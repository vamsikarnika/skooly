"""Teacher app single-student endpoint — mounted on teacher_api."""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router

from apps.accounts.teacher_auth import get_teacher, teacher_jwt_auth
from apps.people import teacher_services
from apps.people.teacher_schemas import TeacherStudentDetailOut

router = Router(tags=["teacher-students"], auth=teacher_jwt_auth, by_alias=True)


@router.get("/students/{student_id}", response=TeacherStudentDetailOut)
def get_student(request: HttpRequest, student_id: int) -> dict:
    school = request.auth.school  # type: ignore[attr-defined]
    return teacher_services.student_detail(
        teacher=get_teacher(request),
        student_id=student_id,
        academic_year_id=school.current_academic_year_id if school else None,
    )
