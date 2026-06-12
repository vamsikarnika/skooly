"""Teacher app classes & roster endpoints — mounted on teacher_api."""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router

from apps.academics import teacher_services
from apps.academics.teacher_schemas import (
    ClassStudentOut,
    TeacherClassOut,
    TeacherPeriodOut,
    TeacherTimetableDayOut,
)
from apps.accounts.teacher_auth import get_teacher, teacher_jwt_auth

router = Router(tags=["teacher-classes"], auth=teacher_jwt_auth, by_alias=True)


def _academic_year_id(request: HttpRequest) -> int | None:
    school = request.auth.school  # type: ignore[attr-defined]
    return school.current_academic_year_id if school else None


@router.get("/classes", response=list[TeacherClassOut])
def list_classes(request: HttpRequest) -> list[dict]:
    return teacher_services.list_teacher_classes(
        teacher=get_teacher(request), academic_year_id=_academic_year_id(request)
    )


@router.get("/classes/{class_id}/students", response=list[ClassStudentOut])
def list_class_students(request: HttpRequest, class_id: int) -> list[dict]:
    return teacher_services.list_class_students(
        teacher=get_teacher(request),
        section_id=class_id,
        academic_year_id=_academic_year_id(request),
    )


@router.get("/timetable/today", response=list[TeacherPeriodOut])
def timetable_today(request: HttpRequest) -> list[dict]:
    return teacher_services.teacher_timetable_today(teacher=get_teacher(request))


@router.get("/timetable", response=list[TeacherTimetableDayOut])
def timetable_week(request: HttpRequest) -> list[dict]:
    return teacher_services.teacher_timetable_week(teacher=get_teacher(request))
