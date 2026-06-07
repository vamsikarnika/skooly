"""Parent app timetable endpoint — mounted on parent_api.

Resolves the child's current section and returns the weekly schedule
grouped by day. Lunch / short breaks are inferred client-side from the
gap between consecutive periods, so the API just returns periods.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from django.http import HttpRequest
from ninja import Router

from apps.academics.models import DayOfWeek, TimetablePeriod
from apps.accounts.parent_auth import get_parent_child, parent_jwt_auth
from apps.core.schemas import CamelSchema

router = Router(tags=["parent-timetable"], auth=parent_jwt_auth, by_alias=True)


class PeriodOut(CamelSchema):
    period: int
    start_time: str
    end_time: str
    subject: str
    teacher: str


class DayOut(CamelSchema):
    day: str  # "Mon" | "Tue" | "Wed" | "Thu" | "Fri" | "Sat"
    periods: list[PeriodOut]


class TimetableOut(CamelSchema):
    days: list[DayOut]


def _current_section(student: Any, school: Any) -> Any:
    year_id = school.current_academic_year_id if school else None
    qs = student.enrollments.filter(status="active").select_related("section")
    enroll = None
    if year_id is not None:
        enroll = qs.filter(academic_year_id=year_id).first()
    enroll = enroll or qs.first()
    return enroll.section if enroll else None


@router.get("/children/{child_id}/timetable", response=TimetableOut)
def get_timetable(request: HttpRequest, child_id: int) -> dict:
    student = get_parent_child(request, child_id)
    school = request.auth.school  # type: ignore[attr-defined]
    section = _current_section(student, school)
    if section is None:
        return {"days": []}

    rows = (
        TimetablePeriod.objects.filter(section=section)
        .select_related("subject", "teacher")
        .order_by("day_of_week", "period_number")
    )

    by_day: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_day[r.day_of_week].append(
            {
                "period": r.period_number,
                "start_time": r.start_time.strftime("%H:%M"),
                "end_time": r.end_time.strftime("%H:%M"),
                "subject": r.subject.name if r.subject else "",
                "teacher": r.teacher.full_name if r.teacher else "",
            }
        )

    return {
        "days": [
            {"day": DayOfWeek(day_value).label[:3], "periods": periods}
            for day_value, periods in sorted(by_day.items())
        ]
    }
