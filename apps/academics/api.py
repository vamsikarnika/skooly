"""Academics endpoints: classes (+ sections), subjects, teacher assignments."""

from __future__ import annotations

from django.db.models import Count, Q
from django.http import HttpRequest
from ninja import File, Form, Query, Router
from ninja.files import UploadedFile

from apps.academics import bulk_import as bulk
from apps.academics import services_write
from apps.academics.models import Class, Section, Subject, TeacherAssignment
from apps.academics.schemas import (
    ClassOut,
    SectionOut,
    SectionSubjectTeacherOut,
    SectionTimetableOut,
    SubjectOut,
)
from apps.academics.schemas_in import (
    ClassCreateRequest,
    ClassSubjectRequest,
    ClassUpdateRequest,
    SectionCreateRequest,
    SectionTimetableIn,
    SectionUpdateRequest,
    SubjectCreateRequest,
    SubjectUpdateRequest,
    TeacherAssignmentRequest,
)
from apps.accounts.auth import jwt_auth
from apps.accounts.models import Role
from apps.core.exceptions import Forbidden, NotFound
from apps.core.helpers import get_in_tenant
from apps.core.schemas import ActionResponse
from apps.people.schemas import BulkImportResponse

router = Router(tags=["academics"], auth=jwt_auth, by_alias=True)


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


def _section_to_dict(section) -> dict:  # type: ignore[no-untyped-def]
    active = getattr(section, "active_count", None)
    if active is None:
        active = section.enrollments.filter(status="active").count()
    teacher = section.class_teacher
    return {
        "id": section.id,
        "name": section.name,
        "class_id": section.class_obj_id,
        "class_teacher_id": teacher.id if teacher else None,
        "class_teacher_name": teacher.full_name if teacher else None,
        "room_number": section.room_number,
        "capacity": section.capacity,
        "active_student_count": active,
    }


# ----- Classes (with nested sections) ----------------------------------------

@router.get("/classes", response=list[ClassOut])
def list_classes(
    request: HttpRequest,
    academic_year_id: int | None = Query(default=None, alias="academicYearId"),
) -> list[dict]:
    school = _school(request)
    qs = (
        Class.objects.filter(school=school)
        .prefetch_related("sections__class_teacher")
        .annotate(
            student_count=Count(
                "sections__enrollments",
                filter=Q(sections__enrollments__status="active"),
                distinct=True,
            ),
        )
    )
    if academic_year_id:
        qs = qs.filter(academic_year_id=academic_year_id)
    out = []
    for cls in qs:
        sections = [_section_to_dict(s) for s in cls.sections.all()]
        out.append({
            "id": cls.id,
            "name": cls.name,
            "academic_year_id": cls.academic_year_id,
            "display_order": cls.display_order,
            "sections": sections,
            "student_count": cls.student_count,
        })
    return out


@router.post("/classes", response=ClassOut)
def create_class(request: HttpRequest, payload: ClassCreateRequest) -> dict:
    _require_admin(request)
    cls = services_write.create_class(
        school=_school(request),
        actor_id=_user(request).id,
        data=payload.model_dump(by_alias=False),
    )
    return {
        "id": cls.id, "name": cls.name, "academic_year_id": cls.academic_year_id,
        "display_order": cls.display_order, "sections": [], "student_count": 0,
    }


@router.post("/classes/bulk-import", response=BulkImportResponse)
def bulk_import_classes(
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

    response["imported"] = bulk.import_rows(school=school, rows=parsed.rows)
    return response


@router.patch("/classes/{class_id}", response=ClassOut)
def update_class(request: HttpRequest, class_id: int, payload: ClassUpdateRequest) -> dict:
    _require_admin(request)
    cls = services_write.update_class(
        school=_school(request),
        actor_id=_user(request).id,
        class_id=class_id,
        data=payload.model_dump(by_alias=False, exclude_unset=True),
    )
    return {
        "id": cls.id, "name": cls.name, "academic_year_id": cls.academic_year_id,
        "display_order": cls.display_order, "sections": [], "student_count": 0,
    }


@router.delete("/classes/{class_id}", response=ActionResponse)
def delete_class(request: HttpRequest, class_id: int) -> ActionResponse:
    _require_admin(request)
    services_write.delete_class(
        school=_school(request), actor_id=_user(request).id, class_id=class_id
    )
    return ActionResponse(success=True, message="Class deleted.")


# ----- Sections --------------------------------------------------------------

@router.get("/sections/{section_id}", response=SectionOut)
def get_section(request: HttpRequest, section_id: int):  # type: ignore[no-untyped-def]
    school = _school(request)
    section = (
        Section.objects.filter(school=school, id=section_id)
        .select_related("class_teacher", "class_obj")
        .first()
    )
    if section is None:
        raise NotFound("Section not found.")
    return _section_to_dict(section)


@router.post("/sections", response=SectionOut)
def create_section(request: HttpRequest, payload: SectionCreateRequest) -> dict:
    _require_admin(request)
    section = services_write.create_section(
        school=_school(request),
        actor_id=_user(request).id,
        data=payload.model_dump(by_alias=False),
    )
    return _section_to_dict(section)


@router.patch("/sections/{section_id}", response=SectionOut)
def update_section(
    request: HttpRequest, section_id: int, payload: SectionUpdateRequest
) -> dict:
    _require_admin(request)
    section = services_write.update_section(
        school=_school(request),
        actor_id=_user(request).id,
        section_id=section_id,
        data=payload.model_dump(by_alias=False, exclude_unset=True),
    )
    return _section_to_dict(section)


@router.delete("/sections/{section_id}", response=ActionResponse)
def delete_section(request: HttpRequest, section_id: int) -> ActionResponse:
    _require_admin(request)
    services_write.delete_section(
        school=_school(request), actor_id=_user(request).id, section_id=section_id
    )
    return ActionResponse(success=True, message="Section deleted.")


# ----- Section timetable -----------------------------------------------------

@router.get("/sections/{section_id}/timetable", response=SectionTimetableOut)
def get_section_timetable(request: HttpRequest, section_id: int) -> SectionTimetableOut:
    """The section's weekly timetable: period time-slots + filled day/period cells."""
    data = services_write.get_section_timetable(school=_school(request), section_id=section_id)
    return SectionTimetableOut(**data)


@router.put("/sections/{section_id}/timetable", response=SectionTimetableOut)
def save_section_timetable(
    request: HttpRequest, section_id: int, payload: SectionTimetableIn
) -> SectionTimetableOut:
    """Replace the section's weekly timetable. Each cell's teacher is resolved
    from the subject's assignment, so the teacher app's schedule is populated."""
    _require_admin(request)
    services_write.save_section_timetable(
        school=_school(request),
        actor_id=_user(request).id,
        section_id=section_id,
        data=payload.model_dump(by_alias=False),
    )
    data = services_write.get_section_timetable(school=_school(request), section_id=section_id)
    return SectionTimetableOut(**data)


# ----- Subjects --------------------------------------------------------------

@router.get("/subjects", response=list[SubjectOut])
def list_subjects(request: HttpRequest) -> list[SubjectOut]:
    school = _school(request)
    return [SubjectOut.from_orm(s) for s in Subject.objects.filter(school=school)]


@router.post("/subjects", response=SubjectOut)
def create_subject(request: HttpRequest, payload: SubjectCreateRequest) -> SubjectOut:
    _require_admin(request)
    subject = services_write.create_subject(
        school=_school(request),
        actor_id=_user(request).id,
        data=payload.model_dump(by_alias=False),
    )
    return SubjectOut.from_orm(subject)


@router.patch("/subjects/{subject_id}", response=SubjectOut)
def update_subject(
    request: HttpRequest, subject_id: int, payload: SubjectUpdateRequest
) -> SubjectOut:
    _require_admin(request)
    subject = services_write.update_subject(
        school=_school(request),
        actor_id=_user(request).id,
        subject_id=subject_id,
        data=payload.model_dump(by_alias=False, exclude_unset=True),
    )
    return SubjectOut.from_orm(subject)


@router.delete("/subjects/{subject_id}", response=ActionResponse)
def delete_subject(request: HttpRequest, subject_id: int) -> ActionResponse:
    _require_admin(request)
    services_write.delete_subject(
        school=_school(request), actor_id=_user(request).id, subject_id=subject_id
    )
    return ActionResponse(success=True, message="Subject deleted.")


# ----- Class subjects (which subjects a class teaches) -----------------------

@router.get("/classes/{class_id}/subjects", response=list[SubjectOut])
def list_class_subjects(request: HttpRequest, class_id: int) -> list[SubjectOut]:
    """Subjects mapped to this class. These are the rows the section page's
    'Subject teachers' picker assigns teachers to."""
    school = _school(request)
    cls = get_in_tenant(Class, school, pk=class_id)
    subjects = (
        Subject.objects.filter(school=school, class_mappings__class_obj=cls.id)
        .order_by("name")
        .distinct()
    )
    return [SubjectOut.from_orm(s) for s in subjects]


@router.post("/classes/{class_id}/subjects", response=ActionResponse)
def attach_class_subject(
    request: HttpRequest, class_id: int, payload: ClassSubjectRequest
) -> ActionResponse:
    _require_admin(request)
    mapping = services_write.attach_subject_to_class(
        school=_school(request),
        actor_id=_user(request).id,
        class_id=class_id,
        subject_id=payload.subject_id,
    )
    return ActionResponse(
        success=True, message="Subject added to class.", data={"id": mapping.id}
    )


@router.delete("/classes/{class_id}/subjects/{subject_id}", response=ActionResponse)
def detach_class_subject(
    request: HttpRequest, class_id: int, subject_id: int
) -> ActionResponse:
    _require_admin(request)
    services_write.detach_subject_from_class(
        school=_school(request),
        actor_id=_user(request).id,
        class_id=class_id,
        subject_id=subject_id,
    )
    return ActionResponse(success=True, message="Subject removed from class.")


# ----- Teacher assignments ---------------------------------------------------

@router.get(
    "/sections/{section_id}/teacher-assignments",
    response=list[SectionSubjectTeacherOut],
)
def list_section_teacher_assignments(
    request: HttpRequest, section_id: int
) -> list[SectionSubjectTeacherOut]:
    """Subjects taught at this section's class level, each with its current
    teacher assignment (if any). Drives the section's "Subject teachers" UI."""
    school = _school(request)
    section = get_in_tenant(Section, school, pk=section_id)
    subjects = (
        Subject.objects.filter(school=school, class_mappings__class_obj=section.class_obj_id)
        .order_by("name")
        .distinct()
    )
    assignments = {
        a.subject_id: a
        for a in TeacherAssignment.objects.filter(
            school=school, section=section
        ).select_related("teacher")
    }
    rows: list[SectionSubjectTeacherOut] = []
    for subject in subjects:
        assignment = assignments.get(subject.id)
        teacher = assignment.teacher if assignment else None
        rows.append(
            SectionSubjectTeacherOut(
                subject_id=subject.id,
                subject_name=subject.name,
                assignment_id=assignment.id if assignment else None,
                teacher_id=teacher.id if teacher else None,
                teacher_name=teacher.full_name if teacher else None,
            )
        )
    return rows


@router.post("/teacher-assignments", response=ActionResponse)
def create_teacher_assignment(
    request: HttpRequest, payload: TeacherAssignmentRequest
) -> ActionResponse:
    _require_admin(request)
    assignment = services_write.create_teacher_assignment(
        school=_school(request),
        actor_id=_user(request).id,
        data=payload.model_dump(by_alias=False),
    )
    return ActionResponse(
        success=True,
        message="Assignment created.",
        data={"id": assignment.id},
    )


@router.delete("/teacher-assignments/{assignment_id}", response=ActionResponse)
def delete_teacher_assignment(request: HttpRequest, assignment_id: int) -> ActionResponse:
    _require_admin(request)
    school = _school(request)
    get_in_tenant(TeacherAssignment, school, pk=assignment_id)
    services_write.delete_teacher_assignment(
        school=school, actor_id=_user(request).id, assignment_id=assignment_id
    )
    return ActionResponse(success=True, message="Assignment removed.")
