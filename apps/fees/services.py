"""Fees business logic.

All money is integer paise. Status recomputation runs inside the same
transaction that mutates payments/discounts so we never expose a stale
status across a request boundary.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.academics.models import Class, StudentEnrollment
from apps.core.audit import log_action
from apps.core.exceptions import Conflict, NotFound, ValidationFailed
from apps.core.helpers import get_in_tenant
from apps.fees.models import (
    FeeComponent,
    FeePayment,
    FeePaymentComponent,
    FeeStatus,
    FeeStructure,
    ReceiptCounter,
    StudentFee,
    StudentFeeComponent,
)
from apps.schools.models import AcademicYear, School

# --- Status math -------------------------------------------------------------

def _component_status(applied: int, paid: int, due_date: date, today: date | None = None) -> str:
    if applied <= 0:
        return FeeStatus.PAID
    if paid >= applied:
        return FeeStatus.PAID
    if paid > 0:
        return FeeStatus.PARTIAL
    if (today or timezone.now().date()) > due_date:
        return FeeStatus.OVERDUE
    return FeeStatus.PENDING


def _overall_status(applied: int, paid: int, any_overdue: bool) -> str:
    if applied <= 0:
        return FeeStatus.PAID
    if paid >= applied:
        return FeeStatus.PAID
    if paid == 0:
        return FeeStatus.OVERDUE if any_overdue else FeeStatus.PENDING
    return FeeStatus.OVERDUE if any_overdue else FeeStatus.PARTIAL


def recompute_student_fee(student_fee: StudentFee, *, today: date | None = None) -> None:
    """Recompute paid_paise, per-component status, and overall status.
    Always call inside a transaction with the StudentFee already selected_for_update.
    """
    today = today or timezone.now().date()
    components = list(
        StudentFeeComponent.objects.filter(student_fee=student_fee).select_related("fee_component")
    )

    any_overdue = False
    applicable_applied = 0
    applicable_paid = 0
    for c in components:
        if not c.is_applicable:
            continue
        new_status = _component_status(c.applied_paise, c.paid_paise, c.fee_component.due_date, today)
        if new_status != c.status:
            c.status = new_status
            c.save(update_fields=["status", "updated_at"])
        applicable_applied += c.applied_paise
        applicable_paid += c.paid_paise
        if new_status == FeeStatus.OVERDUE:
            any_overdue = True

    # Discount applies at the StudentFee level. The "final" is total minus discount.
    final = max(0, applicable_applied - student_fee.discount_paise)
    status = _overall_status(final, applicable_paid, any_overdue)

    StudentFee.objects.filter(pk=student_fee.pk).update(
        total_paise=applicable_applied,
        final_paise=final,
        paid_paise=applicable_paid,
        status=status,
    )


# --- Structures -------------------------------------------------------------

@transaction.atomic
def create_structure(
    *,
    school: School,
    actor_id: int,
    academic_year_id: int,
    class_id: int,
    name: str,
    components: list[dict[str, Any]],
) -> FeeStructure:
    year = get_in_tenant(AcademicYear, school, pk=academic_year_id)
    cls = get_in_tenant(Class, school, pk=class_id)
    if FeeStructure.objects.filter(
        school=school, academic_year=year, class_obj=cls, name=name
    ).exists():
        raise Conflict("A structure with that name already exists for this class/year.")

    structure = FeeStructure.objects.create(
        school=school, academic_year=year, class_obj=cls, name=name
    )
    for idx, c in enumerate(components):
        FeeComponent.objects.create(
            school=school,
            fee_structure=structure,
            name=c["name"],
            amount_paise=c["amount_paise"],
            due_date=c["due_date"],
            is_optional=c.get("is_optional", False),
            display_order=c.get("display_order", idx),
        )
    log_action(
        school_id=school.id, user_id=actor_id, action="fee_structure.create",
        model_name="FeeStructure", object_id=structure.id,
    )
    return structure


@transaction.atomic
def apply_structure_to_class(
    *,
    school: School,
    actor_id: int,
    structure_id: int,
    section_ids: list[int] | None = None,
) -> dict[str, int]:
    """Idempotent: for every active student in the structure's class who
    doesn't yet have a StudentFee for this structure, create one + components.
    Existing StudentFees are left alone (no auto-update if components change).

    When ``section_ids`` is provided, only enroll students in those sections.
    Sections that don't belong to the structure's class are rejected (404).
    Leaving it None applies to all sections in the class (legacy behaviour).
    """
    from apps.academics.models import Section

    structure = (
        FeeStructure.objects.filter(school=school, pk=structure_id)
        .select_related("class_obj", "academic_year")
        .prefetch_related("components")
        .first()
    )
    if structure is None:
        raise NotFound("Fee structure not found.")

    components = list(structure.components.all())
    if not components:
        raise ValidationFailed("Structure has no components; nothing to apply.")

    # Validate any provided sections belong to the structure's class.
    if section_ids:
        valid_section_ids = set(
            Section.objects.filter(
                school=school, class_obj=structure.class_obj, id__in=section_ids
            ).values_list("id", flat=True)
        )
        missing = set(section_ids) - valid_section_ids
        if missing:
            raise NotFound(
                "One or more sections do not belong to this structure's class.",
            )

    enroll_qs = StudentEnrollment.objects.filter(
        school=school,
        section__class_obj=structure.class_obj,
        academic_year=structure.academic_year,
        status="active",
    ).select_related("student")
    if section_ids:
        enroll_qs = enroll_qs.filter(section_id__in=section_ids)
    enrollments = list(enroll_qs)

    created = 0
    skipped = 0
    for enrollment in enrollments:
        student = enrollment.student
        if StudentFee.objects.filter(school=school, student=student, fee_structure=structure).exists():
            skipped += 1
            continue
        sf = StudentFee.objects.create(
            school=school,
            student=student,
            fee_structure=structure,
            academic_year=structure.academic_year,
        )
        applicable_total = 0
        for c in components:
            applicable = not c.is_optional
            StudentFeeComponent.objects.create(
                school=school,
                student_fee=sf,
                fee_component=c,
                applied_paise=c.amount_paise,
                is_applicable=applicable,
            )
            if applicable:
                applicable_total += c.amount_paise
        StudentFee.objects.filter(pk=sf.pk).update(
            total_paise=applicable_total, final_paise=applicable_total
        )
        recompute_student_fee(sf)
        created += 1

    if not structure.applied_at:
        structure.applied_at = timezone.now()
        structure.save(update_fields=["applied_at", "updated_at"])

    log_action(
        school_id=school.id, user_id=actor_id, action="fee_structure.apply",
        model_name="FeeStructure", object_id=structure.id,
        changes={"created": created, "skipped": skipped},
    )
    return {"created": created, "skipped": skipped, "total_students": len(enrollments)}


# --- Student fees -----------------------------------------------------------

@transaction.atomic
def apply_discount(
    *, school: School, actor_id: int, student_fee_id: int,
    discount_paise: int, reason: str = "",
) -> StudentFee:
    if discount_paise < 0:
        raise ValidationFailed("Discount cannot be negative.")
    sf = (
        StudentFee.objects.select_for_update()
        .filter(school=school, pk=student_fee_id)
        .first()
    )
    if sf is None:
        raise NotFound("Student fee not found.")
    if discount_paise > sf.total_paise:
        raise ValidationFailed("Discount cannot exceed total.")
    sf.discount_paise = discount_paise
    sf.discount_reason = reason
    sf.save(update_fields=["discount_paise", "discount_reason", "updated_at"])
    recompute_student_fee(sf)
    sf.refresh_from_db()
    log_action(
        school_id=school.id, user_id=actor_id, action="student_fee.discount",
        model_name="StudentFee", object_id=sf.id,
        changes={"discount_paise": discount_paise, "reason": reason},
    )
    return sf


@transaction.atomic
def toggle_optional_component(
    *, school: School, actor_id: int, student_fee_id: int,
    component_id: int, is_applicable: bool,
) -> StudentFeeComponent:
    sfc = (
        StudentFeeComponent.objects.select_for_update()
        .filter(
            school=school,
            student_fee_id=student_fee_id,
            fee_component_id=component_id,
        )
        .select_related("fee_component", "student_fee")
        .first()
    )
    if sfc is None:
        raise NotFound("Component not found for this student fee.")
    if not sfc.fee_component.is_optional:
        raise ValidationFailed("Component is not optional; cannot toggle.")
    if sfc.paid_paise > 0 and not is_applicable:
        raise ValidationFailed(
            "Cannot mark a component non-applicable when payments have been allocated to it.",
        )
    sfc.is_applicable = is_applicable
    sfc.save(update_fields=["is_applicable", "updated_at"])
    recompute_student_fee(sfc.student_fee)
    log_action(
        school_id=school.id, user_id=actor_id, action="student_fee_component.toggle",
        model_name="StudentFeeComponent", object_id=sfc.id,
        changes={"is_applicable": is_applicable},
    )
    return sfc


# --- Receipts ---------------------------------------------------------------

def _next_receipt_number(school: School, year_label: str) -> str:
    """Lock & increment the per-school per-year counter.
    Caller MUST be inside transaction.atomic()."""
    counter, _ = ReceiptCounter.objects.select_for_update().get_or_create(
        school=school, academic_year_label=year_label,
    )
    seq = counter.next_number
    counter.next_number = seq + 1
    counter.save(update_fields=["next_number"])

    prefix = "".join(c for c in school.name[:2].upper() if c.isalpha()) or "SK"
    return f"{prefix}/{year_label}/{seq:04d}"


# --- Payments ---------------------------------------------------------------

@transaction.atomic
def record_payment(
    *,
    school: School,
    actor_id: int,
    student_fee_id: int,
    paid_on: date,
    payment_mode: str,
    reference_number: str,
    notes: str,
    allocations: list[dict[str, Any]],
) -> FeePayment:
    """Record a payment with explicit per-component allocations.

    ``allocations`` is a list of ``{component_id, amount_paise}``. The sum of
    allocations is the payment total. Each allocation must not exceed the
    remaining unpaid amount on that component. Receipt number is grabbed under
    a select_for_update lock on the per-school counter.
    """
    sf = (
        StudentFee.objects.select_for_update()
        .filter(school=school, pk=student_fee_id)
        .select_related("academic_year")
        .first()
    )
    if sf is None:
        raise NotFound("Student fee not found.")

    if not allocations:
        raise ValidationFailed("Payment must allocate to at least one component.")
    if any(a.get("amount_paise", 0) <= 0 for a in allocations):
        raise ValidationFailed("Each allocation amount must be positive.")

    total = sum(a["amount_paise"] for a in allocations)
    if total <= 0:
        raise ValidationFailed("Payment total must be positive.")

    # Fetch + lock components for this student_fee that are mentioned in the
    # allocations. select_for_update prevents two payments racing on the same
    # component.
    component_ids = [a["component_id"] for a in allocations]
    sfcs = {
        sfc.id: sfc
        for sfc in StudentFeeComponent.objects.select_for_update().filter(
            school=school, student_fee=sf, id__in=component_ids
        )
    }
    if len(sfcs) != len(set(component_ids)):
        raise ValidationFailed("One or more component_ids do not belong to this student fee.")

    # Validate each allocation against remaining unpaid amount on that component.
    for a in allocations:
        sfc = sfcs[a["component_id"]]
        if not sfc.is_applicable:
            raise ValidationFailed(
                f"Component '{sfc.fee_component_id}' is not applicable; cannot allocate to it.",
            )
        remaining = max(0, sfc.applied_paise - sfc.paid_paise)
        if a["amount_paise"] > remaining:
            raise ValidationFailed(
                "Allocation exceeds remaining balance on a component.",
                {"componentId": [str(sfc.id)], "remaining": [str(remaining)]},
            )

    receipt_number = _next_receipt_number(school, sf.academic_year.label)
    payment = FeePayment.objects.create(
        school=school,
        student_fee=sf,
        total_paise=total,
        payment_mode=payment_mode,
        reference_number=reference_number,
        paid_on=paid_on,
        received_by_id=actor_id,
        receipt_number=receipt_number,
        notes=notes,
    )

    for a in allocations:
        sfc = sfcs[a["component_id"]]
        FeePaymentComponent.objects.create(
            school=school,
            payment=payment,
            student_fee_component=sfc,
            amount_paise=a["amount_paise"],
        )
        StudentFeeComponent.objects.filter(pk=sfc.id).update(
            paid_paise=sfc.paid_paise + a["amount_paise"]
        )

    recompute_student_fee(sf)
    log_action(
        school_id=school.id, user_id=actor_id, action="payment.record",
        model_name="FeePayment", object_id=payment.id,
        changes={"receipt_number": receipt_number, "total_paise": total},
    )
    return payment


@transaction.atomic
def void_payment(
    *, school: School, actor_id: int, payment_id: int, reason: str
) -> FeePayment:
    if not reason.strip():
        raise ValidationFailed("Void reason required.")
    payment = (
        FeePayment.objects.select_for_update()
        .filter(school=school, pk=payment_id)
        .select_related("student_fee")
        .first()
    )
    if payment is None:
        raise NotFound("Payment not found.")
    if payment.is_voided:
        raise Conflict("Payment already voided.")

    # Reverse allocations.
    allocations = list(payment.allocations.all().select_related("student_fee_component"))
    for alloc in allocations:
        sfc = alloc.student_fee_component
        new_paid = max(0, sfc.paid_paise - alloc.amount_paise)
        StudentFeeComponent.objects.filter(pk=sfc.id).update(paid_paise=new_paid)

    payment.voided_at = timezone.now()
    payment.voided_reason = reason
    payment.voided_by_id = actor_id
    payment.save(update_fields=["voided_at", "voided_reason", "voided_by", "updated_at"])

    # Re-lock student fee + recompute.
    sf = StudentFee.objects.select_for_update().get(pk=payment.student_fee_id)
    recompute_student_fee(sf)

    log_action(
        school_id=school.id, user_id=actor_id, action="payment.void",
        model_name="FeePayment", object_id=payment.id,
        changes={"reason": reason},
    )
    return payment


# --- Dashboard / dues -------------------------------------------------------

def dues_queryset(
    *,
    school: School,
    class_id: int | None = None,
    section_id: int | None = None,
    status: str | None = None,
):
    qs = (
        StudentFee.objects.filter(school=school)
        .exclude(status=FeeStatus.PAID)
        .select_related(
            "student",
            "fee_structure__class_obj",
            "academic_year",
        )
    )
    if status:
        qs = qs.filter(status=status)
    if class_id:
        qs = qs.filter(fee_structure__class_obj_id=class_id)
    if section_id:
        qs = qs.filter(
            student__enrollments__section_id=section_id,
            student__enrollments__status="active",
        )
    return qs.order_by("fee_structure__class_obj__display_order", "student__first_name")


def section_rollup(
    *, school: School, academic_year_id: int | None = None
) -> list[dict[str, Any]]:
    from apps.academics.models import Section

    sections = (
        Section.objects.filter(school=school)
        .select_related("class_obj")
        .order_by("class_obj__display_order", "name")
    )

    enroll_qs = StudentEnrollment.objects.filter(
        school=school, status="active"
    )
    if academic_year_id:
        enroll_qs = enroll_qs.filter(academic_year_id=academic_year_id)

    # student_id -> section_id
    student_section: dict[int, int] = {}
    for e in enroll_qs:
        student_section[e.student_id] = e.section_id

    fees_qs = StudentFee.objects.filter(
        school=school, student_id__in=student_section.keys()
    )
    if academic_year_id:
        fees_qs = fees_qs.filter(academic_year_id=academic_year_id)

    per_section: dict[int, dict[str, int]] = {}
    for sf in fees_qs:
        sec_id = student_section.get(sf.student_id)
        if sec_id is None:
            continue
        b = per_section.setdefault(
            sec_id,
            {"expected_paise": 0, "collected_paise": 0, "paid_count": 0, "partial_count": 0,
             "pending_count": 0, "overdue_count": 0, "student_count": 0},
        )
        b["expected_paise"] += sf.final_paise
        b["collected_paise"] += sf.paid_paise
        b["student_count"] += 1
        b[f"{sf.status}_count"] = b.get(f"{sf.status}_count", 0) + 1

    out = []
    for section in sections:
        b = per_section.get(section.id, {
            "expected_paise": 0, "collected_paise": 0, "paid_count": 0,
            "partial_count": 0, "pending_count": 0, "overdue_count": 0, "student_count": 0,
        })
        out.append({
            "section_id": section.id,
            "section_name": section.name,
            "class_id": section.class_obj_id,
            "class_name": section.class_obj.name,
            "display_order": section.class_obj.display_order,
            "student_count": b["student_count"],
            "expected_paise": b["expected_paise"],
            "collected_paise": b["collected_paise"],
            "outstanding_paise": max(0, b["expected_paise"] - b["collected_paise"]),
            "paid_count": b["paid_count"],
            "partial_count": b["partial_count"],
            "pending_count": b["pending_count"],
            "overdue_count": b["overdue_count"],
        })
    return out


def recompute_overdue_all(*, school: School) -> int:
    """Nightly drift-correction. Re-recomputes every StudentFee in the school
    so newly-passed due dates get reflected. Safe to run any time."""
    fees = list(StudentFee.objects.filter(school=school).only("id"))
    today = timezone.now().date()
    count = 0
    for sf in fees:
        with transaction.atomic():
            locked = StudentFee.objects.select_for_update().get(pk=sf.pk)
            recompute_student_fee(locked, today=today)
            count += 1
    return count


def default_window() -> tuple[date, date]:
    today = timezone.now().date()
    return today - timedelta(days=30), today
