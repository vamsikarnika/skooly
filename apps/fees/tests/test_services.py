"""Unit tests for fees/services.py — covers status math, toggle, void,
dues filtering, section_rollup, and recompute_overdue_all."""

from __future__ import annotations

from datetime import date

import pytest

from apps.academics.models import StudentEnrollment
from apps.core.context import use_school
from apps.fees.models import (
    FeeComponent,
    FeeStatus,
    FeeStructure,
    StudentFee,
    StudentFeeComponent,
)
from apps.fees.services import (
    _component_status,
    _overall_status,
    apply_structure_to_class,
    create_structure,
    dues_queryset,
    recompute_overdue_all,
    record_payment,
    section_rollup,
    toggle_optional_component,
    void_payment,
)
from apps.people.tests.factories import StudentFactory

PAST = date(2020, 1, 1)
FUTURE = date(2099, 12, 31)
TODAY = date(2025, 6, 1)


# ---------------------------------------------------------------------------
# _component_status
# ---------------------------------------------------------------------------

def test_component_status_zero_applied_is_paid():
    assert _component_status(0, 0, FUTURE, TODAY) == FeeStatus.PAID


def test_component_status_fully_paid():
    assert _component_status(1000, 1000, PAST, TODAY) == FeeStatus.PAID


def test_component_status_partial():
    assert _component_status(1000, 500, FUTURE, TODAY) == FeeStatus.PARTIAL


def test_component_status_overdue():
    assert _component_status(1000, 0, PAST, TODAY) == FeeStatus.OVERDUE


def test_component_status_pending():
    assert _component_status(1000, 0, FUTURE, TODAY) == FeeStatus.PENDING


# ---------------------------------------------------------------------------
# _overall_status
# ---------------------------------------------------------------------------

def test_overall_status_zero_applied_is_paid():
    assert _overall_status(0, 0, False) == FeeStatus.PAID


def test_overall_status_fully_paid():
    assert _overall_status(1000, 1000, False) == FeeStatus.PAID


def test_overall_status_nothing_paid_not_overdue():
    assert _overall_status(1000, 0, False) == FeeStatus.PENDING


def test_overall_status_nothing_paid_overdue():
    assert _overall_status(1000, 0, True) == FeeStatus.OVERDUE


def test_overall_status_partial_not_overdue():
    assert _overall_status(1000, 500, False) == FeeStatus.PARTIAL


def test_overall_status_partial_overdue():
    assert _overall_status(1000, 500, True) == FeeStatus.OVERDUE


# ---------------------------------------------------------------------------
# Helpers for DB tests
# ---------------------------------------------------------------------------

def _enroll(world, student, *, roll="01", section=None):
    StudentEnrollment.objects.create(
        school=world["school"],
        student=student,
        section=section or world["section_a"],
        academic_year=world["year"],
        roll_number=roll,
        enrollment_date=date(2025, 6, 1),
        status="active",
    )


def _build_structure(world, *, name="Fees 2025", components=None):
    if components is None:
        components = [
            {"name": "Tuition", "amount_paise": 10000_00, "due_date": PAST,
             "is_optional": False, "display_order": 0},
            {"name": "Transport", "amount_paise": 2000_00, "due_date": FUTURE,
             "is_optional": True, "display_order": 1},
        ]
    with use_school(world["school"]):
        return create_structure(
            school=world["school"],
            actor_id=world["admin"].id,
            academic_year_id=world["year"].id,
            class_id=world["class"].id,
            name=name,
            components=components,
        )


def _apply(world, structure=None):
    if structure is None:
        # caller already built a structure; look it up
        structure = FeeStructure.objects.filter(school=world["school"]).first()
    with use_school(world["school"]):
        return apply_structure_to_class(
            school=world["school"],
            actor_id=world["admin"].id,
            structure_id=structure.id,
        )


def _pay(world, sf, component, amount):
    sfc = StudentFeeComponent.objects.all_tenants().get(student_fee=sf, fee_component=component)
    with use_school(world["school"]):
        return record_payment(
            school=world["school"],
            actor_id=world["admin"].id,
            student_fee_id=sf.id,
            allocations=[{"component_id": sfc.id, "amount_paise": amount}],
            payment_mode="cash",
            paid_on=date(2025, 6, 1),
            reference_number="",
            notes="",
        )


# ---------------------------------------------------------------------------
# toggle_optional_component
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_toggle_optional_component_marks_non_applicable(world_a):
    student = StudentFactory(school=world_a["school"], admission_number="T1")
    _enroll(world_a, student)
    structure = _build_structure(world_a)
    _apply(world_a, structure)
    sf = StudentFee.objects.all_tenants().get(student=student)
    transport_comp = FeeComponent.objects.all_tenants().get(fee_structure=structure, name="Transport")
    sfc = StudentFeeComponent.objects.all_tenants().get(student_fee=sf, fee_component=transport_comp)

    with use_school(world_a["school"]):
        result = toggle_optional_component(
            school=world_a["school"],
            actor_id=world_a["admin"].id,
            student_fee_id=sf.id,
            component_id=sfc.id,
            is_applicable=False,
        )
    assert result.is_applicable is False
    sf.refresh_from_db()
    assert sf.final_paise == 10000_00


@pytest.mark.django_db
def test_toggle_non_optional_component_raises(world_a):
    from apps.core.exceptions import ValidationFailed
    student = StudentFactory(school=world_a["school"], admission_number="T2")
    _enroll(world_a, student)
    structure = _build_structure(world_a)
    _apply(world_a, structure)
    sf = StudentFee.objects.all_tenants().get(student=student)
    tuition_comp = FeeComponent.objects.all_tenants().get(fee_structure=structure, name="Tuition")
    sfc = StudentFeeComponent.objects.all_tenants().get(student_fee=sf, fee_component=tuition_comp)

    with use_school(world_a["school"]):
        with pytest.raises(ValidationFailed):
            toggle_optional_component(
                school=world_a["school"],
                actor_id=world_a["admin"].id,
                student_fee_id=sf.id,
                component_id=sfc.id,
                is_applicable=False,
            )


@pytest.mark.django_db
def test_toggle_component_with_payment_raises(world_a):
    from apps.core.exceptions import ValidationFailed
    student = StudentFactory(school=world_a["school"], admission_number="T3")
    _enroll(world_a, student)
    structure = _build_structure(world_a)
    _apply(world_a, structure)
    sf = StudentFee.objects.all_tenants().get(student=student)
    transport_comp = FeeComponent.objects.all_tenants().get(fee_structure=structure, name="Transport")
    sfc = StudentFeeComponent.objects.all_tenants().get(student_fee=sf, fee_component=transport_comp)

    # Opt-in to transport first (optional components start non-applicable)
    with use_school(world_a["school"]):
        toggle_optional_component(
            school=world_a["school"],
            actor_id=world_a["admin"].id,
            student_fee_id=sf.id,
            component_id=sfc.id,
            is_applicable=True,
        )

    # Now pay against it
    _pay(world_a, sf, transport_comp, 500_00)

    # Trying to opt-out after a payment should fail
    with use_school(world_a["school"]):
        with pytest.raises(ValidationFailed, match="non-applicable"):
            toggle_optional_component(
                school=world_a["school"],
                actor_id=world_a["admin"].id,
                student_fee_id=sf.id,
                component_id=sfc.id,
                is_applicable=False,
            )


# ---------------------------------------------------------------------------
# void_payment
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_void_payment_reverses_allocation(world_a):
    student = StudentFactory(school=world_a["school"], admission_number="V1")
    _enroll(world_a, student)
    structure = _build_structure(world_a)
    _apply(world_a, structure)
    sf = StudentFee.objects.all_tenants().get(student=student)
    tuition_comp = FeeComponent.objects.all_tenants().get(fee_structure=structure, name="Tuition")
    payment = _pay(world_a, sf, tuition_comp, 5000_00)

    sf.refresh_from_db()
    assert sf.paid_paise == 5000_00

    with use_school(world_a["school"]):
        void_payment(
            school=world_a["school"],
            actor_id=world_a["admin"].id,
            payment_id=payment.id,
            reason="Entered by mistake",
        )

    sf.refresh_from_db()
    assert sf.paid_paise == 0
    payment.refresh_from_db()
    assert payment.is_voided is True


@pytest.mark.django_db
def test_void_payment_empty_reason_raises(world_a):
    from apps.core.exceptions import ValidationFailed
    student = StudentFactory(school=world_a["school"], admission_number="V2")
    _enroll(world_a, student)
    structure = _build_structure(world_a)
    _apply(world_a, structure)
    sf = StudentFee.objects.all_tenants().get(student=student)
    tuition_comp = FeeComponent.objects.all_tenants().get(fee_structure=structure, name="Tuition")
    payment = _pay(world_a, sf, tuition_comp, 5000_00)

    with use_school(world_a["school"]):
        with pytest.raises(ValidationFailed, match="reason"):
            void_payment(
                school=world_a["school"],
                actor_id=world_a["admin"].id,
                payment_id=payment.id,
                reason="   ",
            )


@pytest.mark.django_db
def test_void_payment_already_voided_raises(world_a):
    from apps.core.exceptions import Conflict
    student = StudentFactory(school=world_a["school"], admission_number="V3")
    _enroll(world_a, student)
    structure = _build_structure(world_a)
    _apply(world_a, structure)
    sf = StudentFee.objects.all_tenants().get(student=student)
    tuition_comp = FeeComponent.objects.all_tenants().get(fee_structure=structure, name="Tuition")
    payment = _pay(world_a, sf, tuition_comp, 5000_00)
    with use_school(world_a["school"]):
        void_payment(school=world_a["school"], actor_id=world_a["admin"].id,
                     payment_id=payment.id, reason="First void")
        with pytest.raises(Conflict, match="voided"):
            void_payment(school=world_a["school"], actor_id=world_a["admin"].id,
                         payment_id=payment.id, reason="Second void")


# ---------------------------------------------------------------------------
# dues_queryset — filter paths
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_dues_queryset_filter_by_status(world_a):
    s1 = StudentFactory(school=world_a["school"], admission_number="D1")
    s2 = StudentFactory(school=world_a["school"], admission_number="D2")
    _enroll(world_a, s1, roll="01")
    _enroll(world_a, s2, roll="02")
    structure = _build_structure(world_a)
    _apply(world_a, structure)

    sf1 = StudentFee.objects.all_tenants().get(student=s1)
    tuition = FeeComponent.objects.all_tenants().get(fee_structure=structure, name="Tuition")
    _pay(world_a, sf1, tuition, 10000_00)

    with use_school(world_a["school"]):
        qs = dues_queryset(school=world_a["school"], status=FeeStatus.OVERDUE)
        student_ids = list(qs.values_list("student_id", flat=True))
    assert s2.id in student_ids
    assert s1.id not in student_ids


@pytest.mark.django_db
def test_dues_queryset_filter_by_class(world_a):
    student = StudentFactory(school=world_a["school"], admission_number="D4")
    _enroll(world_a, student)
    structure = _build_structure(world_a)
    _apply(world_a, structure)

    with use_school(world_a["school"]):
        qs = dues_queryset(school=world_a["school"], class_id=world_a["class"].id)
        assert qs.filter(student=student).exists()

        qs_empty = dues_queryset(school=world_a["school"], class_id=99999)
        assert not qs_empty.exists()


@pytest.mark.django_db
def test_dues_queryset_filter_by_section(world_a):
    s_a = StudentFactory(school=world_a["school"], admission_number="D5")
    s_b = StudentFactory(school=world_a["school"], admission_number="D6")
    _enroll(world_a, s_a, roll="01", section=world_a["section_a"])
    _enroll(world_a, s_b, roll="02", section=world_a["section_b"])
    structure = _build_structure(world_a)
    _apply(world_a, structure)

    with use_school(world_a["school"]):
        qs = dues_queryset(school=world_a["school"], section_id=world_a["section_a"].id)
        student_ids = list(qs.values_list("student_id", flat=True))
    assert s_a.id in student_ids
    assert s_b.id not in student_ids


# ---------------------------------------------------------------------------
# section_rollup
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_section_rollup_returns_correct_counts(world_a):
    s1 = StudentFactory(school=world_a["school"], admission_number="R1")
    s2 = StudentFactory(school=world_a["school"], admission_number="R2")
    _enroll(world_a, s1, roll="01")
    _enroll(world_a, s2, roll="02")
    structure = _build_structure(world_a)
    _apply(world_a, structure)

    sf1 = StudentFee.objects.all_tenants().get(student=s1)
    tuition = FeeComponent.objects.all_tenants().get(fee_structure=structure, name="Tuition")
    _pay(world_a, sf1, tuition, 10000_00)

    with use_school(world_a["school"]):
        result = section_rollup(school=world_a["school"], academic_year_id=world_a["year"].id)
    sec_a = next((r for r in result if r["section_name"] == "A"), None)
    assert sec_a is not None
    assert sec_a["student_count"] == 2
    assert sec_a["collected_paise"] == 10000_00


@pytest.mark.django_db
def test_section_rollup_no_fees_returns_zeros(world_a):
    with use_school(world_a["school"]):
        result = section_rollup(school=world_a["school"])
    for row in result:
        assert row["student_count"] == 0
        assert row["expected_paise"] == 0


# ---------------------------------------------------------------------------
# recompute_overdue_all
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_recompute_overdue_all_returns_count(world_a):
    s1 = StudentFactory(school=world_a["school"], admission_number="OV1")
    s2 = StudentFactory(school=world_a["school"], admission_number="OV2")
    _enroll(world_a, s1, roll="01")
    _enroll(world_a, s2, roll="02")
    structure = _build_structure(world_a)
    _apply(world_a, structure)

    with use_school(world_a["school"]):
        count = recompute_overdue_all(school=world_a["school"])
    assert count == StudentFee.objects.all_tenants().filter(school=world_a["school"]).count()


@pytest.mark.django_db
def test_recompute_overdue_all_no_fees_returns_zero(world_a):
    assert recompute_overdue_all(school=world_a["school"]) == 0


# ---------------------------------------------------------------------------
# create_structure — duplicate name conflict
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_structure_duplicate_name_raises(world_a):
    from apps.core.exceptions import Conflict
    _build_structure(world_a, name="Unique Name")
    with use_school(world_a["school"]):
        with pytest.raises(Conflict):
            _build_structure(world_a, name="Unique Name")
