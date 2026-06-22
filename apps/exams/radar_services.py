"""Strength/weakness radar — relative grading across common tests.

A student's profile is a per-subject *percentile* measured against their whole
grade (every sibling section), not a raw average. It is built only from
**common tests**: tests that every section of the grade has published under the
same exam name. Until all sections publish a subject's common test, that
subject stays off the radar (listed in ``pending_subjects`` instead).

See :func:`build_strength_profile` for the full algorithm. The same function
feeds the parent app (own child), the teacher app (per-student) and the admin
portal (any student) — the only difference between those callers is how the
student is authorised and resolved.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from apps.academics.models import Section, StudentEnrollment
from apps.exams.models import Test
from apps.people.models import Student
from apps.schools.models import School


def _percentile(value: float, cohort: list[float]) -> int:
    """Percentile rank of ``value`` within ``cohort`` (cohort includes value).

    Ordinal rank expressed 0-100: the share of peers scoring *strictly below*.
    Ties share a rank; the top scorer lands on 100, the bottom on 0. This is the
    0-100 form of the ``rank = count(above) + 1`` logic used elsewhere.
    """
    n = len(cohort)
    if n <= 1:
        return 100
    below = sum(1 for m in cohort if m < value)
    return round(100 * below / (n - 1))


def _empty_profile() -> dict[str, Any]:
    return {
        "class_name": "",
        "section": "",
        "academic_year": "",
        "section_count": 0,
        "cohort_size": 0,
        "overall_percentile": None,
        "subjects": [],
        "pending_subjects": [],
    }


def build_strength_profile(
    *, school: School, student: Student, academic_year_id: int | None
) -> dict[str, Any]:
    """Build a student's per-subject percentile radar for the given year.

    Returns an empty profile (no axes) when the student has no active
    enrollment, when no common test is fully published yet, or when the student
    was absent for every eligible common test in a subject.
    """
    enroll_qs = StudentEnrollment.objects.filter(
        school=school, student=student, status="active"
    ).select_related("section__class_obj__academic_year")
    enrollment = None
    if academic_year_id is not None:
        enrollment = enroll_qs.filter(academic_year_id=academic_year_id).first()
    enrollment = enrollment or enroll_qs.first()
    if enrollment is None:
        return _empty_profile()

    section = enrollment.section
    class_obj = section.class_obj

    siblings = list(Section.objects.filter(school=school, class_obj=class_obj))

    # The gate requires *every section that actually has students* to have
    # published — an empty/placeholder section never blocks the radar.
    grade_enrollments = StudentEnrollment.objects.filter(
        school=school, section__class_obj=class_obj, status="active"
    )
    enrolled_section_ids = set(grade_enrollments.values_list("section_id", flat=True))
    required_ids = enrolled_section_ids or {s.id for s in siblings}
    cohort_size = grade_enrollments.count()

    # Common tests = published tests across the grade carrying an exam name.
    tests = (
        Test.objects.filter(
            school=school,
            section__class_obj=class_obj,
            published_at__isnull=False,
            exam_name__isnull=False,
        )
        .select_related("subject")
        .prefetch_related("scores")
    )

    # Group by the shared identity of a "common test": same exam name + same
    # exact title + same subject. The title keeps series entries ("Weekly Test
    # 1" vs "Weekly Test 2") as distinct groups.
    groups: dict[tuple, dict[str, Any]] = defaultdict(
        lambda: {"subject_id": None, "subject_name": "", "sections": set(), "tests": []}
    )
    for t in tests:
        g = groups[(t.exam_name_id, t.name, t.subject_id)]
        g["subject_id"] = t.subject_id
        g["subject_name"] = t.subject.name
        g["sections"].add(t.section_id)
        g["tests"].append(t)

    subj_percentiles: dict[int, list[int]] = defaultdict(list)
    subj_raw: dict[int, list[float]] = defaultdict(list)
    subj_name: dict[int, str] = {}
    subjects_with_groups: set[int] = set()

    for g in groups.values():
        subj_id = g["subject_id"]
        subj_name[subj_id] = g["subject_name"]
        subjects_with_groups.add(subj_id)

        # Strict gate: every section with students must have published here.
        if not required_ids.issubset(g["sections"]):
            continue

        cohort: list[float] = []
        student_vals: list[float] = []
        for t in g["tests"]:
            if not t.max_marks:
                continue
            for s in t.scores.all():
                if s.is_absent or s.marks_obtained is None:
                    continue
                pct = float(s.marks_obtained) / t.max_marks * 100
                cohort.append(pct)
                if s.student_id == student.id:
                    student_vals.append(pct)
        if not student_vals or not cohort:
            continue
        my_pct = sum(student_vals) / len(student_vals)
        subj_percentiles[subj_id].append(_percentile(my_pct, cohort))
        subj_raw[subj_id].append(my_pct)

    subjects_out = [
        {
            "subject_id": subj_id,
            "subject": subj_name[subj_id],
            "percentile": round(sum(pcts) / len(pcts)),
            "avg_percent": round(sum(subj_raw[subj_id]) / len(subj_raw[subj_id])),
            "test_count": len(pcts),
        }
        for subj_id, pcts in subj_percentiles.items()
    ]
    subjects_out.sort(key=lambda s: s["subject"])

    # Subjects that have common tests but aren't on the radar yet — either a
    # section hasn't published, or the student was absent throughout.
    represented = {s["subject_id"] for s in subjects_out}
    pending = sorted(
        subj_name[sid] for sid in subjects_with_groups if sid not in represented
    )

    overall = (
        round(sum(s["percentile"] for s in subjects_out) / len(subjects_out))
        if subjects_out
        else None
    )

    return {
        "class_name": class_obj.name,
        "section": section.name,
        "academic_year": class_obj.academic_year.label,
        "section_count": len(siblings),
        "cohort_size": cohort_size,
        "overall_percentile": overall,
        "subjects": subjects_out,
        "pending_subjects": pending,
    }
