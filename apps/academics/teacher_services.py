"""Read logic for the teacher app's classes & roster.

A teacher's "classes" are their TeacherAssignment rows for the school's current
academic year — one card per (section, subject). classId is the section PK;
all queries are school-scoped by the TenantManager and additionally gated on
the teacher actually being assigned to the section.
"""

from __future__ import annotations

from datetime import time as time_type
from typing import Any

from apps.academics.models import (
    Section,
    StudentEnrollment,
    TeacherAssignment,
    TimetablePeriod,
)
from apps.attendance.models import Attendance
from apps.core.exceptions import NotFound
from apps.core.helpers import gender_code, hhmm_local, roll_to_int, today_local


def _fmt_period(start: time_type, end: time_type) -> str:
    """Format a period as a readable range, e.g. "10:00 - 10:45 AM".
    Drops the meridiem on the start when it matches the end's."""
    s = start.strftime("%I:%M %p").lstrip("0")
    e = end.strftime("%I:%M %p").lstrip("0")
    if s[-2:] == e[-2:]:  # same AM/PM - show it once
        s = s[:-3]
    return f"{s} – {e}"  # noqa: RUF001 — en dash is intentional for the range


def _today_schedule_by_section(*, teacher: Any) -> dict[int, str]:
    """The teacher's earliest period today per section, as a display string.
    Empty when the school hasn't entered a timetable — schedule stays optional."""
    weekday = today_local().isoweekday()  # Mon=1 … Sat=6, matching DayOfWeek
    periods = TimetablePeriod.objects.filter(
        teacher=teacher, day_of_week=weekday
    ).order_by("section_id", "period_number")
    schedule: dict[int, str] = {}
    for p in periods:
        # First (earliest) period wins when a teacher has the section twice today.
        if p.section_id not in schedule:
            schedule[p.section_id] = _fmt_period(p.start_time, p.end_time)
    return schedule


def list_teacher_classes(*, teacher: Any, academic_year_id: int | None) -> list[dict]:
    today = today_local()
    schedule_by_section = _today_schedule_by_section(teacher=teacher)
    assignments = (
        TeacherAssignment.objects.filter(teacher=teacher, academic_year_id=academic_year_id)
        .select_related("section__class_obj", "subject")
        .order_by("section__class_obj__display_order", "section__name", "subject__name")
    )

    # Group by section — a teacher can teach multiple subjects in the same section.
    seen: dict[int, dict] = {}
    for assignment in assignments:
        section = assignment.section
        sid = section.id
        if sid not in seen:
            enrollment = StudentEnrollment.objects.filter(section=section, status="active").count()
            first_mark = (
                Attendance.objects.filter(section=section, date=today).order_by("marked_at").first()
            )
            seen[sid] = {
                "id": str(sid),
                "name": section.class_obj.name,
                "section": section.name,
                "subject": assignment.subject.name,
                "_subjects": [assignment.subject.name],
                "schedule": schedule_by_section.get(sid, ""),
                "enrollment": enrollment,
                "attendance_marked": first_mark is not None,
                "attendance_time": hhmm_local(first_mark.marked_at) if first_mark else None,
            }
        else:
            seen[sid]["_subjects"].append(assignment.subject.name)

    cards = []
    attendance_class_assigned = False
    for card in seen.values():
        card["subject"] = " · ".join(card.pop("_subjects"))
        # Mark the first class (lowest display_order) as the attendance class.
        # This is the only place that needs to change when schools configure a
        # different rule (homeroom section, explicit flag, etc.).
        if not attendance_class_assigned:
            card["is_attendance_class"] = True
            attendance_class_assigned = True
        else:
            card["is_attendance_class"] = False
        cards.append(card)
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
