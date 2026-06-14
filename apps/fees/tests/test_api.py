"""Fees API tests — money math, status transitions, receipt numbering,
voiding, tenant isolation."""

from __future__ import annotations

from datetime import date

import pytest

from apps.academics.models import StudentEnrollment
from apps.fees.models import (
    FeeStatus,
    ReceiptCounter,
    StudentFee,
)
from apps.people.tests.factories import StudentFactory

# ---------- helpers ---------------------------------------------------------

def _enroll(world, student, *, roll="01"):
    StudentEnrollment.objects.create(
        school=world["school"],
        student=student,
        section=world["section_a"],
        academic_year=world["year"],
        roll_number=roll,
        enrollment_date=date(2025, 6, 1),
        status="active",
    )


def _make_structure(world, *, name="Class 6 Fees", components: list[dict] | None = None):
    """Helper that POSTs the structure via the API to exercise the real path."""
    if components is None:
        # Default: tuition (due past), books (future), transport optional
        components = [
            {"name": "Tuition", "amountPaise": 30000_00, "dueDate": "2025-06-01", "isOptional": False},
            {"name": "Books", "amountPaise": 3000_00, "dueDate": "2099-12-31", "isOptional": False},
            {"name": "Transport", "amountPaise": 12000_00, "dueDate": "2099-12-31", "isOptional": True},
        ]
    return {
        "academicYearId": world["year"].id,
        "classId": world["class"].id,
        "name": name,
        "components": components,
    }


# ---------- structures ------------------------------------------------------

@pytest.mark.django_db
def test_create_and_apply_structure(client, admin_token_a, world_a):
    student = StudentFactory(school=world_a["school"], admission_number="S1")
    _enroll(world_a, student)

    payload = _make_structure(world_a)
    res = client.post(
        "/api/v1/fee-structures",
        data=payload,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    structure_id = res.json()["id"]
    assert len(res.json()["components"]) == 3

    # Apply
    res = client.post(
        f"/api/v1/fee-structures/{structure_id}/apply",
        data={},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["created"] == 1
    assert body["totalStudents"] == 1

    # Re-applying is idempotent — no duplicate StudentFee
    res = client.post(
        f"/api/v1/fee-structures/{structure_id}/apply",
        data={},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.json()["created"] == 0
    assert res.json()["skipped"] == 1


@pytest.mark.django_db
def test_apply_status_pending_when_due_in_future(client, admin_token_a, world_a):
    """All components due in the future → status=pending after apply."""
    student = StudentFactory(school=world_a["school"], admission_number="P1")
    _enroll(world_a, student)
    payload = _make_structure(world_a, components=[
        {"name": "Tuition", "amountPaise": 10000_00, "dueDate": "2099-06-01", "isOptional": False},
    ])
    sid = client.post(
        "/api/v1/fee-structures", data=payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    ).json()["id"]
    client.post(
        f"/api/v1/fee-structures/{sid}/apply",
        data={},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )

    sf = StudentFee.objects.all_tenants().filter(school=world_a["school"], student=student).first()
    assert sf is not None
    assert sf.status == FeeStatus.PENDING
    assert sf.final_paise == 10000_00


@pytest.mark.django_db
def test_apply_status_overdue_when_past_due(client, admin_token_a, world_a):
    """A component with due_date in the past → status=overdue."""
    student = StudentFactory(school=world_a["school"], admission_number="O1")
    _enroll(world_a, student)
    payload = _make_structure(world_a, components=[
        {"name": "Tuition", "amountPaise": 10000_00, "dueDate": "2020-06-01", "isOptional": False},
    ])
    sid = client.post(
        "/api/v1/fee-structures", data=payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    ).json()["id"]
    client.post(
        f"/api/v1/fee-structures/{sid}/apply",
        data={},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )

    sf = StudentFee.objects.all_tenants().filter(school=world_a["school"], student=student).first()
    assert sf.status == FeeStatus.OVERDUE


@pytest.mark.django_db
def test_apply_with_section_filter(client, admin_token_a, world_a):
    """When sectionIds is provided, only students in those sections get StudentFees."""
    student_a = StudentFactory(school=world_a["school"], admission_number="SF1")
    _enroll(world_a, student_a)  # default: section_a
    # Enroll a second student in section_b
    student_b = StudentFactory(school=world_a["school"], admission_number="SF2")
    StudentEnrollment.objects.create(
        school=world_a["school"],
        student=student_b,
        section=world_a["section_b"],
        academic_year=world_a["year"],
        roll_number="02",
        enrollment_date=date(2025, 6, 1),
        status="active",
    )

    payload = _make_structure(world_a)
    sid = client.post(
        "/api/v1/fee-structures", data=payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    ).json()["id"]

    # Apply only to section_a
    res = client.post(
        f"/api/v1/fee-structures/{sid}/apply",
        data={"sectionIds": [world_a["section_a"].id]},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["created"] == 1
    assert body["totalStudents"] == 1  # only section_a's roster

    # student_a gets a fee, student_b does not
    assert StudentFee.objects.all_tenants().filter(student=student_a).exists()
    assert not StudentFee.objects.all_tenants().filter(student=student_b).exists()

    # Now apply to both sections — student_a is skipped (idempotent), student_b created
    res = client.post(
        f"/api/v1/fee-structures/{sid}/apply",
        data={"sectionIds": [world_a["section_a"].id, world_a["section_b"].id]},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    body = res.json()
    assert body["created"] == 1
    assert body["skipped"] == 1


@pytest.mark.django_db
def test_apply_rejects_section_from_different_class(client, admin_token_a, world_a):
    """Section must belong to the structure's class."""
    # Make a different class with a section
    from apps.academics.tests.factories import ClassFactory, SectionFactory

    other_class = ClassFactory(
        school=world_a["school"], academic_year=world_a["year"],
        name="Class 7", display_order=7,
    )
    other_section = SectionFactory(
        school=world_a["school"], class_obj=other_class, name="A",
    )

    payload = _make_structure(world_a)  # structure on world_a["class"] (Class 6)
    sid = client.post(
        "/api/v1/fee-structures", data=payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    ).json()["id"]

    # Try to apply with a section from a different class
    res = client.post(
        f"/api/v1/fee-structures/{sid}/apply",
        data={"sectionIds": [other_section.id]},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_optional_component_default_not_applicable(client, admin_token_a, world_a):
    """Optional components are excluded by default — total doesn't include them."""
    student = StudentFactory(school=world_a["school"], admission_number="OP1")
    _enroll(world_a, student)
    payload = _make_structure(world_a, components=[
        {"name": "Tuition", "amountPaise": 10000_00, "dueDate": "2099-06-01", "isOptional": False},
        {"name": "Transport", "amountPaise": 5000_00, "dueDate": "2099-06-01", "isOptional": True},
    ])
    sid = client.post(
        "/api/v1/fee-structures", data=payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    ).json()["id"]
    client.post(
        f"/api/v1/fee-structures/{sid}/apply",
        data={},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )

    sf = StudentFee.objects.all_tenants().filter(school=world_a["school"], student=student).first()
    assert sf.total_paise == 10000_00  # transport excluded
    assert sf.final_paise == 10000_00


@pytest.mark.django_db
def test_structure_cross_tenant_404(client, admin_token_a, world_b):
    """Admin A can't apply structure from school B."""
    payload = _make_structure(world_b)
    res = client.post(
        "/api/v1/fee-structures",
        data=payload,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404


# ---------- payments --------------------------------------------------------

def _setup_one_student_with_fees(client, token, world):
    """Helper: create a structure, apply, return the student_fee dict from the API."""
    student = StudentFactory(school=world["school"], admission_number=f"PAY{world['school'].id}")
    _enroll(world, student)
    payload = _make_structure(world, components=[
        {"name": "Tuition", "amountPaise": 10000_00, "dueDate": "2099-06-01", "isOptional": False},
        {"name": "Books", "amountPaise": 3000_00, "dueDate": "2099-06-01", "isOptional": False},
    ])
    sid = client.post(
        "/api/v1/fee-structures", data=payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    ).json()["id"]
    client.post(
        f"/api/v1/fee-structures/{sid}/apply",
        data={},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    fees = client.get(
        f"/api/v1/students/{student.id}/fees",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    ).json()
    return student, fees[0]


@pytest.mark.django_db
def test_payment_full_marks_paid(client, admin_token_a, world_a):
    student, sf = _setup_one_student_with_fees(client, admin_token_a, world_a)
    # Pay both components in full: 10,000 + 3,000 = 13,000
    payload = {
        "studentFeeId": sf["id"],
        "paidOn": "2026-05-01",
        "paymentMode": "cash",
        "allocations": [
            {"componentId": sf["components"][0]["id"], "amountPaise": 10000_00},
            {"componentId": sf["components"][1]["id"], "amountPaise": 3000_00},
        ],
    }
    res = client.post(
        "/api/v1/payments", data=payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    assert res.json()["totalPaise"] == 13000_00
    assert res.json()["receiptNumber"].endswith("/0001")

    refreshed = StudentFee.objects.all_tenants().get(pk=sf["id"])
    assert refreshed.status == FeeStatus.PAID
    assert refreshed.paid_paise == 13000_00


@pytest.mark.django_db
def test_payment_partial_marks_partial(client, admin_token_a, world_a):
    student, sf = _setup_one_student_with_fees(client, admin_token_a, world_a)
    # Pay half of tuition only
    payload = {
        "studentFeeId": sf["id"],
        "paidOn": "2026-05-01",
        "paymentMode": "cash",
        "allocations": [
            {"componentId": sf["components"][0]["id"], "amountPaise": 5000_00},
        ],
    }
    res = client.post(
        "/api/v1/payments", data=payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    refreshed = StudentFee.objects.all_tenants().get(pk=sf["id"])
    assert refreshed.status == FeeStatus.PARTIAL
    assert refreshed.paid_paise == 5000_00


@pytest.mark.django_db
def test_payment_overpay_component_rejected(client, admin_token_a, world_a):
    """Cannot allocate more to a component than its remaining balance."""
    student, sf = _setup_one_student_with_fees(client, admin_token_a, world_a)
    payload = {
        "studentFeeId": sf["id"],
        "paidOn": "2026-05-01",
        "paymentMode": "cash",
        "allocations": [
            {"componentId": sf["components"][0]["id"], "amountPaise": 999999_00},  # way over
        ],
    }
    res = client.post(
        "/api/v1/payments", data=payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 422


@pytest.mark.django_db
def test_payment_negative_amount_rejected(client, admin_token_a, world_a):
    student, sf = _setup_one_student_with_fees(client, admin_token_a, world_a)
    payload = {
        "studentFeeId": sf["id"],
        "paidOn": "2026-05-01",
        "paymentMode": "cash",
        "allocations": [
            {"componentId": sf["components"][0]["id"], "amountPaise": -100},
        ],
    }
    res = client.post(
        "/api/v1/payments", data=payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 422


@pytest.mark.django_db
def test_void_payment_reverts_status(client, admin_token_a, world_a):
    """Voiding a payment recomputes the student fee status — fully-paid
    student fee reverts to pending/partial after void."""
    student, sf = _setup_one_student_with_fees(client, admin_token_a, world_a)
    # Pay in full
    res = client.post(
        "/api/v1/payments",
        data={
            "studentFeeId": sf["id"],
            "paidOn": "2026-05-01",
            "paymentMode": "cash",
            "allocations": [
                {"componentId": sf["components"][0]["id"], "amountPaise": 10000_00},
                {"componentId": sf["components"][1]["id"], "amountPaise": 3000_00},
            ],
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    payment_id = res.json()["id"]

    assert StudentFee.objects.all_tenants().get(pk=sf["id"]).status == FeeStatus.PAID

    # Void it
    res = client.post(
        f"/api/v1/payments/{payment_id}/void",
        data={"reason": "duplicate entry"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    refreshed = StudentFee.objects.all_tenants().get(pk=sf["id"])
    assert refreshed.status == FeeStatus.PENDING
    assert refreshed.paid_paise == 0


@pytest.mark.django_db
def test_void_already_voided_rejected(client, admin_token_a, world_a):
    student, sf = _setup_one_student_with_fees(client, admin_token_a, world_a)
    res = client.post(
        "/api/v1/payments",
        data={
            "studentFeeId": sf["id"],
            "paidOn": "2026-05-01",
            "paymentMode": "cash",
            "allocations": [
                {"componentId": sf["components"][0]["id"], "amountPaise": 1000_00},
            ],
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    pid = res.json()["id"]
    client.post(
        f"/api/v1/payments/{pid}/void",
        data={"reason": "first void"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    res = client.post(
        f"/api/v1/payments/{pid}/void",
        data={"reason": "second void"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 409


@pytest.mark.django_db
def test_receipt_number_sequential_per_school(client, admin_token_a, world_a):
    """Receipt numbers are sequential within (school, academic year).
    Concurrency safety is guaranteed by the select_for_update lock in
    services._next_receipt_number; here we just verify sequential ordering."""
    student, sf = _setup_one_student_with_fees(client, admin_token_a, world_a)
    receipts: list[str] = []
    for i in range(3):
        res = client.post(
            "/api/v1/payments",
            data={
                "studentFeeId": sf["id"],
                "paidOn": "2026-05-01",
                "paymentMode": "cash",
                "allocations": [
                    {"componentId": sf["components"][0]["id"], "amountPaise": 1000_00},
                ],
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
        )
        receipts.append(res.json()["receiptNumber"])
    # Format: SC/2025-26/0001, /0002, /0003
    sequences = [int(r.split("/")[-1]) for r in receipts]
    assert sequences == [1, 2, 3]
    # All in same (school, year) bucket
    counter = ReceiptCounter.objects.get(school=world_a["school"], academic_year_label="2025-26")
    assert counter.next_number == 4


# ---------- discounts -------------------------------------------------------

@pytest.mark.django_db
def test_apply_discount_reduces_final(client, admin_token_a, world_a):
    student, sf = _setup_one_student_with_fees(client, admin_token_a, world_a)
    # Total = 13,000. Apply ₹3,000 discount → final = 10,000
    res = client.patch(
        f"/api/v1/student-fees/{sf['id']}/discount",
        data={"discountPaise": 3000_00, "reason": "sibling discount"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    refreshed = StudentFee.objects.all_tenants().get(pk=sf["id"])
    assert refreshed.discount_paise == 3000_00
    assert refreshed.final_paise == 10000_00
    assert refreshed.discount_reason == "sibling discount"


@pytest.mark.django_db
def test_discount_exceeding_total_rejected(client, admin_token_a, world_a):
    student, sf = _setup_one_student_with_fees(client, admin_token_a, world_a)
    res = client.patch(
        f"/api/v1/student-fees/{sf['id']}/discount",
        data={"discountPaise": 99999_00, "reason": ""},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 422


@pytest.mark.django_db
def test_paying_after_discount_marks_paid(client, admin_token_a, world_a):
    """If discount brings final to 10k and parent pays 10k → status=paid."""
    student, sf = _setup_one_student_with_fees(client, admin_token_a, world_a)
    client.patch(
        f"/api/v1/student-fees/{sf['id']}/discount",
        data={"discountPaise": 3000_00, "reason": "scholarship"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    # Pay 10k towards tuition (whole tuition component)
    client.post(
        "/api/v1/payments",
        data={
            "studentFeeId": sf["id"],
            "paidOn": "2026-05-01",
            "paymentMode": "cash",
            "allocations": [
                {"componentId": sf["components"][0]["id"], "amountPaise": 10000_00},
            ],
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    refreshed = StudentFee.objects.all_tenants().get(pk=sf["id"])
    # Tuition fully paid; books unpaid (3k). But discount applies at
    # student-fee level: final=10k, paid=10k → status=paid.
    assert refreshed.final_paise == 10000_00
    assert refreshed.paid_paise == 10000_00
    assert refreshed.status == FeeStatus.PAID


# ---------- permission + tenant isolation -----------------------------------

@pytest.mark.django_db
def test_teacher_cannot_create_structure(client, teacher_token_a, world_a):
    res = client.post(
        "/api/v1/fee-structures",
        data=_make_structure(world_a),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {teacher_token_a}",
    )
    assert res.status_code == 403


@pytest.mark.django_db
def test_teacher_cannot_record_payment(client, teacher_token_a, world_a, admin_token_a):
    """Set up a payable fee as admin, confirm teacher can't pay."""
    student, sf = _setup_one_student_with_fees(client, admin_token_a, world_a)
    res = client.post(
        "/api/v1/payments",
        data={
            "studentFeeId": sf["id"],
            "paidOn": "2026-05-01",
            "paymentMode": "cash",
            "allocations": [
                {"componentId": sf["components"][0]["id"], "amountPaise": 100_00},
            ],
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {teacher_token_a}",
    )
    assert res.status_code == 403


@pytest.mark.django_db
def test_cross_tenant_payment_not_found(client, admin_token_a, world_a, world_b, admin_token_b):
    """Admin A can't pay against School B's student fee."""
    student_b, sf_b = _setup_one_student_with_fees(client, admin_token_b, world_b)
    res = client.post(
        "/api/v1/payments",
        data={
            "studentFeeId": sf_b["id"],
            "paidOn": "2026-05-01",
            "paymentMode": "cash",
            "allocations": [
                {"componentId": sf_b["components"][0]["id"], "amountPaise": 100_00},
            ],
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_cross_tenant_void_not_found(client, admin_token_a, world_b, admin_token_b):
    """Admin A can't void a payment from School B."""
    student_b, sf_b = _setup_one_student_with_fees(client, admin_token_b, world_b)
    pay_res = client.post(
        "/api/v1/payments",
        data={
            "studentFeeId": sf_b["id"],
            "paidOn": "2026-05-01",
            "paymentMode": "cash",
            "allocations": [
                {"componentId": sf_b["components"][0]["id"], "amountPaise": 100_00},
            ],
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_b}",
    )
    pid = pay_res.json()["id"]
    res = client.post(
        f"/api/v1/payments/{pid}/void",
        data={"reason": "hack attempt"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_dues_only_shows_unpaid(client, admin_token_a, world_a):
    student, sf = _setup_one_student_with_fees(client, admin_token_a, world_a)
    # Initially in dues (status=pending since due is in 2099 actually)
    res = client.get(
        "/api/v1/fees/dues",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200
    initial_count = res.json()["count"]
    assert initial_count >= 1

    # Pay full → drops out of dues
    client.post(
        "/api/v1/payments",
        data={
            "studentFeeId": sf["id"],
            "paidOn": "2026-05-01",
            "paymentMode": "cash",
            "allocations": [
                {"componentId": sf["components"][0]["id"], "amountPaise": 10000_00},
                {"componentId": sf["components"][1]["id"], "amountPaise": 3000_00},
            ],
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    res = client.get(
        "/api/v1/fees/dues",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.json()["count"] == initial_count - 1


# ---------- safety net ------------------------------------------------------

@pytest.mark.django_db
def test_no_floats_in_money_fields():
    """Defence-in-depth: any drift to float anywhere in the money math is a
    serious bug. This test asserts that the model fields are all integer types."""
    from django.db.models import PositiveBigIntegerField

    money_fields = [
        ("FeeComponent", "amount_paise"),
        ("StudentFee", "total_paise"),
        ("StudentFee", "discount_paise"),
        ("StudentFee", "final_paise"),
        ("StudentFee", "paid_paise"),
        ("StudentFeeComponent", "applied_paise"),
        ("StudentFeeComponent", "paid_paise"),
        ("FeePayment", "total_paise"),
        ("FeePaymentComponent", "amount_paise"),
    ]
    from apps.fees import models

    for cls_name, field_name in money_fields:
        cls = getattr(models, cls_name)
        field = cls._meta.get_field(field_name)
        assert isinstance(
            field, PositiveBigIntegerField
        ), f"{cls_name}.{field_name} must be PositiveBigIntegerField, got {type(field).__name__}"


@pytest.mark.django_db
def test_structure_detail_includes_section_status(client, admin_token_a, world_a):
    """Detail endpoint reports per-section apply status; list endpoint omits it."""
    student = StudentFactory(school=world_a["school"], admission_number="SS1")
    _enroll(world_a, student)  # section_a
    sid = client.post(
        "/api/v1/fee-structures",
        data=_make_structure(world_a),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    ).json()["id"]

    # Apply to section A only.
    client.post(
        f"/api/v1/fee-structures/{sid}/apply",
        data={"sectionIds": [world_a["section_a"].id]},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )

    res = client.get(
        f"/api/v1/fee-structures/{sid}", HTTP_AUTHORIZATION=f"Bearer {admin_token_a}"
    )
    assert res.status_code == 200, res.content
    secs = {s["name"]: s for s in res.json()["sections"]}
    assert secs["A"]["studentCount"] == 1
    assert secs["A"]["appliedCount"] == 1
    assert secs["B"]["appliedCount"] == 0

    # List endpoint stays light (no per-section status).
    lst = client.get("/api/v1/fee-structures", HTTP_AUTHORIZATION=f"Bearer {admin_token_a}")
    assert lst.json()[0]["sections"] == []
