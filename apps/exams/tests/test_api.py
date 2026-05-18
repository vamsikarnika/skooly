"""Read-side test endpoint tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.academics.models import StudentEnrollment
from apps.academics.tests.factories import SubjectFactory
from apps.exams.models import Test, TestScore, TestType
from apps.people.tests.factories import StudentFactory


def _enroll(world, student):
    StudentEnrollment.objects.create(
        school=world["school"],
        student=student,
        section=world["section_a"],
        academic_year=world["year"],
        roll_number="01",
        enrollment_date=date(2025, 6, 1),
        status="active",
    )


def _make_test(world, *, name="Test", max_marks=50, published=True, subject_name="Mathematics"):
    from apps.academics.models import Subject

    subject = Subject.objects.all_tenants().filter(school=world["school"], name=subject_name).first()
    if subject is None:
        subject = Subject.objects.create(school=world["school"], name=subject_name)
    test = Test.objects.create(
        school=world["school"],
        section=world["section_a"],
        subject=subject,
        name=name,
        test_type=TestType.FA1,
        test_date=date(2026, 5, 1),
        max_marks=max_marks,
        published_at=timezone.now() if published else None,
    )
    return test, subject


@pytest.mark.django_db
def test_list_tests_only_returns_published(client, admin_token_a, world_a):
    _make_test(world_a, name="Published", published=True)
    _make_test(world_a, name="Draft", published=False)
    res = client.get("/api/v1/tests", HTTP_AUTHORIZATION=f"Bearer {admin_token_a}")
    assert res.status_code == 200
    names = {t["name"] for t in res.json()["items"]}
    assert names == {"Published"}


@pytest.mark.django_db
def test_test_detail_stats(client, admin_token_a, world_a):
    test, _ = _make_test(world_a, max_marks=50)
    s1 = StudentFactory(school=world_a["school"], admission_number="T1")
    s2 = StudentFactory(school=world_a["school"], admission_number="T2")
    s3 = StudentFactory(school=world_a["school"], admission_number="T3")
    s4 = StudentFactory(school=world_a["school"], admission_number="T4")
    for s in (s1, s2, s3, s4):
        _enroll(world_a, s)

    TestScore.objects.create(
        school=world_a["school"], test=test, student=s1, marks_obtained=Decimal("40.00")
    )
    TestScore.objects.create(
        school=world_a["school"], test=test, student=s2, marks_obtained=Decimal("30.00")
    )
    TestScore.objects.create(
        school=world_a["school"], test=test, student=s3, marks_obtained=Decimal("50.00")
    )
    TestScore.objects.create(
        school=world_a["school"], test=test, student=s4, is_absent=True, marks_obtained=None
    )

    res = client.get(f"/api/v1/tests/{test.id}", HTTP_AUTHORIZATION=f"Bearer {admin_token_a}")
    assert res.status_code == 200, res.content
    body = res.json()
    stats = body["stats"]
    assert stats["scoredCount"] == 3
    assert stats["absentCount"] == 1
    assert stats["studentCount"] == 4
    assert stats["average"] == 40.0  # (40 + 30 + 50) / 3
    assert Decimal(stats["maxMarksScored"]) == Decimal("50.00")
    assert Decimal(stats["minMarksScored"]) == Decimal("30.00")


@pytest.mark.django_db
def test_test_detail_includes_unscored_students(client, admin_token_a, world_a):
    """Roster shows every active student, with null marks for unscored ones."""
    test, _ = _make_test(world_a)
    s1 = StudentFactory(school=world_a["school"], admission_number="U1")
    s2 = StudentFactory(school=world_a["school"], admission_number="U2")
    _enroll(world_a, s1)
    _enroll(world_a, s2)
    TestScore.objects.create(
        school=world_a["school"], test=test, student=s1, marks_obtained=Decimal("45.00")
    )

    res = client.get(f"/api/v1/tests/{test.id}", HTTP_AUTHORIZATION=f"Bearer {admin_token_a}")
    body = res.json()
    rows = {row["studentId"]: row for row in body["scores"]}
    assert rows[s1.id]["marks"] is not None
    assert rows[s2.id]["marks"] is None
    assert rows[s2.id]["isAbsent"] is False


@pytest.mark.django_db
def test_draft_test_detail_returns_404(client, admin_token_a, world_a):
    test, _ = _make_test(world_a, published=False)
    res = client.get(f"/api/v1/tests/{test.id}", HTTP_AUTHORIZATION=f"Bearer {admin_token_a}")
    assert res.status_code == 404


@pytest.mark.django_db
def test_tests_cross_tenant_isolated(client, admin_token_a, world_b):
    """A's admin should not see B's tests."""
    foreign_subject = SubjectFactory(school=world_b["school"], name="English")
    Test.objects.create(
        school=world_b["school"],
        section=world_b["section_a"],
        subject=foreign_subject,
        name="School B test",
        test_type=TestType.FA1,
        test_date=date(2026, 5, 1),
        max_marks=50,
        published_at=timezone.now(),
    )
    res = client.get("/api/v1/tests", HTTP_AUTHORIZATION=f"Bearer {admin_token_a}")
    assert res.status_code == 200
    names = {t["name"] for t in res.json()["items"]}
    assert "School B test" not in names


@pytest.mark.django_db
def test_section_tests_filtering(client, admin_token_a, world_a):
    """GET /sections/{id}/tests returns only that section's published tests."""
    _make_test(world_a, name="In section A")
    # Create a test in section B
    subject = SubjectFactory(school=world_a["school"], name="Hindi")
    Test.objects.create(
        school=world_a["school"],
        section=world_a["section_b"],
        subject=subject,
        name="In section B",
        test_type=TestType.FA1,
        test_date=date(2026, 5, 2),
        max_marks=50,
        published_at=timezone.now(),
    )
    res = client.get(
        f"/api/v1/sections/{world_a['section_a'].id}/tests",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    names = {t["name"] for t in res.json()}
    assert "In section A" in names
    assert "In section B" not in names


@pytest.mark.django_db
def test_section_tests_cross_tenant_404(client, admin_token_a, world_b):
    res = client.get(
        f"/api/v1/sections/{world_b['section_a'].id}/tests",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_student_scores_history(client, admin_token_a, world_a):
    student = StudentFactory(school=world_a["school"], admission_number="H1")
    _enroll(world_a, student)

    subject = SubjectFactory(school=world_a["school"], name="Mathematics")
    test1 = Test.objects.create(
        school=world_a["school"],
        section=world_a["section_a"],
        subject=subject,
        name="FA1 Math",
        test_type=TestType.FA1,
        test_date=date(2026, 4, 1),
        max_marks=50,
        published_at=timezone.now(),
    )
    test2 = Test.objects.create(
        school=world_a["school"],
        section=world_a["section_a"],
        subject=subject,
        name="FA2 Math",
        test_type=TestType.FA2,
        test_date=date(2026, 5, 1),
        max_marks=50,
        published_at=timezone.now(),
    )
    # Draft test should NOT appear.
    Test.objects.create(
        school=world_a["school"],
        section=world_a["section_a"],
        subject=subject,
        name="Draft Math",
        test_type=TestType.FA3,
        test_date=date(2026, 5, 10),
        max_marks=50,
        published_at=None,
    )
    TestScore.objects.create(
        school=world_a["school"], test=test1, student=student, marks_obtained=Decimal("40.00")
    )
    TestScore.objects.create(
        school=world_a["school"], test=test2, student=student, marks_obtained=Decimal("30.00")
    )

    res = client.get(
        f"/api/v1/students/{student.id}/scores",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    body = res.json()
    assert len(body["bySubject"]) == 1  # only Mathematics
    math = body["bySubject"][0]
    assert math["subjectName"] == "Mathematics"
    assert len(math["tests"]) == 2  # draft excluded
    # 40/50 = 80%, 30/50 = 60% → avg 70%
    assert math["averagePercent"] == 70.0
    assert {t["testName"] for t in math["tests"]} == {"FA1 Math", "FA2 Math"}


@pytest.mark.django_db
def test_student_scores_absent_excluded_from_average(client, admin_token_a, world_a):
    student = StudentFactory(school=world_a["school"], admission_number="ABS1")
    _enroll(world_a, student)
    subject = SubjectFactory(school=world_a["school"], name="Science")
    t = Test.objects.create(
        school=world_a["school"],
        section=world_a["section_a"],
        subject=subject,
        name="T1",
        test_type=TestType.FA1,
        test_date=date(2026, 5, 1),
        max_marks=50,
        published_at=timezone.now(),
    )
    t2 = Test.objects.create(
        school=world_a["school"],
        section=world_a["section_a"],
        subject=subject,
        name="T2",
        test_type=TestType.FA2,
        test_date=date(2026, 5, 8),
        max_marks=50,
        published_at=timezone.now(),
    )
    TestScore.objects.create(
        school=world_a["school"], test=t, student=student, marks_obtained=Decimal("45.00")
    )
    TestScore.objects.create(
        school=world_a["school"], test=t2, student=student, is_absent=True, marks_obtained=None
    )

    res = client.get(
        f"/api/v1/students/{student.id}/scores",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    science = res.json()["bySubject"][0]
    # Avg only over the scored test: 45/50 = 90%
    assert science["averagePercent"] == 90.0


@pytest.mark.django_db
def test_student_scores_cross_tenant_404(client, admin_token_a, world_b):
    foreign = StudentFactory(school=world_b["school"], admission_number="F1")
    res = client.get(
        f"/api/v1/students/{foreign.id}/scores",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_tests_requires_auth(client):
    res = client.get("/api/v1/tests")
    assert res.status_code == 401
