"""Read logic for the teacher app's classes & roster.

A teacher's "classes" are their TeacherAssignment rows for the school's current
academic year — one card per (section, subject). classId is the section PK;
all queries are school-scoped by the TenantManager and additionally gated on
the teacher actually being assigned to the section.
"""

from __future__ import annotations

from typing import Any

from apps.academics.models import Section, StudentEnrollment, TeacherAssignment
from apps.attendance.models import Attendance
from apps.core.exceptions import NotFound
from apps.core.helpers import gender_code, hhmm_local, roll_to_int, today_local


def list_teacher_classes(*, teacher: Any, academic_year_id: int | None) -> list[dict]:
    today = today_local()
    assignments = (
        TeacherAssignment.objects.filter(teacher=teacher, academic_year_id=academic_year_id)
        .select_related("section__class_obj", "subject")
        .order_by("section__class_obj__display_order", "section__name", "subject__name")
    )
    cards: list[dict] = []
    for assignment in assignments:
        section = assignment.section
        enrollment = StudentEnrollment.objects.filter(section=section, status="active").count()
        first_mark = (
            Attendance.objects.filter(section=section, date=today).order_by("marked_at").first()
        )
        cards.append(
            {
                "id": str(section.id),
                "name": section.class_obj.name,
                "section": section.name,
                "subject": assignment.subject.name,
                "schedule": "",
                "enrollment": enrollment,
                "attendance_marked": first_mark is not None,
                "attendance_time": hhmm_local(first_mark.marked_at) if first_mark else None,
            }
        )
    return cards


def assigned_section(*, teacher: Any, section_id: int, academic_year_id: int | None) -> Section:
    """Return the section only if the teacher teaches it this year, else 404.
    Section.objects is school-scoped, so cross-tenant ids already 404."""
    section = (
        Section.objects.filter(id=section_id).select_related("class_obj").first()
    )
    if section is None or not TeacherAssignment.objects.filter(
        teacher=teacher, section_id=section_id, academic_year_id=academic_year_id
    ).exists():
        raise NotFound("Class not found.")
    return section


def list_class_students(*, teacher: Any, section_id: int, academic_year_id: int | None) -> list[dict]:
    assigned_section(teacher=teacher, section_id=section_id, academic_year_id=academic_year_id)
    enrollments = (
        StudentEnrollment.objects.filter(section_id=section_id, status="active")
        .select_related("student")
    )
    rows = [
        {
            "id": str(e.student.id),
            "roll_no": roll_to_int(e.roll_number),
            "name": e.student.full_name,
            "gender": gender_code(e.student.gender),
            "parent_phone": e.student.parent1_phone,
        }
        for e in enrollments
    ]
    # Stored roll numbers are free-text; order numerically, unknowns last.
    rows.sort(key=lambda r: (r["roll_no"] is None, r["roll_no"] or 0, r["name"]))
    return rows
