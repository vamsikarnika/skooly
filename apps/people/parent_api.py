"""Parent app home-feed endpoint — mounted on parent_api.

Aggregates the most recent attendance, published marks, and overdue-fee signals
for a single linked child into one newest-first list for the home screen.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from ninja import Router

from apps.accounts.parent_auth import get_parent_child, parent_jwt_auth
from apps.attendance.models import Attendance
from apps.core.schemas import CamelSchema
from apps.exams.models import Test, TestMode, TestScore
from apps.fees.models import StudentFee

router = Router(tags=["parent-feed"], auth=parent_jwt_auth, by_alias=True)

_ATT_MESSAGE = {
    "present": "{name} was present",
    "absent": "{name} was absent",
    "late": "{name} came late",
    "half_day": "{name} attended half day",
}


class FeedItemOut(CamelSchema):
    id: str
    type: str
    message: str
    detail: str | None = None
    date: str
    link_to: str | None = None


class FeedOut(CamelSchema):
    items: list[FeedItemOut]


def _section(student: Any, school: Any) -> Any:
    year_id = school.current_academic_year_id if school else None
    qs = student.enrollments.filter(status="active").select_related("section")
    enroll = (qs.filter(academic_year_id=year_id).first() if year_id else None) or qs.first()
    return enroll.section if enroll else None


@router.get("/children/{child_id}/feed", response=FeedOut)
def feed(request: HttpRequest, child_id: int) -> dict:
    student = get_parent_child(request, child_id)
    school = request.auth.school  # type: ignore[attr-defined]
    name = student.first_name
    items: list[dict] = []

    # Attendance — only the latest recorded day (current status; avoids a noisy
    # run of "was present / was absent" entries piling up in the feed).
    for a in Attendance.objects.filter(student=student).order_by("-date")[:1]:
        items.append(
            {
                "id": f"att-{a.id}",
                "type": "attendance",
                "message": _ATT_MESSAGE.get(a.status, "{name} attendance updated").format(
                    name=name
                ),
                "detail": a.notes or None,
                "date": a.date.isoformat(),
                "link_to": "/attendance",
            }
        )

    # Marks — most recent published offline tests where the child has a score.
    section = _section(student, school)
    if section is not None:
        scores = (
            TestScore.objects.filter(
                student=student,
                test__section=section,
                test__mode=TestMode.OFFLINE,
                test__published_at__isnull=False,
            )
            .select_related("test", "test__subject")
            .order_by("-test__test_date")[:3]
        )
        for s in scores:
            test: Test = s.test
            if s.is_absent or s.marks_obtained is None:
                continue
            # Test names sometimes already lead with the subject — don't repeat it.
            subject = test.subject.name
            title = test.name if test.name.lower().startswith(subject.lower()) else f"{subject} {test.name}"
            items.append(
                {
                    "id": f"mark-{s.id}",
                    "type": "marks",
                    "message": f"{title} — {round(float(s.marks_obtained))} / {test.max_marks or 0}",
                    "detail": None,
                    "date": test.test_date.isoformat(),
                    "link_to": "/marks",
                }
            )

    # Fees — overdue applicable components.
    student_fee = (
        StudentFee.objects.filter(student=student)
        .prefetch_related("components__fee_component")
        .order_by("-id")
        .first()
    )
    if student_fee is not None:
        for c in student_fee.components.all():
            if not c.is_applicable or c.status != "overdue":
                continue
            due = max(c.applied_paise - c.paid_paise, 0) // 100
            items.append(
                {
                    "id": f"fee-{c.id}",
                    "type": "fee",
                    "message": f"Fee reminder: {c.fee_component.name} ₹{due:,} overdue",
                    "detail": f"Due date was {c.fee_component.due_date.strftime('%d %b')}",
                    "date": c.fee_component.due_date.isoformat(),
                    "link_to": "/fees",
                }
            )

    items.sort(key=lambda x: x["date"], reverse=True)
    return {"items": items[:10]}
