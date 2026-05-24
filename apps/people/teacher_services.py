"""Single-student detail for the teacher app.

Visible only if the student is enrolled in a section the teacher is assigned
to this year — otherwise 404 (no existence leak), on top of school scoping.
"""

from __future__ import annotations

from typing import Any

from apps.academics.models import StudentEnrollment, TeacherAssignment
from apps.attendance.models import Attendance
from apps.core.exceptions import NotFound
from apps.core.helpers import gender_code, roll_to_int
from apps.exams.models import TestScore
from apps.people.models import Student


def student_detail(*, teacher: Any, student_id: int, academic_year_id: int | None) -> dict:
    student = Student.objects.filter(id=student_id).first()
    enrollment = (
        StudentEnrollment.objects.filter(student_id=student_id, status="active")
        .select_related("section__class_obj")
        .first()
    )
    if student is None or enrollment is None:
        raise NotFound("Student not found.")
    section = enrollment.section
    if not TeacherAssignment.objects.filter(
        teacher=teacher, section=section, academic_year_id=academic_year_id
    ).exists():
        raise NotFound("Student not found.")

    attendance = Attendance.objects.filter(student_id=student_id)
    total = attendance.count()
    absent = attendance.filter(status="absent").count()
    present = total - absent
    rate = round(present / total * 100) if total else 0

    scores = (
        TestScore.objects.filter(student_id=student_id, test__published_at__isnull=False)
        .select_related("test")
        .order_by("-test__test_date")
    )
    test_scores: list[dict] = []
    for score in scores:
        test = score.test
        marks = float(score.marks_obtained) if score.marks_obtained is not None else None
        pct = round(marks / test.max_marks * 100) if (marks is not None and test.max_marks) else None
        test_scores.append(
            {
                "test_id": str(test.id),
                "test_title": test.name,
                "date": test.test_date.strftime("%a, %d %b"),
                "marks": marks,
                "max_marks": test.max_marks,
                "percentage": pct,
            }
        )

    return {
        "id": str(student.id),
        "roll_no": roll_to_int(enrollment.roll_number),
        "name": student.full_name,
        "gender": gender_code(student.gender),
        "parent_phone": student.parent1_phone,
        "class_id": str(section.id),
        "class_name": section.class_obj.name,
        "section": section.name,
        "attendance": {"total_days": total, "present": present, "absent": absent, "rate": rate},
        "test_scores": test_scores,
    }
