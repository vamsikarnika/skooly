"""Academics read endpoints (classes + nested sections + subjects)."""

from __future__ import annotations

from django.db.models import Count, Q
from django.http import HttpRequest
from ninja import Query, Router

from apps.academics.models import Class, Subject
from apps.academics.schemas import ClassOut, SectionOut, SubjectOut
from apps.accounts.auth import jwt_auth

router = Router(tags=["academics"], auth=jwt_auth, by_alias=True)


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


@router.get("/classes", response=list[ClassOut])
def list_classes(
    request: HttpRequest,
    academic_year_id: int | None = Query(default=None, alias="academicYearId"),
) -> list[dict]:
    qs = Class.objects.prefetch_related("sections__class_teacher").annotate(
        student_count=Count(
            "sections__enrollments",
            filter=Q(sections__enrollments__status="active"),
            distinct=True,
        ),
    )
    if academic_year_id:
        qs = qs.filter(academic_year_id=academic_year_id)
    out = []
    for cls in qs:
        sections = []
        for section in cls.sections.all():
            sections.append(_section_to_dict(section))
        out.append({
            "id": cls.id,
            "name": cls.name,
            "academic_year_id": cls.academic_year_id,
            "display_order": cls.display_order,
            "sections": sections,
            "student_count": cls.student_count,
        })
    return out


@router.get("/sections/{section_id}", response=SectionOut)
def get_section(request: HttpRequest, section_id: int):  # type: ignore[no-untyped-def]
    from apps.academics.models import Section

    section = (
        Section.objects.select_related("class_teacher", "class_obj")
        .filter(id=section_id)
        .first()
    )
    if section is None:
        from apps.core.exceptions import NotFound

        raise NotFound("Section not found.")
    return _section_to_dict(section)


@router.get("/subjects", response=list[SubjectOut])
def list_subjects(request: HttpRequest) -> list[SubjectOut]:
    return [SubjectOut.from_orm(s) for s in Subject.objects.all()]
