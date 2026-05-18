"""Read services for attendance.

All queries are tenant-safe via the TenantManager. The selector functions
take a ``school`` to be explicit for defence-in-depth — the manager would
also catch a cross-tenant attempt with an empty result.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import Any

from django.db.models import Count, Q

from apps.academics.models import Section, StudentEnrollment
from apps.attendance.models import Attendance, AttendanceStatus
from apps.schools.models import School

WEIGHTS: dict[str, float] = {
    AttendanceStatus.PRESENT: 1.0,
    AttendanceStatus.LATE: 1.0,      # late students are still present
    AttendanceStatus.HALF_DAY: 0.5,
    AttendanceStatus.ABSENT: 0.0,
}


def _attendance_pct(counts: Counter[str]) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    weighted = sum(counts[s] * w for s, w in WEIGHTS.items())
    return round(100 * weighted / total, 1)


def section_attendance_for_date(
    *, school: School, section: Section, day: date
) -> dict[str, Any]:
    """Return the section roster plus each student's mark for the given date.
    Students without a mark get status=None."""
    enrollments = list(
        StudentEnrollment.objects.filter(
            school=school, section=section, status="active"
        )
        .select_related("student")
        .order_by("roll_number", "student__first_name")
    )
    marks_by_student = {
        a.student_id: a
        for a in Attendance.objects.filter(
            school=school, section=section, date=day
        ).select_related("marked_by")
    }

    summary: Counter[str] = Counter()
    marks_out = []
    for enrollment in enrollments:
        student = enrollment.student
        att = marks_by_student.get(student.id)
        if att:
            summary[att.status] += 1
        else:
            summary["not_marked"] += 1
        marks_out.append({
            "student_id": student.id,
            "student_name": student.full_name,
            "admission_number": student.admission_number,
            "roll_number": enrollment.roll_number,
            "status": att.status if att else None,
            "notes": att.notes if att else "",
            "marked_at": att.marked_at if att else None,
            "marked_by_name": att.marked_by.full_name if att and att.marked_by else None,
        })

    # Ensure all keys present so the frontend doesn't have to defend against missing keys.
    for k in ("present", "absent", "late", "half_day", "not_marked"):
        summary.setdefault(k, 0)

    return {
        "section_id": section.id,
        "section_name": section.name,
        "class_name": section.class_obj.name,
        "date": day,
        "marks": marks_out,
        "summary": dict(summary),
    }


def student_attendance_history(
    *, school: School, student, from_date: date, to_date: date
) -> dict[str, Any]:
    if from_date > to_date:
        from_date, to_date = to_date, from_date

    records = list(
        Attendance.objects.filter(
            school=school, student=student, date__gte=from_date, date__lte=to_date
        ).order_by("date")
    )

    days = [
        {
            "date": r.date,
            "status": r.status,
            "notes": r.notes,
            "marked_at": r.marked_at,
        }
        for r in records
    ]
    counts: Counter[str] = Counter(r.status for r in records)
    for k in ("present", "absent", "late", "half_day"):
        counts.setdefault(k, 0)

    return {
        "student_id": student.id,
        "student_name": student.full_name,
        "from_date": from_date,
        "to_date": to_date,
        "days": days,
        "summary": dict(counts),
        "attendance_pct": _attendance_pct(counts),
    }


def section_summary(
    *, school: School, section: Section, from_date: date, to_date: date
) -> dict[str, Any]:
    if from_date > to_date:
        from_date, to_date = to_date, from_date

    enrollments = list(
        StudentEnrollment.objects.filter(
            school=school, section=section, status="active"
        )
        .select_related("student")
        .order_by("roll_number", "student__first_name")
    )
    student_ids = [e.student_id for e in enrollments]

    records = list(
        Attendance.objects.filter(
            school=school,
            section=section,
            student_id__in=student_ids,
            date__gte=from_date,
            date__lte=to_date,
        )
    )
    by_student: dict[int, Counter[str]] = {sid: Counter() for sid in student_ids}
    school_dates: set[date] = set()
    for r in records:
        by_student[r.student_id][r.status] += 1
        school_dates.add(r.date)

    rows = []
    for enrollment in enrollments:
        student = enrollment.student
        counts = by_student[student.id]
        for k in ("present", "absent", "late", "half_day"):
            counts.setdefault(k, 0)
        total = sum(counts.values())
        rows.append({
            "student_id": student.id,
            "student_name": student.full_name,
            "admission_number": student.admission_number,
            "roll_number": enrollment.roll_number,
            "present": counts["present"],
            "absent": counts["absent"],
            "late": counts["late"],
            "half_day": counts["half_day"],
            "total_marked": total,
            "attendance_pct": _attendance_pct(counts),
        })

    return {
        "section_id": section.id,
        "section_name": section.name,
        "class_name": section.class_obj.name,
        "from_date": from_date,
        "to_date": to_date,
        "students": rows,
        "school_days": len(school_dates),
    }


def default_window() -> tuple[date, date]:
    """Default to last 30 days."""
    today = date.today()
    return today - timedelta(days=30), today


def all_sections_daily_rollup(*, school: School, day: date) -> dict[str, Any]:
    """One-shot daily summary for every section in the school.

    Two queries total regardless of section count:
    1. Sections with annotated active-student count and joined class teacher.
    2. Attendance rows for the date, aggregated by (section, status).

    Avoids the N+1 a per-section call would create on the dashboard.
    """
    sections = list(
        Section.objects.filter(school=school)
        .select_related("class_obj", "class_teacher")
        .annotate(
            active_count=Count(
                "enrollments", filter=Q(enrollments__status="active"), distinct=True
            ),
        )
        .order_by("class_obj__display_order", "name")
    )

    # Aggregate attendance counts grouped by (section, status) in one query.
    rows = (
        Attendance.objects.filter(school=school, date=day)
        .values("section_id", "status")
        .annotate(c=Count("id"))
    )
    by_section: dict[int, Counter[str]] = {}
    for r in rows:
        by_section.setdefault(r["section_id"], Counter())[r["status"]] = r["c"]

    out_sections = []
    totals: Counter[str] = Counter()
    marked_section_count = 0

    for section in sections:
        counts = by_section.get(section.id, Counter())
        active = section.active_count or 0
        marked_total = sum(counts.values())
        not_marked = max(0, active - marked_total)

        summary = {
            "present": counts.get("present", 0),
            "absent": counts.get("absent", 0),
            "late": counts.get("late", 0),
            "half_day": counts.get("half_day", 0),
            "not_marked": not_marked,
        }
        if marked_total > 0:
            marked_section_count += 1
        for k in ("present", "absent", "late", "half_day", "not_marked"):
            totals[k] += summary[k]

        teacher = section.class_teacher
        out_sections.append({
            "section_id": section.id,
            "section_name": section.name,
            "class_id": section.class_obj_id,
            "class_name": section.class_obj.name,
            "display_order": section.class_obj.display_order,
            "class_teacher_id": teacher.id if teacher else None,
            "class_teacher_name": teacher.full_name if teacher else None,
            "active_student_count": active,
            "summary": summary,
        })

    return {
        "date": day,
        "sections": out_sections,
        "totals": dict(totals),
        "marked_section_count": marked_section_count,
        "total_section_count": len(sections),
    }
