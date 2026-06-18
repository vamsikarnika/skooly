"""Write services for academics."""

from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.academics.models import (
    Class,
    Section,
    StudentEnrollment,
    Subject,
    SubjectClassMapping,
    TeacherAssignment,
)
from apps.core.audit import log_action
from apps.core.exceptions import Conflict, NotFound, ValidationFailed
from apps.core.helpers import get_in_tenant
from apps.people.models import Teacher
from apps.schools.models import AcademicYear, School

# ----- Classes ---------------------------------------------------------------

@transaction.atomic
def create_class(*, school: School, actor_id: int, data: dict[str, Any]) -> Class:
    year = get_in_tenant(AcademicYear, school, pk=data["academic_year_id"])
    if Class.objects.filter(school=school, academic_year=year, name=data["name"]).exists():
        raise Conflict("A class with that name already exists for this academic year.")
    cls = Class.objects.create(
        school=school,
        academic_year=year,
        name=data["name"],
        display_order=data.get("display_order", 0),
    )
    log_action(school_id=school.id, user_id=actor_id, action="class.create",
               model_name="Class", object_id=cls.id)
    return cls


@transaction.atomic
def update_class(*, school: School, actor_id: int, class_id: int, data: dict[str, Any]) -> Class:
    cls = get_in_tenant(Class, school, pk=class_id)
    changed = []
    for f in ("name", "display_order"):
        if data.get(f) is not None:
            setattr(cls, f, data[f])
            changed.append(f)
    if changed:
        cls.save(update_fields=[*changed, "updated_at"])
    log_action(school_id=school.id, user_id=actor_id, action="class.update",
               model_name="Class", object_id=cls.id, changes={"fields": changed})
    return cls


@transaction.atomic
def delete_class(*, school: School, actor_id: int, class_id: int) -> None:
    cls = get_in_tenant(Class, school, pk=class_id)
    if cls.sections.filter(deleted_at__isnull=True).exists():
        raise Conflict("Cannot delete a class that still has sections. Delete sections first.")
    cls.soft_delete()
    log_action(school_id=school.id, user_id=actor_id, action="class.delete",
               model_name="Class", object_id=cls.id)


# ----- Sections --------------------------------------------------------------

@transaction.atomic
def create_section(*, school: School, actor_id: int, data: dict[str, Any]) -> Section:
    cls = get_in_tenant(Class, school, pk=data["class_id"])
    if Section.objects.filter(school=school, class_obj=cls, name=data["name"]).exists():
        raise Conflict("A section with that name already exists for this class.")
    class_teacher = None
    if data.get("class_teacher_id") is not None:
        class_teacher = get_in_tenant(Teacher, school, pk=data["class_teacher_id"])
    section = Section.objects.create(
        school=school,
        class_obj=cls,
        name=data["name"],
        class_teacher=class_teacher,
        room_number=data.get("room_number", ""),
        capacity=data.get("capacity", 40),
    )
    log_action(school_id=school.id, user_id=actor_id, action="section.create",
               model_name="Section", object_id=section.id)
    return section


@transaction.atomic
def update_section(*, school: School, actor_id: int, section_id: int, data: dict[str, Any]) -> Section:
    section = get_in_tenant(Section, school, pk=section_id)
    if "class_teacher_id" in data:
        if data["class_teacher_id"] is None:
            section.class_teacher = None
        else:
            section.class_teacher = get_in_tenant(Teacher, school, pk=data["class_teacher_id"])
    changed = ["class_teacher"] if "class_teacher_id" in data else []
    for f in ("name", "room_number", "capacity"):
        if data.get(f) is not None:
            setattr(section, f, data[f])
            changed.append(f)
    if changed:
        section.save(update_fields=[*changed, "updated_at"])
    log_action(school_id=school.id, user_id=actor_id, action="section.update",
               model_name="Section", object_id=section.id, changes={"fields": changed})
    return section


@transaction.atomic
def delete_section(*, school: School, actor_id: int, section_id: int) -> None:
    section = get_in_tenant(Section, school, pk=section_id)
    if StudentEnrollment.objects.filter(
        school=school, section=section, status="active"
    ).exists():
        raise Conflict(
            "Cannot delete a section that still has active enrollments. "
            "Transfer or withdraw the students first."
        )
    section.soft_delete()
    log_action(school_id=school.id, user_id=actor_id, action="section.delete",
               model_name="Section", object_id=section.id)


# ----- Subjects --------------------------------------------------------------

@transaction.atomic
def create_subject(*, school: School, actor_id: int, data: dict[str, Any]) -> Subject:
    if Subject.objects.filter(school=school, name=data["name"]).exists():
        raise Conflict("A subject with that name already exists.")
    subject = Subject.objects.create(school=school, name=data["name"], code=data.get("code", ""))
    log_action(school_id=school.id, user_id=actor_id, action="subject.create",
               model_name="Subject", object_id=subject.id)
    return subject


@transaction.atomic
def update_subject(*, school: School, actor_id: int, subject_id: int, data: dict[str, Any]) -> Subject:
    subject = get_in_tenant(Subject, school, pk=subject_id)
    changed = []
    for f in ("name", "code"):
        if data.get(f) is not None:
            setattr(subject, f, data[f])
            changed.append(f)
    if changed:
        subject.save(update_fields=[*changed, "updated_at"])
    log_action(school_id=school.id, user_id=actor_id, action="subject.update",
               model_name="Subject", object_id=subject.id, changes={"fields": changed})
    return subject


@transaction.atomic
def delete_subject(*, school: School, actor_id: int, subject_id: int) -> None:
    subject = get_in_tenant(Subject, school, pk=subject_id)
    subject.soft_delete()
    log_action(school_id=school.id, user_id=actor_id, action="subject.delete",
               model_name="Subject", object_id=subject.id)


# ----- Class subjects (subject <-> class mappings) ---------------------------

@transaction.atomic
def attach_subject_to_class(
    *, school: School, actor_id: int, class_id: int, subject_id: int
) -> SubjectClassMapping:
    cls = get_in_tenant(Class, school, pk=class_id)
    subject = get_in_tenant(Subject, school, pk=subject_id)
    mapping, created = SubjectClassMapping.objects.get_or_create(
        school=school, class_obj=cls, subject=subject
    )
    if not created:
        raise Conflict("That subject is already assigned to this class.")
    log_action(school_id=school.id, user_id=actor_id, action="subject_class_mapping.create",
               model_name="SubjectClassMapping", object_id=mapping.id)
    return mapping


@transaction.atomic
def detach_subject_from_class(
    *, school: School, actor_id: int, class_id: int, subject_id: int
) -> None:
    cls = get_in_tenant(Class, school, pk=class_id)
    mapping = SubjectClassMapping.objects.filter(
        school=school, class_obj=cls, subject_id=subject_id
    ).first()
    if mapping is None:
        raise NotFound("That subject is not assigned to this class.")
    mapping_id = mapping.id
    # Hard delete: the mapping is a pure join row with no history worth keeping,
    # and a soft-deleted row would block re-attaching via the (subject, class)
    # unique constraint.
    mapping.delete()
    log_action(school_id=school.id, user_id=actor_id, action="subject_class_mapping.delete",
               model_name="SubjectClassMapping", object_id=mapping_id)


# ----- Teacher assignments ---------------------------------------------------

@transaction.atomic
def create_teacher_assignment(
    *, school: School, actor_id: int, data: dict[str, Any]
) -> TeacherAssignment:
    teacher = get_in_tenant(Teacher, school, pk=data["teacher_id"])
    subject = get_in_tenant(Subject, school, pk=data["subject_id"])
    section = get_in_tenant(Section, school, pk=data["section_id"])
    year = section.class_obj.academic_year

    existing = TeacherAssignment.objects.filter(
        school=school, teacher=teacher, subject=subject, section=section, academic_year=year
    ).first()
    if existing is not None:
        raise Conflict("That assignment already exists.")

    if section.school_id != school.id or subject.school_id != school.id:
        raise ValidationFailed("All references must belong to the same school.")

    assignment = TeacherAssignment.objects.create(
        school=school, teacher=teacher, subject=subject, section=section, academic_year=year
    )
    log_action(school_id=school.id, user_id=actor_id, action="teacher_assignment.create",
               model_name="TeacherAssignment", object_id=assignment.id)
    return assignment


@transaction.atomic
def delete_teacher_assignment(*, school: School, actor_id: int, assignment_id: int) -> None:
    assignment = get_in_tenant(TeacherAssignment, school, pk=assignment_id)
    assignment.soft_delete()
    log_action(school_id=school.id, user_id=actor_id, action="teacher_assignment.delete",
               model_name="TeacherAssignment", object_id=assignment.id)
