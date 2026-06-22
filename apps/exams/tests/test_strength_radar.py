"""Strength/weakness radar — relative grading across common tests.

Covers the compute service (percentile vs the whole grade, the strict
all-sections-published gate, common-tests-only, multi-test averaging, absent
handling) and the thin endpoints (admin/internal read + the teacher access
gate). The percentile math lives entirely in ``radar_services`` so most of the
coverage drives it directly under a tenant context.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.test import Client
from django.utils import timezone

from apps.academics.models import StudentEnrollment, TeacherAssignment
from apps.academics.tests.factories import SubjectFactory
from apps.core.context import use_school
from apps.exams import radar_services
from apps.exams.models import ExamName
from apps.exams.tests.factories import TestFactory, TestScoreFactory
from apps.people.tests.factories import StudentFactory, TeacherFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _enroll(school, student, section, year):
    return StudentEnrollment.objects.create(
        school=school,
        student=student,
        section=section,
        academic_year=year,
        enrollment_date=date(2025, 6, 1),
        status="active",
    )


def _common_test(school, section, subject, exam_name, *, name, max_marks=50, published=True):
    return TestFactory(
        school=school,
        section=section,
        subject=subject,
        exam_name=exam_name,
        name=name,
        max_marks=max_marks,
        published_at=timezone.now() if published else None,
    )


def _score(school, test, student, marks, *, absent=False):
    return TestScoreFactory(
        school=school,
        test=test,
        student=student,
        marks_obtained=None if absent else marks,
        is_absent=absent,
    )


def _grade(world_a):
    """Two students per section in the world's Class 6 + a 'Mathematics' subject."""
    school, year = world_a["school"], world_a["year"]
    a, b = world_a["section_a"], world_a["section_b"]
    students = {k: StudentFactory(school=school) for k in ("a1", "a2", "b1", "b2")}
    _enroll(school, students["a1"], a, year)
    _enroll(school, students["a2"], a, year)
    _enroll(school, students["b1"], b, year)
    _enroll(school, students["b2"], b, year)
    subject = SubjectFactory(school=school, name="Mathematics")
    return students, subject


def _profile(school, student, year):
    with use_school(school):
        return radar_services.build_strength_profile(
            school=school, student=student, academic_year_id=year.id
        )


def _auth(token: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _set_current_year(school, year) -> None:
    school.current_academic_year = year
    school.save(update_fields=["current_academic_year"])


# ---------------------------------------------------------------------------
# Compute service
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_percentile_is_relative_to_whole_grade(world_a) -> None:
    school, year = world_a["school"], world_a["year"]
    students, subject = _grade(world_a)
    exam = ExamName.objects.create(school=school, label="Quarterly Exam", display_order=1)
    ta = _common_test(school, world_a["section_a"], subject, exam, name="Quarterly Exam")
    tb = _common_test(school, world_a["section_b"], subject, exam, name="Quarterly Exam")
    # Grade-wide percentages: a1=90, a2=50, b1=100, b2=60.
    _score(school, ta, students["a1"], 45)
    _score(school, ta, students["a2"], 25)
    _score(school, tb, students["b1"], 50)
    _score(school, tb, students["b2"], 30)

    prof = _profile(school, students["a1"], year)

    assert prof["class_name"] == "Class 6"
    assert prof["section"] == "A"
    assert prof["academic_year"] == "2025-26"
    assert prof["section_count"] == 2
    assert prof["cohort_size"] == 4
    assert prof["pending_subjects"] == []
    assert len(prof["subjects"]) == 1
    axis = prof["subjects"][0]
    assert axis["subject"] == "Mathematics"
    assert axis["avg_percent"] == 90
    assert axis["test_count"] == 1
    # a1 (90%) beats a2 (50) and b2 (60): 2 of 3 peers below -> 67.
    assert axis["percentile"] == 67
    assert prof["overall_percentile"] == 67
    # The grade's top scorer (b1, 100%) sits at 100.
    assert _profile(school, students["b1"], year)["subjects"][0]["percentile"] == 100


@pytest.mark.django_db
def test_subject_hidden_until_all_sections_publish(world_a) -> None:
    school, year = world_a["school"], world_a["year"]
    students, subject = _grade(world_a)
    exam = ExamName.objects.create(school=school, label="Quarterly Exam", display_order=1)
    ta = _common_test(school, world_a["section_a"], subject, exam, name="Quarterly Exam")
    tb = _common_test(
        school, world_a["section_b"], subject, exam, name="Quarterly Exam", published=False
    )
    _score(school, ta, students["a1"], 45)
    _score(school, ta, students["a2"], 25)
    _score(school, tb, students["b1"], 50)
    _score(school, tb, students["b2"], 30)

    # Section B hasn't published — the axis is withheld, listed as pending.
    prof = _profile(school, students["a1"], year)
    assert prof["subjects"] == []
    assert prof["pending_subjects"] == ["Mathematics"]

    # Once B publishes, the axis appears and pending clears.
    tb.published_at = timezone.now()
    tb.save(update_fields=["published_at"])
    prof = _profile(school, students["a1"], year)
    assert [s["subject"] for s in prof["subjects"]] == ["Mathematics"]
    assert prof["pending_subjects"] == []


@pytest.mark.django_db
def test_free_text_tests_are_ignored(world_a) -> None:
    """A test with no exam name has no cross-section identity — never plotted."""
    school, year = world_a["school"], world_a["year"]
    students, subject = _grade(world_a)
    ta = _common_test(school, world_a["section_a"], subject, None, name="Pop Quiz")
    tb = _common_test(school, world_a["section_b"], subject, None, name="Pop Quiz")
    _score(school, ta, students["a1"], 45)
    _score(school, tb, students["b1"], 50)

    prof = _profile(school, students["a1"], year)
    assert prof["subjects"] == []
    assert prof["pending_subjects"] == []


@pytest.mark.django_db
def test_averages_percentile_across_common_tests(world_a) -> None:
    school, year = world_a["school"], world_a["year"]
    a, b = world_a["section_a"], world_a["section_b"]
    students, subject = _grade(world_a)
    exam = ExamName.objects.create(
        school=school, label="Weekly Test", is_series=True, display_order=1
    )
    wt1_a = _common_test(school, a, subject, exam, name="Weekly Test 1")
    wt1_b = _common_test(school, b, subject, exam, name="Weekly Test 1")
    wt2_a = _common_test(school, a, subject, exam, name="Weekly Test 2")
    wt2_b = _common_test(school, b, subject, exam, name="Weekly Test 2")
    # WT1: a1 is top of the grade (100th pct).
    _score(school, wt1_a, students["a1"], 50)
    _score(school, wt1_a, students["a2"], 25)
    _score(school, wt1_b, students["b1"], 30)
    _score(school, wt1_b, students["b2"], 20)
    # WT2: a1 is bottom of the grade (0th pct).
    _score(school, wt2_a, students["a1"], 10)
    _score(school, wt2_a, students["a2"], 40)
    _score(school, wt2_b, students["b1"], 45)
    _score(school, wt2_b, students["b2"], 50)

    prof = _profile(school, students["a1"], year)
    axis = prof["subjects"][0]
    assert axis["test_count"] == 2
    assert axis["percentile"] == 50  # (100 + 0) / 2
    assert axis["avg_percent"] == 60  # (100% + 20%) / 2


@pytest.mark.django_db
def test_absent_student_subject_is_pending(world_a) -> None:
    school, year = world_a["school"], world_a["year"]
    students, subject = _grade(world_a)
    exam = ExamName.objects.create(school=school, label="Quarterly Exam", display_order=1)
    ta = _common_test(school, world_a["section_a"], subject, exam, name="Quarterly Exam")
    tb = _common_test(school, world_a["section_b"], subject, exam, name="Quarterly Exam")
    _score(school, ta, students["a1"], 0, absent=True)  # the student we query
    _score(school, ta, students["a2"], 25)
    _score(school, tb, students["b1"], 50)
    _score(school, tb, students["b2"], 30)

    prof = _profile(school, students["a1"], year)
    assert prof["subjects"] == []
    assert prof["pending_subjects"] == ["Mathematics"]


@pytest.mark.django_db
def test_no_enrollment_yields_empty_profile(world_a) -> None:
    school, year = world_a["school"], world_a["year"]
    orphan = StudentFactory(school=school)  # never enrolled
    prof = _profile(school, orphan, year)
    assert prof["subjects"] == []
    assert prof["section_count"] == 0
    assert prof["overall_percentile"] is None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_admin_endpoint_returns_camelcase_radar(client: Client, admin_token_a, world_a) -> None:
    school, year = world_a["school"], world_a["year"]
    _set_current_year(school, year)
    students, subject = _grade(world_a)
    exam = ExamName.objects.create(school=school, label="Quarterly Exam", display_order=1)
    ta = _common_test(school, world_a["section_a"], subject, exam, name="Quarterly Exam")
    tb = _common_test(school, world_a["section_b"], subject, exam, name="Quarterly Exam")
    _score(school, ta, students["a1"], 45)
    _score(school, ta, students["a2"], 25)
    _score(school, tb, students["b1"], 50)
    _score(school, tb, students["b2"], 30)

    res = client.get(f"/api/v1/students/{students['a1'].id}/strengths", **_auth(admin_token_a))
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["className"] == "Class 6"
    assert body["cohortSize"] == 4
    assert body["overallPercentile"] == 67
    assert body["pendingSubjects"] == []
    axis = body["subjects"][0]
    assert axis["subject"] == "Mathematics"
    assert axis["percentile"] == 67
    assert axis["avgPercent"] == 90
    assert axis["testCount"] == 1


@pytest.mark.django_db
def test_teacher_endpoint_enforces_assignment(client: Client, teacher_token_a, world_a) -> None:
    school, year = world_a["school"], world_a["year"]
    _set_current_year(school, year)
    students, subject = _grade(world_a)
    exam = ExamName.objects.create(school=school, label="Quarterly Exam", display_order=1)
    ta = _common_test(school, world_a["section_a"], subject, exam, name="Quarterly Exam")
    tb = _common_test(school, world_a["section_b"], subject, exam, name="Quarterly Exam")
    _score(school, ta, students["a1"], 45)
    _score(school, ta, students["a2"], 25)
    _score(school, tb, students["b1"], 50)
    _score(school, tb, students["b2"], 30)

    # The teacher is assigned to section A only.
    teacher = TeacherFactory(school=school, user=world_a["teacher_user"])
    TeacherAssignment.objects.create(
        school=school, teacher=teacher, subject=subject,
        section=world_a["section_a"], academic_year=year,
    )

    ok = client.get(
        f"/api/v1/teacher/students/{students['a1'].id}/strengths", **_auth(teacher_token_a)
    )
    assert ok.status_code == 200, ok.content
    assert ok.json()["subjects"][0]["percentile"] == 67

    # A student in section B (not the teacher's) is invisible — 404, no leak.
    denied = client.get(
        f"/api/v1/teacher/students/{students['b1'].id}/strengths", **_auth(teacher_token_a)
    )
    assert denied.status_code == 404
