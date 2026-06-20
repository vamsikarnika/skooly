"""HTTP tests for the parent app online-tests endpoints — list / start /
autosave / submit / result. Covers MCQ + short-answer auto-grading, resume
behaviour, deadline enforcement, and the no-correct-answer-leak guarantee."""

from __future__ import annotations

from datetime import date

import pytest
from django.test import Client
from django.utils import timezone

from apps.academics.models import StudentEnrollment
from apps.accounts.models import Role, User
from apps.accounts.services import issue_tokens_for_user
from apps.exams.models import (
    MCQOption,
    Question,
    QuestionType,
    SubmissionAnswer,
    SubmissionStatus,
    Test,
    TestMode,
    TestScore,
    TestSubmission,
    TestType,
)
from apps.people.models import Parent, ParentStudent
from apps.people.tests.factories import StudentFactory


def _auth(user: User) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_tokens_for_user(user)['access_token']}"}


def _parent_with_child(world: dict, phone: str = "+919876512345"):
    school, year, section = world["school"], world["year"], world["section_a"]
    student = StudentFactory(school=school, first_name="Aarav", last_name="Reddy")
    StudentEnrollment.objects.create(
        school=school, student=student, section=section, academic_year=year,
        roll_number="14", enrollment_date=date(2025, 6, 1), status="active",
    )
    school.current_academic_year = year
    school.save(update_fields=["current_academic_year"])
    user = User.objects.create(
        phone=phone, role=Role.PARENT, school=school, first_name="Suresh", last_name="Reddy"
    )
    user.set_unusable_password()
    user.save()
    parent = Parent.objects.create(school=school, user=user, name="Suresh Reddy", phone=phone)
    ParentStudent.objects.create(school=school, parent=parent, student=student)
    return user, student


def _make_online_test(
    world, *, name="Quiz", duration_min=20, deadline_in_hours=24, available_from_in_hours=-1
):
    from apps.academics.models import Subject
    school, section = world["school"], world["section_a"]
    subject, _ = Subject.objects.all_tenants().get_or_create(school=school, name="Mathematics")
    return Test.objects.create(
        school=school, section=section, subject=subject, name=name,
        test_type=TestType.OTHER, mode=TestMode.ONLINE,
        test_date=timezone.now().date(),
        available_from=timezone.now() + timezone.timedelta(hours=available_from_in_hours),
        available_until=timezone.now() + timezone.timedelta(hours=deadline_in_hours),
        duration_min=duration_min, max_marks=2,
        published_at=timezone.now(),
    )


def _add_mcq(test, *, text="Q?", correct_idx=0, options=("A", "B", "C", "D")):
    school = test.school
    next_order = test.questions.count()
    q = Question.objects.create(
        school=school, test=test, question_type=QuestionType.MCQ,
        text=text, marks=1, display_order=next_order,
    )
    for i, opt in enumerate(options):
        MCQOption.objects.create(
            question=q, text=opt, is_correct=(i == correct_idx), display_order=i,
        )
    return q


def _add_short(test, *, text="Capital of India?", correct="Delhi"):
    school = test.school
    next_order = test.questions.count()
    return Question.objects.create(
        school=school, test=test, question_type=QuestionType.SHORT_ANSWER,
        text=text, marks=1, display_order=next_order,
        correct_answer=correct,
    )


# --- list ------------------------------------------------------------------

@pytest.mark.django_db
def test_list_groups_pending_vs_completed(client: Client, world_a) -> None:
    user, student = _parent_with_child(world_a)
    pending = _make_online_test(world_a, name="Pending quiz")
    _add_mcq(pending)
    completed = _make_online_test(world_a, name="Completed quiz")
    _add_mcq(completed)
    # Pre-submit one.
    TestSubmission.objects.create(
        school=world_a["school"], test=completed, student=student,
        status=SubmissionStatus.SUBMITTED, submitted_at=timezone.now(),
        total_marks=1, max_marks=1,
    )

    res = client.get(f"/api/v1/parent/children/{student.id}/online-tests", **_auth(user))
    assert res.status_code == 200, res.content
    by_status = {t["title"]: t for t in res.json()}
    assert by_status["Pending quiz"]["status"] == "pending"
    assert by_status["Pending quiz"]["score"] is None
    # Scheduled start is exposed so the app can gate the Start button.
    assert by_status["Pending quiz"]["availableFrom"] is not None
    assert by_status["Completed quiz"]["status"] == "completed"
    assert by_status["Completed quiz"]["score"] == 1
    # The completed test exposes the submitted-at timestamp.
    assert by_status["Completed quiz"]["completedDate"] is not None


# --- start -----------------------------------------------------------------

@pytest.mark.django_db
def test_start_creates_submission_and_strips_correct_signals(client: Client, world_a) -> None:
    """The start payload must not leak which option is correct."""
    user, student = _parent_with_child(world_a)
    test = _make_online_test(world_a)
    _add_mcq(test, text="Pick A", correct_idx=0)

    res = client.post(
        f"/api/v1/parent/children/{student.id}/online-tests/{test.id}/start",
        content_type="application/json", **_auth(user),
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["secondsRemaining"] > 0
    q = body["questions"][0]
    assert q["options"][0].keys() == {"id", "text"}  # no is_correct field
    assert "correctAnswer" not in q
    # Submission row exists. Use all_tenants — assertions outside the request
    # context don't have school pinned for the default tenant manager.
    assert TestSubmission.objects.all_tenants().filter(test=test, student=student).count() == 1


@pytest.mark.django_db
def test_start_is_idempotent_and_resumes(client: Client, world_a) -> None:
    user, student = _parent_with_child(world_a)
    test = _make_online_test(world_a)
    q = _add_mcq(test)
    # Hit start twice.
    r1 = client.post(
        f"/api/v1/parent/children/{student.id}/online-tests/{test.id}/start",
        content_type="application/json", **_auth(user),
    )
    sub_id = r1.json()["submissionId"]
    # Save an answer.
    pick = q.options.order_by("display_order").first()
    client.patch(
        f"/api/v1/parent/children/{student.id}/submissions/{sub_id}/answer",
        data={"questionId": q.id, "optionId": pick.id},
        content_type="application/json", **_auth(user),
    )
    r2 = client.post(
        f"/api/v1/parent/children/{student.id}/online-tests/{test.id}/start",
        content_type="application/json", **_auth(user),
    )
    assert r2.json()["submissionId"] == sub_id
    # The saved option echoes back as the resume cue.
    assert r2.json()["questions"][0]["selectedOptionId"] == pick.id


@pytest.mark.django_db
def test_start_rejects_before_open(client: Client, world_a) -> None:
    user, student = _parent_with_child(world_a)
    test = _make_online_test(world_a, available_from_in_hours=2, deadline_in_hours=24)
    _add_mcq(test)
    res = client.post(
        f"/api/v1/parent/children/{student.id}/online-tests/{test.id}/start",
        content_type="application/json", **_auth(user),
    )
    assert res.status_code == 409
    body = res.json()
    assert body["error"]["code"] == "TEST_NOT_OPEN"
    assert "opens on" in body["error"]["message"]


@pytest.mark.django_db
def test_start_rejects_past_deadline(client: Client, world_a) -> None:
    user, student = _parent_with_child(world_a)
    test = _make_online_test(world_a, available_from_in_hours=-2, deadline_in_hours=-1)
    _add_mcq(test)
    res = client.post(
        f"/api/v1/parent/children/{student.id}/online-tests/{test.id}/start",
        content_type="application/json", **_auth(user),
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "TEST_CLOSED"


@pytest.mark.django_db
def test_start_rejects_already_submitted(client: Client, world_a) -> None:
    user, student = _parent_with_child(world_a)
    test = _make_online_test(world_a)
    _add_mcq(test)
    TestSubmission.objects.create(
        school=world_a["school"], test=test, student=student,
        status=SubmissionStatus.SUBMITTED, submitted_at=timezone.now(),
        total_marks=1, max_marks=1,
    )
    res = client.post(
        f"/api/v1/parent/children/{student.id}/online-tests/{test.id}/start",
        content_type="application/json", **_auth(user),
    )
    assert res.status_code == 409


# --- autosave + submit + grading -------------------------------------------

@pytest.mark.django_db
def test_submit_grades_mcq_and_short_answer_correctly(client: Client, world_a) -> None:
    """End-to-end: start → answer two MCQ + one short → submit → graded."""
    user, student = _parent_with_child(world_a)
    test = _make_online_test(world_a)
    test.max_marks = 3
    test.save(update_fields=["max_marks"])
    q_correct = _add_mcq(test, text="MCQ correct", correct_idx=0)
    q_wrong = _add_mcq(test, text="MCQ wrong", correct_idx=0)
    q_short = _add_short(test, text="Capital of France?", correct="Paris")

    start = client.post(
        f"/api/v1/parent/children/{student.id}/online-tests/{test.id}/start",
        content_type="application/json", **_auth(user),
    )
    sub_id = start.json()["submissionId"]

    # Save: pick correct on first, wrong on second, "paris" (lowercase) on short.
    correct_opt = q_correct.options.filter(is_correct=True).first()
    wrong_opt = q_wrong.options.filter(is_correct=False).first()
    for payload in [
        {"questionId": q_correct.id, "optionId": correct_opt.id},
        {"questionId": q_wrong.id, "optionId": wrong_opt.id},
        {"questionId": q_short.id, "textAnswer": "paris"},  # case-insensitive
    ]:
        r = client.patch(
            f"/api/v1/parent/children/{student.id}/submissions/{sub_id}/answer",
            data=payload, content_type="application/json", **_auth(user),
        )
        assert r.status_code == 200, r.content

    res = client.post(
        f"/api/v1/parent/children/{student.id}/submissions/{sub_id}/submit",
        content_type="application/json", **_auth(user),
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["totalMarks"] == 2  # MCQ correct + short
    assert body["maxMarks"] == 3
    # The result payload reveals correctness so the review screen can render it.
    by_id = {q["id"]: q for q in body["questions"]}
    assert by_id[q_correct.id]["isCorrect"] is True
    assert by_id[q_wrong.id]["isCorrect"] is False
    assert by_id[q_short.id]["isCorrect"] is True
    # TestScore mirror exists so teacher reports keep working.
    assert TestScore.objects.all_tenants().filter(test=test, student=student).exists()


@pytest.mark.django_db
def test_submit_is_idempotent(client: Client, world_a) -> None:
    user, student = _parent_with_child(world_a)
    test = _make_online_test(world_a)
    _add_mcq(test)
    start = client.post(
        f"/api/v1/parent/children/{student.id}/online-tests/{test.id}/start",
        content_type="application/json", **_auth(user),
    )
    sub_id = start.json()["submissionId"]
    client.post(
        f"/api/v1/parent/children/{student.id}/submissions/{sub_id}/submit",
        content_type="application/json", **_auth(user),
    )
    # Submit again — should not error, returns the same result payload.
    res2 = client.post(
        f"/api/v1/parent/children/{student.id}/submissions/{sub_id}/submit",
        content_type="application/json", **_auth(user),
    )
    assert res2.status_code == 200
    # Still exactly one submission row.
    assert TestSubmission.objects.all_tenants().filter(test=test, student=student).count() == 1


# --- result ----------------------------------------------------------------

@pytest.mark.django_db
def test_result_returns_404_until_submitted(client: Client, world_a) -> None:
    user, student = _parent_with_child(world_a)
    test = _make_online_test(world_a)
    _add_mcq(test)
    # No submission yet.
    r = client.get(
        f"/api/v1/parent/children/{student.id}/online-tests/{test.id}/result",
        **_auth(user),
    )
    assert r.status_code == 404


# --- cross-tenant + unlinked ----------------------------------------------

@pytest.mark.django_db
def test_cross_tenant_start_404(client: Client, world_a, world_b) -> None:
    user_a, _ = _parent_with_child(world_a, phone="+919876512345")
    _, _ = _parent_with_child(world_b, phone="+919876599999")
    test_b = _make_online_test(world_b)
    _add_mcq(test_b)
    r = client.post(
        f"/api/v1/parent/children/9999/online-tests/{test_b.id}/start",
        content_type="application/json", **_auth(user_a),
    )
    assert r.status_code == 404


@pytest.mark.django_db
def test_autosave_rejected_after_submit(client: Client, world_a) -> None:
    """Once a submission is finalised, autosave returns 422 and the existing
    graded answer is not overwritten."""
    user, student = _parent_with_child(world_a)
    test = _make_online_test(world_a)
    q = _add_mcq(test, correct_idx=0)
    start = client.post(
        f"/api/v1/parent/children/{student.id}/online-tests/{test.id}/start",
        content_type="application/json", **_auth(user),
    )
    sub_id = start.json()["submissionId"]
    # Save the correct answer, then submit (so the graded row exists).
    correct_opt = q.options.filter(is_correct=True).first()
    wrong_opt = q.options.filter(is_correct=False).first()
    client.patch(
        f"/api/v1/parent/children/{student.id}/submissions/{sub_id}/answer",
        data={"questionId": q.id, "optionId": correct_opt.id},
        content_type="application/json", **_auth(user),
    )
    client.post(
        f"/api/v1/parent/children/{student.id}/submissions/{sub_id}/submit",
        content_type="application/json", **_auth(user),
    )
    # Attempt to autosave a different answer post-submit.
    r = client.patch(
        f"/api/v1/parent/children/{student.id}/submissions/{sub_id}/answer",
        data={"questionId": q.id, "optionId": wrong_opt.id},
        content_type="application/json", **_auth(user),
    )
    assert r.status_code == 422
    # The graded answer is untouched.
    answer = SubmissionAnswer.objects.all_tenants().get(submission_id=sub_id, question=q)
    assert answer.selected_option_id == correct_opt.id
    assert answer.is_correct is True
