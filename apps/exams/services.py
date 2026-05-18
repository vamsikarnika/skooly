"""Read services for tests & scores.

All endpoints filter to ``published_at__isnull=False`` by default — drafts
are teacher-app territory. Stats exclude absents from average/min/max.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import QuerySet

from apps.academics.models import StudentEnrollment
from apps.exams.models import Test, TestScore
from apps.people.models import Student
from apps.schools.models import School


def _stats_from_scores(scores: list[TestScore], roster_size: int) -> dict[str, Any]:
    scored: list[Decimal] = []
    absent = 0
    for s in scores:
        if s.is_absent:
            absent += 1
        elif s.marks_obtained is not None:
            scored.append(s.marks_obtained)
    avg = (sum(scored) / len(scored)) if scored else None
    return {
        "student_count": roster_size,
        "scored_count": len(scored),
        "absent_count": absent,
        "average": round(float(avg), 2) if avg is not None else None,
        "max_marks_scored": max(scored) if scored else None,
        "min_marks_scored": min(scored) if scored else None,
    }


def list_published_tests(
    *,
    school: School,
    section_id: int | None = None,
    class_id: int | None = None,
    subject_id: int | None = None,
    test_type: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> QuerySet[Test]:
    qs = (
        Test.objects.filter(published_at__isnull=False)
        .select_related("section__class_obj", "subject", "created_by")
        .prefetch_related("scores")
    )
    if section_id:
        qs = qs.filter(section_id=section_id)
    if class_id:
        qs = qs.filter(section__class_obj_id=class_id)
    if subject_id:
        qs = qs.filter(subject_id=subject_id)
    if test_type:
        qs = qs.filter(test_type=test_type)
    if from_date:
        qs = qs.filter(test_date__gte=from_date)
    if to_date:
        qs = qs.filter(test_date__lte=to_date)
    return qs


def test_summary_dict(test: Test) -> dict[str, Any]:
    """Lightweight per-test summary used in list responses."""
    roster_size = StudentEnrollment.objects.filter(
        school=test.school, section=test.section, status="active"
    ).count()
    scores = list(test.scores.all())
    return {
        "id": test.id,
        "name": test.name,
        "test_type": test.test_type,
        "test_date": test.test_date,
        "max_marks": test.max_marks,
        "section_id": test.section_id,
        "section_name": test.section.name,
        "class_id": test.section.class_obj_id,
        "class_name": test.section.class_obj.name,
        "subject_id": test.subject_id,
        "subject_name": test.subject.name,
        "created_by_name": test.created_by.full_name if test.created_by else None,
        "published_at": test.published_at,
        "stats": _stats_from_scores(scores, roster_size),
    }


def test_detail_dict(test: Test) -> dict[str, Any]:
    """Full per-test detail: roster + every student's score (or null)."""
    enrollments = list(
        StudentEnrollment.objects.filter(
            school=test.school, section=test.section, status="active"
        )
        .select_related("student")
        .order_by("roll_number", "student__first_name")
    )
    scores_by_student = {s.student_id: s for s in test.scores.all()}

    scores_out = []
    score_objects: list[TestScore] = []
    for enrollment in enrollments:
        student = enrollment.student
        score = scores_by_student.get(student.id)
        scores_out.append({
            "student_id": student.id,
            "student_name": student.full_name,
            "admission_number": student.admission_number,
            "roll_number": enrollment.roll_number,
            "marks": score.marks_obtained if score else None,
            "is_absent": score.is_absent if score else False,
        })
        if score:
            score_objects.append(score)

    summary = test_summary_dict(test)
    summary["stats"] = _stats_from_scores(score_objects, len(enrollments))
    summary["scores"] = scores_out
    return summary


def student_scores_history(
    *,
    school: School,
    student: Student,
    from_date: date | None = None,
    to_date: date | None = None,
) -> dict[str, Any]:
    qs = TestScore.objects.filter(
        school=school, student=student, test__published_at__isnull=False
    ).select_related("test__subject")
    if from_date:
        qs = qs.filter(test__test_date__gte=from_date)
    if to_date:
        qs = qs.filter(test__test_date__lte=to_date)

    by_subject: dict[int, dict[str, Any]] = defaultdict(
        lambda: {"subject_id": 0, "subject_name": "", "tests": [], "percent_total": 0.0, "percent_count": 0}
    )

    for score in qs.order_by("test__test_date"):
        test = score.test
        subj_id = test.subject_id
        bucket = by_subject[subj_id]
        bucket["subject_id"] = subj_id
        bucket["subject_name"] = test.subject.name
        pct: float | None
        if score.is_absent or score.marks_obtained is None:
            pct = None
        else:
            pct = round(100 * float(score.marks_obtained) / test.max_marks, 1)
        if pct is not None:
            bucket["percent_total"] += pct
            bucket["percent_count"] += 1
        bucket["tests"].append({
            "test_id": test.id,
            "test_name": test.name,
            "test_type": test.test_type,
            "test_date": test.test_date,
            "subject_id": subj_id,
            "subject_name": test.subject.name,
            "max_marks": test.max_marks,
            "marks": score.marks_obtained,
            "is_absent": score.is_absent,
            "percent": pct,
        })

    out_by_subject = []
    for subj in sorted(by_subject.values(), key=lambda b: b["subject_name"]):
        avg = (
            round(subj["percent_total"] / subj["percent_count"], 1)
            if subj["percent_count"] > 0
            else None
        )
        out_by_subject.append({
            "subject_id": subj["subject_id"],
            "subject_name": subj["subject_name"],
            "tests": subj["tests"],
            "average_percent": avg,
        })

    return {
        "student_id": student.id,
        "student_name": student.full_name,
        "from_date": from_date or date.min,
        "to_date": to_date or date.max,
        "by_subject": out_by_subject,
    }
