"""Teacher attendance read/write services."""

from __future__ import annotations

from datetime import date
from typing import Any

from django.db import transaction

from apps.academics.models import StudentEnrollment, TeacherAssignment
from apps.academics.teacher_services import assigned_section
from apps.attendance.models import Attendance, AttendanceStatus
from apps.core.helpers import roll_to_int


def attendance_summary(*, teacher: Any, academic_year_id: int | None, on_date: date) -> list[dict]:
    """Per-section attendance summary for all sections the teacher is assigned to."""
    assignments = (
        TeacherAssignment.objects.filter(teacher=teacher, academic_year_id=academic_year_id)
        .select_related("section__class_obj", "subject")
        .order_by("section__class_obj__display_order", "section__name")
    )

    seen: dict[int, dict] = {}
    for assignment in assignments:
        section = assignment.section
        sid = section.id
        if sid in seen:
            continue
        enrollments = StudentEnrollment.objects.filter(section=section, status="active")
        total = enrollments.count()
        records = Attendance.objects.filter(section=section, date=on_date)
        absent = records.filter(status=AttendanceStatus.ABSENT).count()
        present = records.filter(status=AttendanceStatus.PRESENT).count()
        seen[sid] = {
            "section_id": str(sid),
            "class_name": section.class_obj.name,
            "section": section.name,
            "subject": assignment.subject.name,
            "total": total,
            "present": present,
            "absent": absent,
            "rate": round(present / total * 100) if total else 0,
            "marked": records.exists(),
        }
    return list(seen.values())


def get_attendance(
    *, teacher: Any, section_id: int, academic_year_id: int | None, on_date: date
) -> list[dict]:
    """Per-student attendance for a section on a given date.

    Pre-fills with 'present' for enrolled students who have no record yet,
    so the mark screen always shows a full roster.
    """
    section = assigned_section(teacher=teacher, section_id=section_id, academic_year_id=academic_year_id)
    enrollments = (
        StudentEnrollment.objects.filter(section=section, status="active")
        .select_related("student")
    )
    existing = {
        str(a.student_id): a.status
        for a in Attendance.objects.filter(section=section, date=on_date)
    }
    rows = []
    for e in enrollments:
        sid = str(e.student.id)
        rows.append({
            "student_id": sid,
            "roll_no": roll_to_int(e.roll_number),
            "name": e.student.full_name,
            "status": existing.get(sid, AttendanceStatus.PRESENT),
        })
    rows.sort(key=lambda r: (r["roll_no"] is None, r["roll_no"] or 0, r["name"]))
    return rows


def save_attendance(
    *,
    teacher: Any,
    section_id: int,
    academic_year_id: int | None,
    on_date: date,
    records: list[dict],
) -> int:
    """Bulk upsert attendance records. Returns count of rows saved."""
    section = assigned_section(teacher=teacher, section_id=section_id, academic_year_id=academic_year_id)
    school = section.school

    valid_statuses = {s.value for s in AttendanceStatus}
    with transaction.atomic():
        saved = 0
        for rec in records:
            status = rec["status"] if rec["status"] in valid_statuses else AttendanceStatus.PRESENT
            Attendance.objects.update_or_create(
                school=school,
                student_id=int(rec["student_id"]),
                section=section,
                date=on_date,
                defaults={"status": status},
            )
            saved += 1
    return saved
