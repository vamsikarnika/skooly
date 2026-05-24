"""Teacher attendance endpoints — mounted on teacher_api."""

from __future__ import annotations

from datetime import date

from django.http import HttpRequest
from ninja import Query, Router

from apps.accounts.teacher_auth import get_teacher, teacher_jwt_auth
from apps.attendance import teacher_services
from apps.attendance.teacher_schemas import (
    AttendanceRecordOut,
    AttendanceSummaryOut,
    BulkAttendanceIn,
    BulkAttendanceSavedOut,
)
from apps.core.helpers import today_local

router = Router(tags=["teacher-attendance"], auth=teacher_jwt_auth, by_alias=True)


@router.get("/attendance/summary", response=list[AttendanceSummaryOut])
def get_summary(request: HttpRequest, date: date = Query(default=None)) -> list[dict]:  # type: ignore[assignment]
    school = request.auth.school  # type: ignore[attr-defined]
    on_date = date or today_local()
    return teacher_services.attendance_summary(
        teacher=get_teacher(request),
        academic_year_id=school.current_academic_year_id if school else None,
        on_date=on_date,
    )


@router.get("/attendance/{section_id}", response=list[AttendanceRecordOut])
def get_attendance(request: HttpRequest, section_id: int, date: date = Query(default=None)) -> list[dict]:  # type: ignore[assignment]
    school = request.auth.school  # type: ignore[attr-defined]
    on_date = date or today_local()
    return teacher_services.get_attendance(
        teacher=get_teacher(request),
        section_id=section_id,
        academic_year_id=school.current_academic_year_id if school else None,
        on_date=on_date,
    )


@router.post("/attendance/{section_id}", response=BulkAttendanceSavedOut)
def save_attendance(request: HttpRequest, section_id: int, payload: BulkAttendanceIn) -> dict:
    school = request.auth.school  # type: ignore[attr-defined]
    saved = teacher_services.save_attendance(
        teacher=get_teacher(request),
        section_id=section_id,
        academic_year_id=school.current_academic_year_id if school else None,
        on_date=payload.date,
        records=[r.model_dump(by_alias=False) for r in payload.records],
    )
    return {"saved": saved}
