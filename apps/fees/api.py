"""Fees endpoints."""

from __future__ import annotations

from datetime import date as date_type

from django.http import HttpRequest
from ninja import Query, Router

from apps.accounts.auth import jwt_auth
from apps.accounts.models import Role
from apps.core.exceptions import Forbidden, NotFound
from apps.core.helpers import get_in_tenant
from apps.core.pagination import paginate
from apps.core.schemas import ActionResponse
from apps.fees import services
from apps.fees.models import (
    FeePayment,
    FeeStructure,
    StudentFee,
)
from apps.fees.schemas import (
    ApplyStructureRequest,
    ApplyStructureResponse,
    DiscountRequest,
    DuesListOut,
    FeesRollupOut,
    FeeStructureCreateRequest,
    FeeStructureOut,
    PaymentCreateRequest,
    PaymentListOut,
    PaymentOut,
    StudentFeeOut,
    ToggleComponentRequest,
    VoidPaymentRequest,
)
from apps.people.models import Student

router = Router(tags=["fees"], auth=jwt_auth, by_alias=True)


def _user(request: HttpRequest):  # type: ignore[no-untyped-def]
    return request.auth  # type: ignore[attr-defined]


def _require_admin(request: HttpRequest) -> None:
    if _user(request).role != Role.ADMIN:
        raise Forbidden("Admin role required.")


def _school(request: HttpRequest):  # type: ignore[no-untyped-def]
    school = _user(request).school
    if school is None:
        raise NotFound("Current user has no school.")
    return school


# --- Serialization helpers --------------------------------------------------

def _structure_to_dict(structure: FeeStructure) -> dict:
    return {
        "id": structure.id,
        "name": structure.name,
        "academic_year_id": structure.academic_year_id,
        "academic_year_label": structure.academic_year.label,
        "class_id": structure.class_obj_id,
        "class_name": structure.class_obj.name,
        "applied_at": structure.applied_at,
        "components": [
            {
                "id": c.id,
                "name": c.name,
                "amount_paise": c.amount_paise,
                "due_date": c.due_date,
                "is_optional": c.is_optional,
                "display_order": c.display_order,
            }
            for c in structure.components.all()
        ],
    }


def _student_fee_to_dict(sf: StudentFee) -> dict:
    student = sf.student
    active_enrollment = next(
        (e for e in student.enrollments.all() if e.status == "active"), None
    )
    components_out = []
    for c in sf.components.all():
        components_out.append({
            "id": c.id,
            "fee_component_id": c.fee_component_id,
            "name": c.fee_component.name,
            "applied_paise": c.applied_paise,
            "paid_paise": c.paid_paise,
            "is_applicable": c.is_applicable,
            "is_optional": c.fee_component.is_optional,
            "due_date": c.fee_component.due_date,
            "status": c.status,
        })
    return {
        "id": sf.id,
        "student_id": student.id,
        "student_name": student.full_name,
        "admission_number": student.admission_number,
        "class_name": active_enrollment.section.class_obj.name if active_enrollment else None,
        "section_name": active_enrollment.section.name if active_enrollment else None,
        "academic_year_label": sf.academic_year.label,
        "structure_name": sf.fee_structure.name,
        "total_paise": sf.total_paise,
        "discount_paise": sf.discount_paise,
        "final_paise": sf.final_paise,
        "paid_paise": sf.paid_paise,
        "outstanding_paise": max(0, sf.final_paise - sf.paid_paise),
        "discount_reason": sf.discount_reason,
        "status": sf.status,
        "components": components_out,
    }


def _payment_to_dict(payment: FeePayment) -> dict:
    sf = payment.student_fee
    student = sf.student
    allocations = []
    for a in payment.allocations.all():
        allocations.append({
            "component_id": a.student_fee_component.fee_component_id,
            "component_name": a.student_fee_component.fee_component.name,
            "amount_paise": a.amount_paise,
        })
    return {
        "id": payment.id,
        "receipt_number": payment.receipt_number,
        "student_fee_id": sf.id,
        "student_id": student.id,
        "student_name": student.full_name,
        "total_paise": payment.total_paise,
        "payment_mode": payment.payment_mode,
        "reference_number": payment.reference_number,
        "paid_on": payment.paid_on,
        "received_by_name": (
            payment.received_by.full_name if payment.received_by else None
        ),
        "notes": payment.notes,
        "receipt_pdf_url": payment.receipt_pdf_url,
        "voided_at": payment.voided_at,
        "voided_reason": payment.voided_reason,
        "allocations": allocations,
    }


# --- Structures -------------------------------------------------------------

@router.get("/fee-structures", response=list[FeeStructureOut])
def list_structures(
    request: HttpRequest,
    academic_year_id: int | None = Query(default=None, alias="academicYearId"),
    class_id: int | None = Query(default=None, alias="classId"),
) -> list[dict]:
    school = _school(request)
    qs = (
        FeeStructure.objects.filter(school=school)
        .select_related("academic_year", "class_obj")
        .prefetch_related("components")
    )
    if academic_year_id:
        qs = qs.filter(academic_year_id=academic_year_id)
    if class_id:
        qs = qs.filter(class_obj_id=class_id)
    return [_structure_to_dict(s) for s in qs]


@router.post("/fee-structures", response=FeeStructureOut)
def create_structure(
    request: HttpRequest, payload: FeeStructureCreateRequest
) -> dict:
    _require_admin(request)
    structure = services.create_structure(
        school=_school(request),
        actor_id=_user(request).id,
        academic_year_id=payload.academic_year_id,
        class_id=payload.class_id,
        name=payload.name,
        components=[c.model_dump(by_alias=False) for c in payload.components],
    )
    structure = (
        FeeStructure.objects.select_related("academic_year", "class_obj")
        .prefetch_related("components")
        .get(pk=structure.id)
    )
    return _structure_to_dict(structure)


@router.get("/fee-structures/{structure_id}", response=FeeStructureOut)
def get_structure(request: HttpRequest, structure_id: int) -> dict:
    school = _school(request)
    structure = (
        FeeStructure.objects.filter(school=school, pk=structure_id)
        .select_related("academic_year", "class_obj")
        .prefetch_related("components")
        .first()
    )
    if structure is None:
        raise NotFound("Fee structure not found.")
    return _structure_to_dict(structure)


@router.post("/fee-structures/{structure_id}/apply", response=ApplyStructureResponse)
def apply_structure(
    request: HttpRequest,
    structure_id: int,
    payload: ApplyStructureRequest = ApplyStructureRequest(),
) -> dict:
    """Body shape: ``{"sectionIds": [1, 2]}`` to apply only to those sections,
    or ``{}`` / no body to apply to all sections in the structure's class."""
    _require_admin(request)
    section_ids = payload.section_ids if payload.section_ids else None
    return services.apply_structure_to_class(
        school=_school(request),
        actor_id=_user(request).id,
        structure_id=structure_id,
        section_ids=section_ids,
    )


# --- Student fees -----------------------------------------------------------

@router.get("/students/{student_id}/fees", response=list[StudentFeeOut])
def get_student_fees(request: HttpRequest, student_id: int) -> list[dict]:
    school = _school(request)
    student = get_in_tenant(Student, school, pk=student_id)
    qs = (
        StudentFee.objects.filter(school=school, student=student)
        .select_related("fee_structure__class_obj", "academic_year", "student")
        .prefetch_related(
            "components__fee_component", "student__enrollments__section__class_obj"
        )
    )
    return [_student_fee_to_dict(sf) for sf in qs]


@router.patch("/student-fees/{student_fee_id}/discount", response=StudentFeeOut)
def apply_discount(
    request: HttpRequest, student_fee_id: int, payload: DiscountRequest
) -> dict:
    _require_admin(request)
    sf = services.apply_discount(
        school=_school(request),
        actor_id=_user(request).id,
        student_fee_id=student_fee_id,
        discount_paise=payload.discount_paise,
        reason=payload.reason,
    )
    sf = (
        StudentFee.objects.select_related("fee_structure__class_obj", "academic_year", "student")
        .prefetch_related("components__fee_component", "student__enrollments__section__class_obj")
        .get(pk=sf.id)
    )
    return _student_fee_to_dict(sf)


@router.post(
    "/student-fees/{student_fee_id}/components/{component_id}/toggle",
    response=ActionResponse,
)
def toggle_component(
    request: HttpRequest,
    student_fee_id: int,
    component_id: int,
    payload: ToggleComponentRequest,
) -> ActionResponse:
    _require_admin(request)
    services.toggle_optional_component(
        school=_school(request),
        actor_id=_user(request).id,
        student_fee_id=student_fee_id,
        component_id=component_id,
        is_applicable=payload.is_applicable,
    )
    return ActionResponse(success=True, message="Component updated.")


# --- Payments ---------------------------------------------------------------

@router.get("/payments", response=PaymentListOut)
def list_payments(
    request: HttpRequest,
    student_id: int | None = Query(default=None, alias="studentId"),
    from_date: date_type | None = Query(default=None, alias="from"),
    to_date: date_type | None = Query(default=None, alias="to"),
    include_voided: bool = Query(default=False, alias="includeVoided"),
    page: int = Query(default=1),
    page_size: int = Query(default=50, alias="pageSize"),
) -> dict:
    school = _school(request)
    qs = (
        FeePayment.objects.filter(school=school)
        .select_related("student_fee__student", "received_by")
        .prefetch_related("allocations__student_fee_component__fee_component")
    )
    if student_id:
        qs = qs.filter(student_fee__student_id=student_id)
    if from_date:
        qs = qs.filter(paid_on__gte=from_date)
    if to_date:
        qs = qs.filter(paid_on__lte=to_date)
    if not include_voided:
        qs = qs.filter(voided_at__isnull=True)
    payload = paginate(qs, page=page, page_size=page_size)
    payload["items"] = [_payment_to_dict(p) for p in payload["items"]]
    return payload


@router.post("/payments", response=PaymentOut)
def record_payment(request: HttpRequest, payload: PaymentCreateRequest) -> dict:
    _require_admin(request)
    school = _school(request)
    payment = services.record_payment(
        school=school,
        actor_id=_user(request).id,
        student_fee_id=payload.student_fee_id,
        paid_on=payload.paid_on,
        payment_mode=payload.payment_mode,
        reference_number=payload.reference_number,
        notes=payload.notes,
        allocations=[a.model_dump(by_alias=False) for a in payload.allocations],
    )
    # Generate receipt PDF outside the critical section (txn already committed).
    # Lazy import — WeasyPrint pulls in system libs we don't want at module load.
    try:
        from apps.fees import receipt_pdf

        pdf_url = receipt_pdf.generate_and_store_receipt(payment)
        FeePayment.objects.filter(pk=payment.id).update(receipt_pdf_url=pdf_url)
        payment.receipt_pdf_url = pdf_url
    except Exception as exc:  # pragma: no cover - PDF gen is best-effort
        # Don't fail the payment because PDF generation choked (e.g. WeasyPrint
        # system libs missing in dev). URL stays empty and admin can regenerate.
        import logging

        logging.getLogger(__name__).warning("Receipt PDF generation failed: %s", exc)

    payment = (
        FeePayment.objects.select_related("student_fee__student", "received_by")
        .prefetch_related("allocations__student_fee_component__fee_component")
        .get(pk=payment.id)
    )
    return _payment_to_dict(payment)


@router.get("/payments/{payment_id}", response=PaymentOut)
def get_payment(request: HttpRequest, payment_id: int) -> dict:
    school = _school(request)
    payment = (
        FeePayment.objects.filter(school=school, pk=payment_id)
        .select_related("student_fee__student", "received_by")
        .prefetch_related("allocations__student_fee_component__fee_component")
        .first()
    )
    if payment is None:
        raise NotFound("Payment not found.")
    return _payment_to_dict(payment)


@router.post("/payments/{payment_id}/void", response=PaymentOut)
def void_payment(
    request: HttpRequest, payment_id: int, payload: VoidPaymentRequest
) -> dict:
    _require_admin(request)
    services.void_payment(
        school=_school(request),
        actor_id=_user(request).id,
        payment_id=payment_id,
        reason=payload.reason,
    )
    payment = (
        FeePayment.objects.select_related("student_fee__student", "received_by")
        .prefetch_related("allocations__student_fee_component__fee_component")
        .get(pk=payment_id)
    )
    return _payment_to_dict(payment)


# --- Dues + dashboard -------------------------------------------------------

@router.get("/fees/dues", response=DuesListOut)
def list_dues(
    request: HttpRequest,
    class_id: int | None = Query(default=None, alias="classId"),
    section_id: int | None = Query(default=None, alias="sectionId"),
    status: str | None = Query(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=50, alias="pageSize"),
) -> dict:
    school = _school(request)
    qs = services.dues_queryset(
        school=school, class_id=class_id, section_id=section_id, status=status
    ).prefetch_related("student__enrollments__section__class_obj")

    page_data = paginate(qs, page=page, page_size=page_size)
    rows = []
    total_outstanding = 0
    for sf in page_data["items"]:
        active = next(
            (e for e in sf.student.enrollments.all() if e.status == "active"), None
        )
        outstanding = max(0, sf.final_paise - sf.paid_paise)
        total_outstanding += outstanding
        rows.append({
            "student_fee_id": sf.id,
            "student_id": sf.student_id,
            "student_name": sf.student.full_name,
            "admission_number": sf.student.admission_number,
            "class_name": sf.fee_structure.class_obj.name,
            "section_name": active.section.name if active else None,
            "total_paise": sf.total_paise,
            "final_paise": sf.final_paise,
            "paid_paise": sf.paid_paise,
            "outstanding_paise": outstanding,
            "status": sf.status,
        })
    page_data["items"] = rows
    page_data["totals"] = {"outstanding_paise": total_outstanding}
    return page_data


@router.get("/fees/rollup", response=FeesRollupOut)
def fees_rollup(
    request: HttpRequest,
    academic_year_id: int | None = Query(default=None, alias="academicYearId"),
) -> dict:
    school = _school(request)
    sections = services.section_rollup(
        school=school, academic_year_id=academic_year_id
    )
    totals = {
        "expected_paise": sum(s["expected_paise"] for s in sections),
        "collected_paise": sum(s["collected_paise"] for s in sections),
        "outstanding_paise": sum(s["outstanding_paise"] for s in sections),
        "paid_count": sum(s["paid_count"] for s in sections),
        "partial_count": sum(s["partial_count"] for s in sections),
        "pending_count": sum(s["pending_count"] for s in sections),
        "overdue_count": sum(s["overdue_count"] for s in sections),
    }
    return {"sections": sections, "totals": totals}
