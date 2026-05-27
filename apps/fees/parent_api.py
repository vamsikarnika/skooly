"""Parent app fee-status endpoint — mounted on parent_api.

Read-only fee breakdown for a single linked child: applicable components with
paid/due, plus the non-voided payment history. All amounts are returned in
**whole rupees** (the parent app does not deal in paise).
"""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router

from apps.accounts.parent_auth import get_parent_child, parent_jwt_auth
from apps.core.schemas import CamelSchema
from apps.fees.models import StudentFee

router = Router(tags=["parent-fees"], auth=parent_jwt_auth, by_alias=True)

# Component-level fee status → the app's coarser paid|due|overdue.
_COMPONENT_STATUS = {
    "paid": "paid",
    "partial": "due",
    "pending": "due",
    "overdue": "overdue",
}


class FeeComponentOut(CamelSchema):
    id: int
    name: str
    paid: int
    due: int
    due_date: str
    status: str


class FeePaymentOut(CamelSchema):
    id: int
    date: str
    amount: int
    receipt_no: str
    components: list[str]


class FeeStatusOut(CamelSchema):
    academic_year: str
    components: list[FeeComponentOut]
    payments: list[FeePaymentOut]


@router.get("/children/{child_id}/fees", response=FeeStatusOut)
def fee_status(request: HttpRequest, child_id: int) -> dict:
    student = get_parent_child(request, child_id)
    school = request.auth.school  # type: ignore[attr-defined]
    year = school.current_academic_year if school else None
    label = year.label if year else ""

    qs = StudentFee.objects.filter(student=student)
    if year is not None:
        qs = qs.filter(academic_year=year)
    student_fee = (
        qs.select_related("academic_year")
        .prefetch_related(
            "components__fee_component",
            "payments__allocations__student_fee_component__fee_component",
        )
        .order_by("-id")
        .first()
    )
    if student_fee is None:
        return {"academic_year": label, "components": [], "payments": []}

    components = [
        {
            "id": c.id,
            "name": c.fee_component.name,
            "paid": c.paid_paise // 100,
            "due": max(c.applied_paise - c.paid_paise, 0) // 100,
            "due_date": c.fee_component.due_date.isoformat(),
            "status": _COMPONENT_STATUS.get(c.status, "due"),
        }
        for c in student_fee.components.all()
        if c.is_applicable
    ]

    payments = [
        {
            "id": p.id,
            "date": p.paid_on.isoformat(),
            "amount": p.total_paise // 100,
            "receipt_no": p.receipt_number,
            "components": [
                a.student_fee_component.fee_component.name for a in p.allocations.all()
            ],
        }
        for p in student_fee.payments.all()
        if not p.is_voided
    ]
    payments.sort(key=lambda x: x["date"], reverse=True)

    return {
        "academic_year": student_fee.academic_year.label,
        "components": components,
        "payments": payments,
    }
