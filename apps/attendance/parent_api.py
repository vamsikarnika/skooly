"""Parent app attendance endpoints — mounted on parent_api.

Read-only calendar + yearly trend for a single linked child.
"""

from __future__ import annotations

import calendar
from collections import defaultdict

from django.http import HttpRequest
from ninja import Query, Router

from apps.accounts.parent_auth import get_parent_child, parent_jwt_auth
from apps.attendance.models import Attendance
from apps.core.schemas import CamelSchema

router = Router(tags=["parent-attendance"], auth=parent_jwt_auth, by_alias=True)

# Backend stores half_day; the app's calendar expects the hyphenated form.
_STATUS_OUT = {
    "present": "present",
    "absent": "absent",
    "late": "late",
    "half_day": "half-day",
}
_PRESENT_LIKE = {"present", "late", "half_day"}


class AttendanceDayOut(CamelSchema):
    date: str
    status: str
    note: str | None = None


class MonthlyAttendanceOut(CamelSchema):
    year: int
    month: int
    days: list[AttendanceDayOut]


class YearMonthOut(CamelSchema):
    month: str
    short_month: str
    present: int
    school_days: int
    pct: int


class YearlyAttendanceOut(CamelSchema):
    academic_year: str
    months: list[YearMonthOut]


@router.get("/children/{child_id}/attendance", response=MonthlyAttendanceOut)
def monthly_attendance(
    request: HttpRequest,
    child_id: int,
    year: int = Query(...),
    month: int = Query(...),
) -> dict:
    student = get_parent_child(request, child_id)
    rows = Attendance.objects.filter(
        student=student, date__year=year, date__month=month
    ).order_by("date")
    days = [
        {
            "date": r.date.isoformat(),
            "status": _STATUS_OUT.get(r.status, r.status),
            "note": r.notes or None,
        }
        for r in rows
    ]
    return {"year": year, "month": month, "days": days}


@router.get("/children/{child_id}/attendance/yearly", response=YearlyAttendanceOut)
def yearly_attendance(
    request: HttpRequest,
    child_id: int,
    academic_year: str = Query(default=None),  # type: ignore[assignment]
) -> dict:
    student = get_parent_child(request, child_id)
    school = request.auth.school  # type: ignore[attr-defined]
    year = school.current_academic_year if school else None
    label = year.label if year else ""

    rows = Attendance.objects.filter(student=student)
    if year is not None:
        rows = rows.filter(date__gte=year.start_date, date__lte=year.end_date)

    buckets: dict[tuple[int, int], dict[str, int]] = defaultdict(
        lambda: {"present": 0, "school": 0}
    )
    for r in rows.only("date", "status"):
        key = (r.date.year, r.date.month)
        buckets[key]["school"] += 1
        if r.status in _PRESENT_LIKE:
            buckets[key]["present"] += 1

    months = []
    for y, m in sorted(buckets.keys()):
        b = buckets[(y, m)]
        pct = round(b["present"] / b["school"] * 100) if b["school"] else 0
        months.append(
            {
                "month": calendar.month_name[m],
                "short_month": calendar.month_abbr[m],
                "present": b["present"],
                "school_days": b["school"],
                "pct": pct,
            }
        )
    return {"academic_year": label, "months": months}
