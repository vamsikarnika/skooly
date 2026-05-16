"""Student & Teacher read endpoints (Module 2 lite)."""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Query, Router

from apps.accounts.auth import jwt_auth
from apps.core.exceptions import NotFound
from apps.core.pagination import paginate
from apps.people import services
from apps.people.models import Student, Teacher
from apps.people.schemas import StudentListOut, StudentOut, TeacherListOut, TeacherOut

router = Router(tags=["people"], auth=jwt_auth, by_alias=True)


@router.get("/students", response=StudentListOut)
def list_students(
    request: HttpRequest,
    section_id: int | None = Query(default=None, alias="sectionId"),
    class_id: int | None = Query(default=None, alias="classId"),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None, alias="q"),
    page: int = Query(default=1),
    page_size: int = Query(default=50, alias="pageSize"),
) -> dict:
    qs = services.list_students(
        section_id=section_id, class_id=class_id, status=status, search=search
    )
    payload = paginate(qs, page=page, page_size=page_size)
    payload["items"] = [services.student_to_dict(s) for s in payload["items"]]
    return payload


@router.get("/students/{student_id}", response=StudentOut)
def get_student(request: HttpRequest, student_id: int) -> dict:
    student = (
        Student.objects.prefetch_related("enrollments__section__class_obj")
        .filter(id=student_id)
        .first()
    )
    if student is None:
        raise NotFound("Student not found.")
    return services.student_to_dict(student)


@router.get("/teachers", response=TeacherListOut)
def list_teachers(
    request: HttpRequest,
    status: str | None = Query(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=50, alias="pageSize"),
) -> dict:
    qs = services.list_teachers(status=status)
    return paginate(qs, page=page, page_size=page_size)


@router.get("/teachers/{teacher_id}", response=TeacherOut)
def get_teacher(request: HttpRequest, teacher_id: int) -> TeacherOut:
    teacher = Teacher.objects.filter(id=teacher_id).first()
    if teacher is None:
        raise NotFound("Teacher not found.")
    return TeacherOut.from_orm(teacher)
