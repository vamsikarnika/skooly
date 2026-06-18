"""Student & Teacher endpoints (Module 2)."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from ninja import File, Form, Query, Router
from ninja.files import UploadedFile

from apps.accounts.auth import jwt_auth
from apps.accounts.models import Role
from apps.core.exceptions import Forbidden, NotFound
from apps.core.helpers import get_in_tenant
from apps.core.pagination import paginate
from apps.core.schemas import ActionResponse
from apps.core.storage import save_uploaded_image
from apps.people import bulk_import as bulk
from apps.people import export, services, services_write
from apps.people import teacher_bulk_import as teacher_bulk
from apps.people.models import Student, Teacher
from apps.people.schemas import (
    BulkImportResponse,
    StudentListOut,
    StudentOut,
    TeacherListOut,
    TeacherOut,
    TempPasswordOut,
)
from apps.people.schemas_in import (
    StudentCreateRequest,
    StudentTransferRequest,
    StudentUpdateRequest,
    TeacherCreateRequest,
    TeacherUpdateRequest,
)

router = Router(tags=["people"], auth=jwt_auth, by_alias=True)


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


# ----- Students --------------------------------------------------------------

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
    qs = services.list_students(section_id=section_id, class_id=class_id, status=status, search=search)
    payload = paginate(qs, page=page, page_size=page_size)
    payload["items"] = [services.student_to_dict(s) for s in payload["items"]]
    return payload


@router.get("/students/export")
def export_students(
    request: HttpRequest,
    section_id: int | None = Query(default=None, alias="sectionId"),
    class_id: int | None = Query(default=None, alias="classId"),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None, alias="q"),
) -> HttpResponse:
    qs = services.list_students(section_id=section_id, class_id=class_id, status=status, search=search)
    data = export.export_students_xlsx(qs)
    resp = HttpResponse(
        data,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = 'attachment; filename="students.xlsx"'
    return resp


@router.post("/students/bulk-import", response=BulkImportResponse)
def bulk_import_students(
    request: HttpRequest,
    file: UploadedFile = File(...),
    dry_run: bool = Form(default=True, alias="dryRun"),
) -> dict:
    _require_admin(request)
    school = _school(request)
    file_bytes = file.read()
    parsed = bulk.parse_workbook(file_bytes=file_bytes, school=school)

    response = {
        "ok": parsed.ok,
        "dry_run": dry_run,
        "row_count": len(parsed.rows) + len(parsed.errors),
        "valid_rows": len(parsed.rows),
        "error_count": len(parsed.errors),
        "errors": [
            {"row": e.row, "field": e.field, "message": e.message} for e in parsed.errors
        ],
        "imported": 0,
    }

    if dry_run or not parsed.ok:
        return response

    imported = bulk.import_rows(school=school, rows=parsed.rows)
    response["imported"] = imported
    return response


@router.get("/students/{student_id}", response=StudentOut)
def get_student(request: HttpRequest, student_id: int) -> dict:
    school = _school(request)
    student = (
        Student.objects.filter(school=school, id=student_id)
        .prefetch_related("enrollments__section__class_obj")
        .first()
    )
    if student is None:
        raise NotFound("Student not found.")
    return services.student_to_dict(student)


@router.post("/students", response=StudentOut)
def create_student(request: HttpRequest, payload: StudentCreateRequest) -> dict:
    _require_admin(request)
    student = services_write.create_student(
        school=_school(request),
        actor_id=_user(request).id,
        data=payload.model_dump(by_alias=False),
    )
    return services.student_to_dict(student)


@router.patch("/students/{student_id}", response=StudentOut)
def update_student(
    request: HttpRequest, student_id: int, payload: StudentUpdateRequest
) -> dict:
    _require_admin(request)
    student = services_write.update_student(
        school=_school(request),
        actor_id=_user(request).id,
        student_id=student_id,
        data=payload.model_dump(by_alias=False, exclude_unset=True),
    )
    student = Student.objects.prefetch_related("enrollments__section__class_obj").get(id=student.id)
    return services.student_to_dict(student)


@router.delete("/students/{student_id}", response=ActionResponse)
def delete_student(request: HttpRequest, student_id: int) -> ActionResponse:
    _require_admin(request)
    services_write.soft_delete_student(
        school=_school(request),
        actor_id=_user(request).id,
        student_id=student_id,
    )
    return ActionResponse(success=True, message="Student withdrawn.")


@router.post("/students/{student_id}/transfer", response=StudentOut)
def transfer_student(
    request: HttpRequest, student_id: int, payload: StudentTransferRequest
) -> dict:
    _require_admin(request)
    services_write.transfer_student(
        school=_school(request),
        actor_id=_user(request).id,
        student_id=student_id,
        target_section_id=payload.section_id,
        roll_number=payload.roll_number,
        effective_date=payload.effective_date,
    )
    student = Student.objects.prefetch_related("enrollments__section__class_obj").get(id=student_id)
    return services.student_to_dict(student)


@router.post("/students/{student_id}/photo", response=StudentOut)
def upload_student_photo(
    request: HttpRequest,
    student_id: int,
    file: UploadedFile = File(...),
) -> dict:
    _require_admin(request)
    school = _school(request)
    student = get_in_tenant(Student, school, pk=student_id)
    url = save_uploaded_image(
        file=file.file,
        content_type=file.content_type or "application/octet-stream",
        size=file.size,
        school_id=school.id,
        kind="student-photo",
        owner_id=student.id,
    )
    student.photo_url = url
    student.save(update_fields=["photo_url", "updated_at"])
    student = Student.objects.prefetch_related("enrollments__section__class_obj").get(id=student.id)
    return services.student_to_dict(student)


# ----- Teachers --------------------------------------------------------------

@router.post("/teachers/bulk-import", response=BulkImportResponse)
def bulk_import_teachers(
    request: HttpRequest,
    file: UploadedFile = File(...),
    dry_run: bool = Form(default=True, alias="dryRun"),
) -> dict:
    _require_admin(request)
    school = _school(request)
    file_bytes = file.read()
    parsed = teacher_bulk.parse_workbook(file_bytes=file_bytes, school=school)

    response = {
        "ok": parsed.ok,
        "dry_run": dry_run,
        "row_count": len(parsed.rows) + len(parsed.errors),
        "valid_rows": len(parsed.rows),
        "error_count": len(parsed.errors),
        "errors": [
            {"row": e.row, "field": e.field, "message": e.message} for e in parsed.errors
        ],
        "imported": 0,
    }

    if dry_run or not parsed.ok:
        return response

    response["imported"] = teacher_bulk.import_rows(school=school, rows=parsed.rows)
    return response


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
    school = _school(request)
    teacher = Teacher.objects.filter(school=school, id=teacher_id).first()
    if teacher is None:
        raise NotFound("Teacher not found.")
    return TeacherOut.from_orm(teacher)


@router.post("/teachers", response=TeacherOut)
def create_teacher(request: HttpRequest, payload: TeacherCreateRequest) -> TeacherOut:
    _require_admin(request)
    teacher = services_write.create_teacher(
        school=_school(request),
        actor_id=_user(request).id,
        data=payload.model_dump(by_alias=False),
    )
    return TeacherOut.from_orm(teacher)


@router.patch("/teachers/{teacher_id}", response=TeacherOut)
def update_teacher(
    request: HttpRequest, teacher_id: int, payload: TeacherUpdateRequest
) -> TeacherOut:
    _require_admin(request)
    teacher = services_write.update_teacher(
        school=_school(request),
        actor_id=_user(request).id,
        teacher_id=teacher_id,
        data=payload.model_dump(by_alias=False, exclude_unset=True),
    )
    return TeacherOut.from_orm(teacher)


@router.delete("/teachers/{teacher_id}", response=ActionResponse)
def delete_teacher(request: HttpRequest, teacher_id: int) -> ActionResponse:
    _require_admin(request)
    services_write.soft_delete_teacher(
        school=_school(request),
        actor_id=_user(request).id,
        teacher_id=teacher_id,
    )
    return ActionResponse(success=True, message="Teacher marked inactive.")


@router.post("/teachers/{teacher_id}/reset-password", response=TempPasswordOut)
def reset_teacher_password(request: HttpRequest, teacher_id: int) -> TempPasswordOut:
    """Generate a first-login password for the teacher. Admin-only; the
    plaintext is returned once for the admin to hand over and is never stored.

    Temporary feature — disabled (404) when TEACHER_PASSWORD_PROVISIONING is off,
    which is how we retire it once OTP-based onboarding ships."""
    if not settings.TEACHER_PASSWORD_PROVISIONING:
        raise NotFound("Teacher password provisioning is disabled.")
    _require_admin(request)
    password = services_write.reset_teacher_login_password(
        school=_school(request),
        actor_id=_user(request).id,
        teacher_id=teacher_id,
    )
    return TempPasswordOut(password=password)


@router.post("/teachers/{teacher_id}/photo", response=TeacherOut)
def upload_teacher_photo(
    request: HttpRequest,
    teacher_id: int,
    file: UploadedFile = File(...),
) -> TeacherOut:
    _require_admin(request)
    school = _school(request)
    teacher = get_in_tenant(Teacher, school, pk=teacher_id)
    url = save_uploaded_image(
        file=file.file,
        content_type=file.content_type or "application/octet-stream",
        size=file.size,
        school_id=school.id,
        kind="teacher-photo",
        owner_id=teacher.id,
    )
    teacher.photo_url = url
    teacher.save(update_fields=["photo_url", "updated_at"])
    return TeacherOut.from_orm(teacher)
