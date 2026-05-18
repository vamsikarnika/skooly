"""Read-only attendance endpoints. POST/mark flows live in the teacher app
build, not in Module 3."""

from __future__ import annotations

from datetime import date as date_type
from datetime import timedelta

from django.http import HttpRequest
from ninja import Query, Router

from apps.academics.models import Section
from apps.accounts.auth import jwt_auth
from apps.attendance import services
from apps.attendance.schemas import (
    SectionAttendanceOut,
    SectionsDailyRollupOut,
    SectionSummaryOut,
    StudentAttendanceHistoryOut,
)
from apps.core.exceptions import NotFound
from apps.core.helpers import get_in_tenant
from apps.people.models import Student

router = Router(tags=["attendance"], auth=jwt_auth, by_alias=True)


def _school(request: HttpRequest):  # type: ignore[no-untyped-def]
    school = request.auth.school  # type: ignore[attr-defined]
    if school is None:
        raise NotFound("Current user has no school.")
    return school


@router.get("/attendance/sections", response=SectionsDailyRollupOut)
def attendance_sections_for_date(
    request: HttpRequest,
    day: date_type | None = Query(default=None, alias="date"),
) -> dict:
    """One-shot daily roll-up for every section. Used by the attendance
    dashboard so we don't fan out N per-section requests."""
    school = _school(request)
    return services.all_sections_daily_rollup(
        school=school, day=day or date_type.today()
    )


@router.get("/sections/{section_id}/attendance", response=SectionAttendanceOut)
def section_attendance_for_date(
    request: HttpRequest,
    section_id: int,
    day: date_type | None = Query(default=None, alias="date"),
) -> dict:
    school = _school(request)
    section = get_in_tenant(
        Section.objects.select_related("class_obj"), school, pk=section_id
    )
    return services.section_attendance_for_date(
        school=school, section=section, day=day or date_type.today()
    )


@router.get("/sections/{section_id}/attendance/summary", response=SectionSummaryOut)
def section_attendance_summary(
    request: HttpRequest,
    section_id: int,
    from_date: date_type | None = Query(default=None, alias="from"),
    to_date: date_type | None = Query(default=None, alias="to"),
) -> dict:
    school = _school(request)
    section = get_in_tenant(
        Section.objects.select_related("class_obj"), school, pk=section_id
    )
    fd, td = services.default_window()
    return services.section_summary(
        school=school,
        section=section,
        from_date=from_date or fd,
        to_date=to_date or td,
    )


@router.get(
    "/students/{student_id}/attendance",
    response=StudentAttendanceHistoryOut,
)
def student_attendance_history(
    request: HttpRequest,
    student_id: int,
    from_date: date_type | None = Query(default=None, alias="from"),
    to_date: date_type | None = Query(default=None, alias="to"),
) -> dict:
    school = _school(request)
    student = get_in_tenant(Student, school, pk=student_id)
    fd = from_date or (date_type.today() - timedelta(days=60))
    td = to_date or date_type.today()
    return services.student_attendance_history(
        school=school, student=student, from_date=fd, to_date=td
    )
