"""Business logic for the teacher tests & scores endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.academics.models import StudentEnrollment, TeacherAssignment
from apps.academics.teacher_services import assigned_section
from apps.core.exceptions import NotFound, ValidationFailed
from apps.core.helpers import roll_to_int, today_local
from apps.exams.models import Test, TestScore, TestType

PASS_THRESHOLD_PCT = 35  # <35% is "below pass"

_BANDS = [
    {"label": "Excellent",  "range": "80-100%", "min": 80, "max": 101},
    {"label": "Good",       "range": "60-79%",  "min": 60, "max": 80},
    {"label": "Average",    "range": "35-59%",  "min": 35, "max": 60},
    {"label": "Below Pass", "range": "< 35%",   "min": 0,  "max": 35},
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _derive_status(test: Test, today: date) -> str:
    if test.published_at is not None:
        return "published"
    if test.test_date > today:
        return "scheduled"
    return "grading"


def _test_to_dict(
    test: Test,
    section_label: str,
    subject_name: str,
    total_students: int,
    today: date,
) -> dict:
    status = _derive_status(test, today)
    scores = list(test.scores.all())

    avg_score = None
    submissions = None

    if status == "published":
        non_absent = [
            s for s in scores
            if not s.is_absent and s.marks_obtained is not None
        ]
        if non_absent and test.max_marks > 0:
            pcts = [float(s.marks_obtained) / test.max_marks * 100 for s in non_absent]
            avg_score = round(sum(pcts) / len(pcts))
    elif status == "grading":
        entered = [s for s in scores if s.is_absent or s.marks_obtained is not None]
        submissions = len(entered)

    return {
        "id": str(test.id),
        "title": test.name,
        "subject": subject_name,
        "class_label": section_label,
        "class_id": str(test.section_id),
        "date": test.test_date.isoformat(),
        "duration_min": 0,
        "questions": 0,
        "max_marks": test.max_marks,
        "status": status,
        "avg_score": avg_score,
        "submissions": submissions,
        "total_students": total_students,
    }


def _get_assigned_test(teacher: Any, test_id: int, academic_year_id: int | None) -> Test:
    """Fetch test and verify the teacher is assigned to its section (else 404)."""
    test = (
        Test.objects.filter(id=test_id)
        .select_related("section__class_obj", "subject", "school")
        .prefetch_related("scores")
        .first()
    )
    if test is None:
        raise NotFound("Test not found.")
    if not TeacherAssignment.objects.filter(
        teacher=teacher,
        section_id=test.section_id,
        academic_year_id=academic_year_id,
    ).exists():
        raise NotFound("Test not found.")
    return test


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

def list_tests(
    *,
    teacher: Any,
    academic_year_id: int | None,
    status_filter: str | None = None,
) -> list[dict]:
    """All tests for sections the teacher is assigned to this academic year."""
    today = today_local()
    section_ids = list(
        TeacherAssignment.objects.filter(
            teacher=teacher, academic_year_id=academic_year_id
        )
        .values_list("section_id", flat=True)
        .distinct()
    )
    tests = (
        Test.objects.filter(section_id__in=section_ids)
        .select_related("section__class_obj", "subject")
        .prefetch_related("scores")
        .order_by("-test_date", "-id")
    )

    result = []
    for test in tests:
        section = test.section
        section_label = f"{section.class_obj.name} — {section.name}"
        total = StudentEnrollment.objects.filter(
            section=section, status="active"
        ).count()
        row = _test_to_dict(test, section_label, test.subject.name, total, today)
        if status_filter and row["status"] != status_filter:
            continue
        result.append(row)
    return result


def get_test(
    *,
    teacher: Any,
    test_id: int,
    academic_year_id: int | None,
) -> dict:
    today = today_local()
    test = _get_assigned_test(teacher, test_id, academic_year_id)
    section = test.section
    section_label = f"{section.class_obj.name} — {section.name}"
    total = StudentEnrollment.objects.filter(
        section=section, status="active"
    ).count()
    return _test_to_dict(test, section_label, test.subject.name, total, today)


def create_test(
    *,
    teacher: Any,
    academic_year_id: int | None,
    section_id: int,
    name: str,
    test_type: str,
    test_date: date,
    max_marks: int,
) -> dict:
    section = assigned_section(
        teacher=teacher, section_id=section_id, academic_year_id=academic_year_id
    )
    assignment = (
        TeacherAssignment.objects.filter(
            teacher=teacher, section=section, academic_year_id=academic_year_id
        )
        .select_related("subject")
        .first()
    )
    if assignment is None:
        raise NotFound("No subject assignment found for this section.")

    test_type_val = test_type if test_type in TestType.values else TestType.OTHER
    test = Test.objects.create(
        school=section.school,
        section=section,
        subject=assignment.subject,
        name=name,
        test_type=test_type_val,
        test_date=test_date,
        max_marks=max_marks,
        created_by=teacher,
    )
    today = today_local()
    section_label = f"{section.class_obj.name} — {section.name}"
    total = StudentEnrollment.objects.filter(
        section=section, status="active"
    ).count()
    return _test_to_dict(test, section_label, assignment.subject.name, total, today)


def get_marks_roster(
    *,
    teacher: Any,
    test_id: int,
    academic_year_id: int | None,
) -> list[dict]:
    test = _get_assigned_test(teacher, test_id, academic_year_id)
    enrollments = (
        StudentEnrollment.objects.filter(section=test.section, status="active")
        .select_related("student")
    )
    existing = {
        str(s.student_id): s for s in TestScore.objects.filter(test=test)
    }
    rows = []
    for e in enrollments:
        sid = str(e.student.id)
        score = existing.get(sid)
        rows.append({
            "student_id": sid,
            "roll_no": roll_to_int(e.roll_number),
            "name": e.student.full_name,
            "marks_obtained": score.marks_obtained if score else None,
            "is_absent": score.is_absent if score else False,
        })
    rows.sort(key=lambda r: (r["roll_no"] is None, r["roll_no"] or 0, r["name"]))
    return rows


def save_marks(
    *,
    teacher: Any,
    test_id: int,
    academic_year_id: int | None,
    records: list[dict],
    publish: bool,
) -> dict:
    test = _get_assigned_test(teacher, test_id, academic_year_id)
    if test.published_at is not None:
        raise ValidationFailed("Cannot edit marks on a published test.")

    saved = 0
    with transaction.atomic():
        for rec in records:
            student_id = int(rec["student_id"])
            is_absent = bool(rec.get("is_absent", False))
            marks_obtained = rec.get("marks_obtained")
            if is_absent:
                marks_obtained = None
            TestScore.objects.update_or_create(
                school=test.school,
                test=test,
                student_id=student_id,
                defaults={
                    "marks_obtained": marks_obtained,
                    "is_absent": is_absent,
                    "entered_by": teacher,
                },
            )
            saved += 1
        if publish:
            test.published_at = timezone.now()
            test.save(update_fields=["published_at", "updated_at"])

    return {"saved": saved, "published": publish}


def get_report(
    *,
    teacher: Any,
    test_id: int,
    academic_year_id: int | None,
) -> dict:
    today = today_local()
    test = _get_assigned_test(teacher, test_id, academic_year_id)
    section = test.section
    section_label = f"{section.class_obj.name} — {section.name}"
    total_students = StudentEnrollment.objects.filter(
        section=section, status="active"
    ).count()
    test_out = _test_to_dict(
        test, section_label, test.subject.name, total_students, today
    )

    enrollments = (
        StudentEnrollment.objects.filter(section=section, status="active")
        .select_related("student")
    )
    scores_map = {
        str(s.student_id): s for s in TestScore.objects.filter(test=test)
    }

    students = []
    for e in enrollments:
        sid = str(e.student.id)
        score = scores_map.get(sid)
        is_absent = score.is_absent if score else False
        marks = score.marks_obtained if score and not is_absent else None
        pct = (
            round(float(marks) / test.max_marks * 100)
            if marks is not None and test.max_marks > 0
            else None
        )
        students.append(
            {
                "student_id": sid,
                "roll_no": roll_to_int(e.roll_number),
                "name": e.student.full_name,
                "marks": marks,
                "pct": pct,
                "is_absent": is_absent,
            }
        )
    students.sort(key=lambda r: (r["pct"] is None, -(r["pct"] or 0)))

    scored = [s for s in students if s["pct"] is not None]
    avg = round(sum(s["pct"] for s in scored) / len(scored)) if scored else 0  # type: ignore[arg-type]
    top = scored[0] if scored else None
    passed = sum(1 for s in scored if (s["pct"] or 0) >= PASS_THRESHOLD_PCT)
    pass_rate = round(passed / len(scored) * 100) if scored else 0

    bands = []
    for band in _BANDS:
        count = sum(
            1 for s in scored if band["min"] <= (s["pct"] or 0) < band["max"]
        )
        bands.append({"label": band["label"], "range": band["range"], "count": count})

    return {
        "test": test_out,
        "students": students,
        "avg": avg,
        "top_score": top["marks"] if top else None,
        "top_student": top["name"] if top else None,
        "passed": passed,
        "pass_rate": pass_rate,
        "total": len(students),
        "bands": bands,
    }
