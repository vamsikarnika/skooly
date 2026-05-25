"""HTTP-layer tests for teacher tests & scores endpoints.

Tests cover:
- list tests (empty, with data, status filter)
- create test
- get test detail
- get marks roster
- save marks (draft + publish)
- get report
- cross-tenant isolation (404 on another school's tests)
- admin token rejected (401)
- wrong teacher (not assigned to section → 404)
"""

from __future__ import annotations

from datetime import UTC, date, timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.academics.models import StudentEnrollment, TeacherAssignment
from apps.academics.tests.factories import SubjectFactory
from apps.accounts.services import issue_tokens_for_user
from apps.exams.models import Question, Test, TestScore
from apps.exams.tests.factories import TestFactory, TestScoreFactory
from apps.people.tests.factories import StudentFactory, TeacherFactory


def _auth(user) -> dict:  # type: ignore[no-untyped-def]
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_tokens_for_user(user)['access_token']}"}


def _setup(world: dict):  # type: ignore[no-untyped-def]
    """Create teacher + subject + assignment in section_a for world."""
    school = world["school"]
    year = world["year"]
    section = world["section_a"]
    teacher = TeacherFactory(school=school, user=world["teacher_user"])
    subject = SubjectFactory(school=school, name="Science")
    TeacherAssignment.objects.create(
        school=school, teacher=teacher, subject=subject, section=section, academic_year=year
    )
    school.current_academic_year = year
    school.save(update_fields=["current_academic_year"])
    return teacher, subject, section


def _enroll(world: dict, section, roll: int = 1) -> object:  # type: ignore[no-untyped-def]
    school, year = world["school"], world["year"]
    student = StudentFactory(school=school)
    StudentEnrollment.objects.create(
        school=school, student=student, section=section, academic_year=year,
        roll_number=str(roll), enrollment_date=date(2025, 6, 1), status="active",
    )
    return student


def _make_test(world: dict, teacher, section, subject, *, test_date=None, published=False) -> Test:  # type: ignore[no-untyped-def]
    td = test_date or (date.today() - timedelta(days=1))
    return TestFactory(
        school=world["school"],
        section=section,
        subject=subject,
        created_by=teacher,
        test_date=td,
        max_marks=50,
        published_at=timezone.now() if published else None,
    )


# ---------------------------------------------------------------------------
# GET /teacher/tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_list_tests_empty(client: Client, world_a) -> None:
    _setup(world_a)
    res = client.get("/api/v1/teacher/tests", **_auth(world_a["teacher_user"]))
    assert res.status_code == 200
    assert res.json() == []


@pytest.mark.django_db
def test_list_tests_returns_own_tests(client: Client, world_a) -> None:
    teacher, subject, section = _setup(world_a)
    _make_test(world_a, teacher, section, subject)
    res = client.get("/api/v1/teacher/tests", **_auth(world_a["teacher_user"]))
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    t = body[0]
    assert t["subject"] == "Science"
    assert t["classLabel"] == "Class 6 — A"
    assert t["classId"] == str(section.id)
    assert "id" in t
    assert t["maxMarks"] == 50


@pytest.mark.django_db
def test_list_tests_status_filter(client: Client, world_a) -> None:
    teacher, subject, section = _setup(world_a)
    _make_test(world_a, teacher, section, subject, published=True)
    _make_test(world_a, teacher, section, subject, test_date=date.today() - timedelta(days=1))

    published = client.get(
        "/api/v1/teacher/tests?status=published", **_auth(world_a["teacher_user"])
    ).json()
    assert len(published) == 1
    assert published[0]["status"] == "published"

    grading = client.get(
        "/api/v1/teacher/tests?status=grading", **_auth(world_a["teacher_user"])
    ).json()
    assert len(grading) == 1
    assert grading[0]["status"] == "grading"


@pytest.mark.django_db
def test_list_tests_scheduled_status(client: Client, world_a) -> None:
    teacher, subject, section = _setup(world_a)
    future = date.today() + timedelta(days=7)
    _make_test(world_a, teacher, section, subject, test_date=future)
    res = client.get("/api/v1/teacher/tests", **_auth(world_a["teacher_user"]))
    assert res.status_code == 200
    assert res.json()[0]["status"] == "scheduled"


@pytest.mark.django_db
def test_list_tests_does_not_return_other_section_tests(client: Client, world_a) -> None:
    """Tests for unassigned sections should not appear."""
    teacher, subject, _ = _setup(world_a)
    section_b = world_a["section_b"]
    other_subject = SubjectFactory(school=world_a["school"], name="Math")
    # Create test in section_b (teacher not assigned there)
    TestFactory(
        school=world_a["school"],
        section=section_b,
        subject=other_subject,
        created_by=teacher,
        test_date=date.today(),
        max_marks=30,
        published_at=None,
    )
    res = client.get("/api/v1/teacher/tests", **_auth(world_a["teacher_user"]))
    assert res.json() == []


@pytest.mark.django_db
def test_list_tests_admin_token_rejected(client: Client, world_a) -> None:
    _setup(world_a)
    res = client.get("/api/v1/teacher/tests", **_auth(world_a["admin"]))
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# POST /teacher/tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_test_success(client: Client, world_a) -> None:
    _, _, section = _setup(world_a)
    payload = {
        "sectionId": section.id,
        "name": "Chapter 3 Test",
        "testType": "FA1",
        "testDate": date.today().isoformat(),
        "maxMarks": 25,
    }
    res = client.post(
        "/api/v1/teacher/tests",
        data=payload,
        content_type="application/json",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "Chapter 3 Test"
    assert body["maxMarks"] == 25
    assert body["classId"] == str(section.id)
    assert body["subject"] == "Science"
    assert Test.objects.all_tenants().filter(school=world_a["school"], name="Chapter 3 Test").exists()


@pytest.mark.django_db
def test_create_test_unassigned_section_raises_404(client: Client, world_a) -> None:
    _setup(world_a)
    res = client.post(
        "/api/v1/teacher/tests",
        data={
            "sectionId": world_a["section_b"].id,
            "name": "Sneaky Test",
            "testType": "OTHER",
            "testDate": date.today().isoformat(),
            "maxMarks": 20,
        },
        content_type="application/json",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# GET /teacher/tests/{test_id}
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_get_test_detail(client: Client, world_a) -> None:
    teacher, subject, section = _setup(world_a)
    test = _make_test(world_a, teacher, section, subject)
    res = client.get(
        f"/api/v1/teacher/tests/{test.id}", **_auth(world_a["teacher_user"])
    )
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == str(test.id)
    assert body["maxMarks"] == 50


@pytest.mark.django_db
def test_get_test_detail_404_wrong_teacher(client: Client, world_a) -> None:
    """Teacher B can't see Teacher A's test even in same school."""
    teacher, subject, section = _setup(world_a)
    test = _make_test(world_a, teacher, section, subject)

    # Create a second teacher with NO assignments
    other_user = __import__(
        "apps.accounts.tests.factories", fromlist=["UserFactory"]
    ).UserFactory(school=world_a["school"], phone="+919999000001", role="teacher")
    TeacherFactory(school=world_a["school"], user=other_user)

    res = client.get(
        f"/api/v1/teacher/tests/{test.id}", **_auth(other_user)
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# GET /teacher/tests/{test_id}/marks
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_get_marks_roster_no_scores(client: Client, world_a) -> None:
    teacher, subject, section = _setup(world_a)
    _enroll(world_a, section, roll=1)
    _enroll(world_a, section, roll=2)
    test = _make_test(world_a, teacher, section, subject)
    res = client.get(
        f"/api/v1/teacher/tests/{test.id}/marks", **_auth(world_a["teacher_user"])
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 2
    for row in body:
        assert row["marksObtained"] is None
        assert row["isAbsent"] is False


@pytest.mark.django_db
def test_get_marks_roster_with_existing_scores(client: Client, world_a) -> None:
    teacher, subject, section = _setup(world_a)
    student = _enroll(world_a, section, roll=1)
    test = _make_test(world_a, teacher, section, subject)
    TestScoreFactory(
        school=world_a["school"],
        test=test,
        student=student,
        marks_obtained=35,
        is_absent=False,
    )
    res = client.get(
        f"/api/v1/teacher/tests/{test.id}/marks", **_auth(world_a["teacher_user"])
    )
    assert res.status_code == 200
    row = res.json()[0]
    assert float(row["marksObtained"]) == 35.0


@pytest.mark.django_db
def test_get_marks_roster_absent_student(client: Client, world_a) -> None:
    teacher, subject, section = _setup(world_a)
    student = _enroll(world_a, section, roll=1)
    test = _make_test(world_a, teacher, section, subject)
    TestScoreFactory(
        school=world_a["school"],
        test=test,
        student=student,
        marks_obtained=None,
        is_absent=True,
    )
    res = client.get(
        f"/api/v1/teacher/tests/{test.id}/marks", **_auth(world_a["teacher_user"])
    )
    row = res.json()[0]
    assert row["isAbsent"] is True
    assert row["marksObtained"] is None


# ---------------------------------------------------------------------------
# POST /teacher/tests/{test_id}/marks
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_save_marks_draft(client: Client, world_a) -> None:
    teacher, subject, section = _setup(world_a)
    student = _enroll(world_a, section, roll=1)
    test = _make_test(world_a, teacher, section, subject)
    res = client.post(
        f"/api/v1/teacher/tests/{test.id}/marks",
        data={
            "publish": False,
            "records": [{"studentId": str(student.id), "marksObtained": 42, "isAbsent": False}],
        },
        content_type="application/json",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["saved"] == 1
    assert body["published"] is False
    test.refresh_from_db()
    assert test.published_at is None


@pytest.mark.django_db
def test_save_marks_publish(client: Client, world_a) -> None:
    teacher, subject, section = _setup(world_a)
    student = _enroll(world_a, section, roll=1)
    test = _make_test(world_a, teacher, section, subject)
    res = client.post(
        f"/api/v1/teacher/tests/{test.id}/marks",
        data={
            "publish": True,
            "records": [{"studentId": str(student.id), "marksObtained": 48, "isAbsent": False}],
        },
        content_type="application/json",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 200
    assert res.json()["published"] is True
    test.refresh_from_db()
    assert test.published_at is not None


@pytest.mark.django_db
def test_save_marks_upsert(client: Client, world_a) -> None:
    """Saving marks twice updates, doesn't duplicate."""
    teacher, subject, section = _setup(world_a)
    student = _enroll(world_a, section, roll=1)
    test = _make_test(world_a, teacher, section, subject)
    for marks in [30, 45]:
        client.post(
            f"/api/v1/teacher/tests/{test.id}/marks",
            data={"publish": False, "records": [{"studentId": str(student.id), "marksObtained": marks, "isAbsent": False}]},
            content_type="application/json",
            **_auth(world_a["teacher_user"]),
        )
    scores = TestScore.objects.all_tenants().filter(test=test, student=student)
    assert scores.count() == 1
    assert float(scores.first().marks_obtained) == 45.0


@pytest.mark.django_db
def test_save_marks_absent_clears_marks(client: Client, world_a) -> None:
    teacher, subject, section = _setup(world_a)
    student = _enroll(world_a, section, roll=1)
    test = _make_test(world_a, teacher, section, subject)
    res = client.post(
        f"/api/v1/teacher/tests/{test.id}/marks",
        data={
            "publish": False,
            "records": [{"studentId": str(student.id), "marksObtained": 10, "isAbsent": True}],
        },
        content_type="application/json",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 200
    score = TestScore.objects.all_tenants().get(test=test, student=student)
    assert score.is_absent is True
    assert score.marks_obtained is None


@pytest.mark.django_db
def test_save_marks_on_published_test_raises(client: Client, world_a) -> None:
    teacher, subject, section = _setup(world_a)
    student = _enroll(world_a, section, roll=1)
    test = _make_test(world_a, teacher, section, subject, published=True)
    res = client.post(
        f"/api/v1/teacher/tests/{test.id}/marks",
        data={"publish": False, "records": [{"studentId": str(student.id), "marksObtained": 20, "isAbsent": False}]},
        content_type="application/json",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# GET /teacher/tests/{test_id}/report
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_get_report(client: Client, world_a) -> None:
    teacher, subject, section = _setup(world_a)
    s1 = _enroll(world_a, section, roll=1)
    s2 = _enroll(world_a, section, roll=2)
    test = _make_test(world_a, teacher, section, subject, published=True)
    TestScoreFactory(school=world_a["school"], test=test, student=s1, marks_obtained=45, is_absent=False)
    TestScoreFactory(school=world_a["school"], test=test, student=s2, marks_obtained=30, is_absent=False)

    res = client.get(
        f"/api/v1/teacher/tests/{test.id}/report", **_auth(world_a["teacher_user"])
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 2
    assert body["passed"] == 2          # 45/50=90% and 30/50=60% — both above 35% threshold
    assert body["avg"] > 0
    assert len(body["bands"]) == 4
    assert len(body["students"]) == 2
    # Students sorted by pct descending (45 = 90% first)
    assert body["students"][0]["pct"] == 90


@pytest.mark.django_db
def test_get_report_all_absent(client: Client, world_a) -> None:
    teacher, subject, section = _setup(world_a)
    student = _enroll(world_a, section, roll=1)
    test = _make_test(world_a, teacher, section, subject, published=True)
    TestScoreFactory(school=world_a["school"], test=test, student=student, marks_obtained=None, is_absent=True)
    res = client.get(
        f"/api/v1/teacher/tests/{test.id}/report", **_auth(world_a["teacher_user"])
    )
    assert res.status_code == 200
    body = res.json()
    assert body["avg"] == 0
    assert body["topScore"] is None


# ---------------------------------------------------------------------------
# Cross-tenant isolation
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_cross_tenant_test_404(client: Client, world_a, world_b) -> None:
    """Teacher from school A can't see school B's tests."""
    _setup(world_a)
    teacher_b, subject_b, section_b = _setup(world_b)
    test_b = _make_test(world_b, teacher_b, section_b, subject_b)

    res = client.get(
        f"/api/v1/teacher/tests/{test_b.id}", **_auth(world_a["teacher_user"])
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_cross_tenant_marks_save_404(client: Client, world_a, world_b) -> None:
    """Teacher from school A can't save marks on school B's test."""
    _setup(world_a)
    teacher_b, subject_b, section_b = _setup(world_b)
    test_b = _make_test(world_b, teacher_b, section_b, subject_b)

    res = client.post(
        f"/api/v1/teacher/tests/{test_b.id}/marks",
        data={"publish": False, "records": []},
        content_type="application/json",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Online test helpers
# ---------------------------------------------------------------------------

def _make_online_test(
    world: dict, teacher, section, subject, *, published: bool = False
) -> Test:
    from datetime import datetime
    now = datetime.now(tz=UTC)
    avail_from = now.replace(hour=8, minute=0, second=0, microsecond=0)
    avail_until = avail_from.replace(hour=18)
    t = TestFactory(
        school=world["school"],
        section=section,
        subject=subject,
        created_by=teacher,
        test_date=date.today(),
        max_marks=None,
        mode="online",
        available_from=avail_from,
        available_until=avail_until,
        duration_min=30,
        published_at=now if published else None,
    )
    return t


_MCQ_PAYLOAD = {
    "questionType": "mcq",
    "text": "What is 2 + 2?",
    "marks": 2,
    "displayOrder": 0,
    "difficulty": "easy",
    "topic": "Arithmetic",
    "options": [
        {"text": "3", "isCorrect": False, "displayOrder": 0},
        {"text": "4", "isCorrect": True,  "displayOrder": 1},
        {"text": "5", "isCorrect": False, "displayOrder": 2},
        {"text": "6", "isCorrect": False, "displayOrder": 3},
    ],
    "correctAnswer": "",
}

_SHORT_PAYLOAD = {
    "questionType": "short_answer",
    "text": "Capital of India?",
    "marks": 1,
    "displayOrder": 1,
    "difficulty": "easy",
    "topic": "Geography",
    "options": None,
    "correctAnswer": "New Delhi",
}


# ---------------------------------------------------------------------------
# POST /teacher/tests  (online)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_online_test(client: Client, world_a) -> None:
    teacher, subject, section = _setup(world_a)
    from datetime import datetime
    now = datetime.now(tz=UTC)
    res = client.post(
        "/api/v1/teacher/tests",
        data={
            "sectionId": section.id,
            "name": "Chapter 1 Quiz",
            "testType": "OTHER",
            "testDate": date.today().isoformat(),
            "mode": "online",
            "availableFrom": now.isoformat(),
            "availableUntil": now.replace(hour=now.hour + 2).isoformat(),
            "durationMin": 30,
        },
        content_type="application/json",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "online"
    assert data["maxMarks"] == 0
    assert data["durationMin"] == 30


@pytest.mark.django_db
def test_create_online_test_missing_schedule(client: Client, world_a) -> None:
    """Online test without availableFrom/Until → 422."""
    teacher, subject, section = _setup(world_a)
    res = client.post(
        "/api/v1/teacher/tests",
        data={
            "sectionId": section.id,
            "name": "Bad test",
            "testType": "OTHER",
            "testDate": date.today().isoformat(),
            "mode": "online",
        },
        content_type="application/json",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code in (400, 422)


# ---------------------------------------------------------------------------
# GET /teacher/tests/{id}/questions
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_get_questions_empty(client: Client, world_a) -> None:
    teacher, subject, section = _setup(world_a)
    test = _make_online_test(world_a, teacher, section, subject)
    res = client.get(
        f"/api/v1/teacher/tests/{test.id}/questions",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 200
    assert res.json() == []


@pytest.mark.django_db
def test_get_questions_offline_test_rejected(client: Client, world_a) -> None:
    teacher, subject, section = _setup(world_a)
    test = _make_test(world_a, teacher, section, subject)
    res = client.get(
        f"/api/v1/teacher/tests/{test.id}/questions",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 422  # ValidationFailed


# ---------------------------------------------------------------------------
# POST /teacher/tests/{id}/questions
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_save_questions_draft(client: Client, world_a) -> None:
    teacher, subject, section = _setup(world_a)
    test = _make_online_test(world_a, teacher, section, subject)
    res = client.post(
        f"/api/v1/teacher/tests/{test.id}/questions",
        data={"publish": False, "questions": [_MCQ_PAYLOAD, _SHORT_PAYLOAD]},
        content_type="application/json",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["saved"] == 2
    assert data["totalMarks"] == 3  # 2 + 1
    assert data["published"] is False
    test.refresh_from_db()
    assert test.max_marks == 3
    assert test.published_at is None
    assert Question.objects.all_tenants().filter(test=test).count() == 2


@pytest.mark.django_db
def test_save_questions_publish(client: Client, world_a) -> None:
    teacher, subject, section = _setup(world_a)
    test = _make_online_test(world_a, teacher, section, subject)
    res = client.post(
        f"/api/v1/teacher/tests/{test.id}/questions",
        data={"publish": True, "questions": [_MCQ_PAYLOAD]},
        content_type="application/json",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 200
    assert res.json()["published"] is True
    test.refresh_from_db()
    assert test.published_at is not None


@pytest.mark.django_db
def test_save_questions_upsert(client: Client, world_a) -> None:
    """Saving questions twice replaces the first set."""
    teacher, subject, section = _setup(world_a)
    test = _make_online_test(world_a, teacher, section, subject)
    client.post(
        f"/api/v1/teacher/tests/{test.id}/questions",
        data={"publish": False, "questions": [_MCQ_PAYLOAD, _SHORT_PAYLOAD]},
        content_type="application/json",
        **_auth(world_a["teacher_user"]),
    )
    # Save again with only 1 question
    res = client.post(
        f"/api/v1/teacher/tests/{test.id}/questions",
        data={"publish": False, "questions": [_MCQ_PAYLOAD]},
        content_type="application/json",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 200
    assert Question.objects.all_tenants().filter(test=test).count() == 1


@pytest.mark.django_db
def test_save_questions_published_blocked(client: Client, world_a) -> None:
    """Cannot edit questions after publishing."""
    teacher, subject, section = _setup(world_a)
    test = _make_online_test(world_a, teacher, section, subject, published=True)
    res = client.post(
        f"/api/v1/teacher/tests/{test.id}/questions",
        data={"publish": False, "questions": [_MCQ_PAYLOAD]},
        content_type="application/json",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 422  # ValidationFailed


@pytest.mark.django_db
def test_save_questions_invalid_mcq_options(client: Client, world_a) -> None:
    """MCQ with wrong option count → 400."""
    teacher, subject, section = _setup(world_a)
    test = _make_online_test(world_a, teacher, section, subject)
    bad_mcq = {**_MCQ_PAYLOAD, "options": _MCQ_PAYLOAD["options"][:3]}  # only 3
    res = client.post(
        f"/api/v1/teacher/tests/{test.id}/questions",
        data={"publish": False, "questions": [bad_mcq]},
        content_type="application/json",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 422  # ValidationFailed — MCQ requires 4 options


@pytest.mark.django_db
def test_save_questions_roundtrip(client: Client, world_a) -> None:
    """Save then GET returns same questions."""
    teacher, subject, section = _setup(world_a)
    test = _make_online_test(world_a, teacher, section, subject)
    client.post(
        f"/api/v1/teacher/tests/{test.id}/questions",
        data={"publish": False, "questions": [_MCQ_PAYLOAD, _SHORT_PAYLOAD]},
        content_type="application/json",
        **_auth(world_a["teacher_user"]),
    )
    res = client.get(
        f"/api/v1/teacher/tests/{test.id}/questions",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 200
    qs = res.json()
    assert len(qs) == 2
    mcq = next(q for q in qs if q["questionType"] == "mcq")
    assert len(mcq["options"]) == 4
    correct = [o for o in mcq["options"] if o["isCorrect"]]
    assert len(correct) == 1
    short = next(q for q in qs if q["questionType"] == "short_answer")
    assert short["correctAnswer"].lower() == "new delhi"


@pytest.mark.django_db
def test_save_questions_no_difficulty(client: Client, world_a) -> None:
    """Questions without difficulty (omitted or null) must not 500.

    Regression: service used ``q.get("difficulty") or None`` which set
    difficulty=None and hit the NOT NULL DB constraint.  Fixed to ``or ""``.
    """
    teacher, subject, section = _setup(world_a)
    test = _make_online_test(world_a, teacher, section, subject)

    no_diff_mcq = {
        "questionType": "mcq",
        "text": "No difficulty MCQ?",
        "marks": 1,
        "displayOrder": 0,
        "topic": "",
        # difficulty intentionally omitted
        "options": [
            {"text": "A", "isCorrect": True,  "displayOrder": 0},
            {"text": "B", "isCorrect": False, "displayOrder": 1},
            {"text": "C", "isCorrect": False, "displayOrder": 2},
            {"text": "D", "isCorrect": False, "displayOrder": 3},
        ],
        "correctAnswer": "",
    }
    no_diff_short = {
        "questionType": "short_answer",
        "text": "Fill in the blank?",
        "marks": 1,
        "displayOrder": 1,
        "difficulty": None,   # explicitly null
        "topic": "",
        "options": None,
        "correctAnswer": "answer",
    }

    res = client.post(
        f"/api/v1/teacher/tests/{test.id}/questions",
        data={"publish": False, "questions": [no_diff_mcq, no_diff_short]},
        content_type="application/json",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["saved"] == 2
    # Verify difficulty stored as empty string, not None
    qs = Question.objects.all_tenants().filter(test=test)
    assert all(q.difficulty == "" for q in qs)


@pytest.mark.django_db
def test_get_test_detail_online_has_mode(client: Client, world_a) -> None:
    """GET /teacher/tests/{id} for an online test must return mode='online'
    so the frontend can route to the question builder instead of marks entry."""
    teacher, subject, section = _setup(world_a)
    test = _make_online_test(world_a, teacher, section, subject)
    res = client.get(
        f"/api/v1/teacher/tests/{test.id}",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "online"
    assert data["status"] == "draft"
    assert data["availableFrom"] is not None
    assert data["availableUntil"] is not None


@pytest.mark.django_db
def test_get_test_detail_offline_has_mode(client: Client, world_a) -> None:
    """GET /teacher/tests/{id} for an offline test must return mode='offline'."""
    teacher, subject, section = _setup(world_a)
    test = _make_test(world_a, teacher, section, subject)
    res = client.get(
        f"/api/v1/teacher/tests/{test.id}",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "offline"
    assert data["availableFrom"] is None
    assert data["availableUntil"] is None


@pytest.mark.django_db
def test_cross_tenant_questions_404(client: Client, world_a, world_b) -> None:
    _setup(world_a)
    teacher_b, subject_b, section_b = _setup(world_b)
    test_b = _make_online_test(world_b, teacher_b, section_b, subject_b)
    res = client.get(
        f"/api/v1/teacher/tests/{test_b.id}/questions",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 404
