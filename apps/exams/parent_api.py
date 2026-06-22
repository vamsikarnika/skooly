"""Parent app exams endpoints — marks, report cards, and online tests.

- Marks: read-only published offline-test results, with class avg/high/rank
  computed on the fly from the section's scores.
- Report cards: published-only, scoped per child, rendered from data_snapshot.
- Online tests: list / start (resumes) / autosave / submit (auto-graded) /
  result, all scoped to the child's section. Correct answers are never
  leaked while the test is in progress.
"""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.http import HttpRequest
from django.utils import timezone
from ninja import Router

from apps.accounts.parent_auth import get_parent_child, parent_jwt_auth
from apps.core.exceptions import APIError, Conflict, NotFound, ValidationFailed
from apps.core.schemas import CamelSchema
from apps.exams import radar_services
from apps.exams.models import (
    MCQOption,
    Question,
    QuestionType,
    ReportCard,
    SubmissionAnswer,
    SubmissionStatus,
    Test,
    TestMode,
    TestScore,
    TestSubmission,
)
from apps.exams.schemas import StrengthProfileOut

router = Router(tags=["parent-marks"], auth=parent_jwt_auth, by_alias=True)


class TestResultOut(CamelSchema):
    id: int
    title: str
    subject: str
    date: str
    marks: int | None = None
    max_marks: int
    class_avg: int
    class_high: int
    rank: int | None = None
    total_students: int


class TestListOut(CamelSchema):
    tests: list[TestResultOut]


def _current_section(student: Any, school: Any) -> Any:
    year_id = school.current_academic_year_id if school else None
    qs = student.enrollments.filter(status="active").select_related("section")
    enroll = None
    if year_id is not None:
        enroll = qs.filter(academic_year_id=year_id).first()
    enroll = enroll or qs.first()
    return enroll.section if enroll else None


def _result(test: Test, student: Any) -> dict:
    scores = list(TestScore.objects.filter(test=test))
    marks_list = [
        float(s.marks_obtained)
        for s in scores
        if not s.is_absent and s.marks_obtained is not None
    ]
    class_avg = round(sum(marks_list) / len(marks_list)) if marks_list else 0
    class_high = round(max(marks_list)) if marks_list else 0

    mine = next((s for s in scores if s.student_id == student.id), None)
    my_marks = (
        float(mine.marks_obtained)
        if (mine and not mine.is_absent and mine.marks_obtained is not None)
        else None
    )
    rank = (sum(1 for m in marks_list if m > my_marks) + 1) if my_marks is not None else None

    return {
        "id": test.id,
        "title": test.name,
        "subject": test.subject.name,
        "date": test.test_date.isoformat(),
        "marks": round(my_marks) if my_marks is not None else None,
        "max_marks": test.max_marks or 0,
        "class_avg": class_avg,
        "class_high": class_high,
        "rank": rank,
        "total_students": len(scores),
    }


@router.get("/children/{child_id}/tests", response=TestListOut)
def list_tests(request: HttpRequest, child_id: int) -> dict:
    student = get_parent_child(request, child_id)
    school = request.auth.school  # type: ignore[attr-defined]
    section = _current_section(student, school)
    if section is None:
        return {"tests": []}
    tests = (
        Test.objects.filter(
            section=section, mode=TestMode.OFFLINE, published_at__isnull=False
        )
        .select_related("subject")
        .order_by("-test_date", "-id")
    )
    return {"tests": [_result(t, student) for t in tests]}


@router.get("/children/{child_id}/tests/{test_id}", response=TestResultOut)
def get_test(request: HttpRequest, child_id: int, test_id: int) -> dict:
    student = get_parent_child(request, child_id)
    school = request.auth.school  # type: ignore[attr-defined]
    section = _current_section(student, school)
    test = (
        Test.objects.filter(
            id=test_id,
            section=section,
            mode=TestMode.OFFLINE,
            published_at__isnull=False,
        )
        .select_related("subject")
        .first()
    )
    if test is None:
        raise NotFound("No such test for this child.")
    return _result(test, student)


@router.get("/children/{child_id}/strengths", response=StrengthProfileOut)
def child_strengths(request: HttpRequest, child_id: int) -> dict:
    """The child's strength/weakness radar — per-subject percentile against the
    whole grade, built from the common tests every section has published."""
    student = get_parent_child(request, child_id)
    school = request.auth.school  # type: ignore[attr-defined]
    return radar_services.build_strength_profile(
        school=school,
        student=student,
        academic_year_id=school.current_academic_year_id if school else None,
    )


# ---------------------------------------------------------------------------
# Report cards
# ---------------------------------------------------------------------------


class ReportCardSubjectOut(CamelSchema):
    name: str
    max_marks: int
    marks: int
    grade: str


class ReportCardOut(CamelSchema):
    id: int
    term: str
    academic_year: str
    issue_date: str
    subjects: list[ReportCardSubjectOut]
    attendance_pct: int
    teacher_remark: str
    principal_remark: str | None = None
    overall_grade: str
    overall_pct: int
    rank: int | None = None
    total_students: int
    # Branded PDF, only once the admin has published it (optional per school).
    pdf_url: str | None = None


def _serialize_card(card: ReportCard) -> dict:
    """Pull the rendered payload from the immutable snapshot and stamp the id.
    The PDF is surfaced only after the admin publishes it."""
    snap = dict(card.data_snapshot or {})
    snap["id"] = card.id
    snap["pdfUrl"] = card.pdf_url if card.pdf_published_at else None
    return snap


@router.get("/children/{child_id}/report-cards", response=list[ReportCardOut])
def list_report_cards(request: HttpRequest, child_id: int) -> list[dict]:
    student = get_parent_child(request, child_id)
    cards = ReportCard.objects.filter(
        student=student, published_at__isnull=False
    ).order_by("-published_at", "-id")
    return [_serialize_card(c) for c in cards]


@router.get("/children/{child_id}/report-cards/{card_id}", response=ReportCardOut)
def get_report_card(request: HttpRequest, child_id: int, card_id: int) -> dict:
    student = get_parent_child(request, child_id)
    card = ReportCard.objects.filter(
        id=card_id, student=student, published_at__isnull=False
    ).first()
    if card is None:
        raise NotFound("No such report card for this child.")
    return _serialize_card(card)


# ---------------------------------------------------------------------------
# Online tests (parent attempts via the parent app)
# ---------------------------------------------------------------------------


class OnlineTestListItem(CamelSchema):
    id: int
    subject: str
    title: str
    duration_min: int
    available_from: str | None = None  # ISO scheduled start; null = open immediately
    deadline: str | None  # ISO datetime when available_until is set
    max_marks: int
    questions: int
    status: str  # pending | completed
    score: int | None = None
    completed_date: str | None = None


class OptionOut(CamelSchema):
    id: int
    text: str


class QuestionOut(CamelSchema):
    id: int
    question_type: str  # mcq | short_answer
    text: str
    marks: int
    display_order: int
    options: list[OptionOut]
    # Resumed-state fields (echo the saved answer so the take screen shows it).
    selected_option_id: int | None = None
    text_answer: str = ""


class StartResponse(CamelSchema):
    submission_id: int
    test_id: int
    title: str
    subject: str
    duration_min: int
    seconds_remaining: int
    max_marks: int
    questions: list[QuestionOut]


class AnswerRequest(CamelSchema):
    question_id: int
    option_id: int | None = None
    text_answer: str | None = None


class SuccessAck(CamelSchema):
    success: bool


class ResultQuestionOut(CamelSchema):
    id: int
    question_type: str
    text: str
    marks: int
    display_order: int
    options: list[OptionOut]
    # Reveal: which option was correct, which the student picked, the result.
    correct_option_id: int | None = None
    correct_answer: str = ""
    selected_option_id: int | None = None
    text_answer: str = ""
    is_correct: bool
    marks_awarded: int


class ResultOut(CamelSchema):
    test_id: int
    submission_id: int
    title: str
    subject: str
    total_marks: int
    max_marks: int
    duration_min: int
    completed_date: str
    questions: list[ResultQuestionOut]


def _section_or_none(student, school):
    return _current_section(student, school)


def _resolve_online_test(student, school, test_id: int) -> Test | None:
    """Visible to the parent only if it's published online and for the child's
    section."""
    section = _section_or_none(student, school)
    if section is None:
        return None
    return (
        Test.objects.filter(
            id=test_id, section=section, mode=TestMode.ONLINE,
            published_at__isnull=False,
        )
        .select_related("subject")
        .first()
    )


@router.get("/children/{child_id}/online-tests", response=list[OnlineTestListItem])
def list_online_tests(request: HttpRequest, child_id: int) -> list[dict]:
    student = get_parent_child(request, child_id)
    school = request.auth.school  # type: ignore[attr-defined]
    section = _section_or_none(student, school)
    if section is None:
        return []
    tests = (
        Test.objects.filter(
            section=section, mode=TestMode.ONLINE, published_at__isnull=False,
        )
        .select_related("subject")
        .annotate(qcount=Count("questions"))
        .order_by("-test_date", "-id")
    )
    # Pull this student's submissions in one query.
    subs_by_test = {
        s.test_id: s
        for s in TestSubmission.objects.filter(student=student, test__in=tests)
    }
    out: list[dict] = []
    for t in tests:
        sub = subs_by_test.get(t.id)
        if sub is not None and sub.is_submitted:
            status = "completed"
            score = sub.total_marks
            completed = sub.submitted_at.isoformat() if sub.submitted_at else None
        else:
            status = "pending"
            score = None
            completed = None
        out.append({
            "id": t.id,
            "subject": t.subject.name,
            "title": t.name,
            "duration_min": t.duration_min,
            "available_from": t.available_from.isoformat() if t.available_from else None,
            "deadline": t.available_until.isoformat() if t.available_until else None,
            "max_marks": t.max_marks or 0,
            "questions": t.qcount,
            "status": status,
            "score": score,
            "completed_date": completed,
        })
    return out


def _seconds_remaining(submission: TestSubmission, test: Test) -> int:
    if test.duration_min <= 0:
        return 0
    end = submission.started_at + timezone.timedelta(minutes=test.duration_min)
    delta = (end - timezone.now()).total_seconds()
    return max(0, int(delta))


def _serialize_question_for_take(question: Question, saved: SubmissionAnswer | None) -> dict:
    """Strip out correctness signals so the take screen cannot cheat."""
    options = [
        {"id": o.id, "text": o.text}
        for o in question.options.all().order_by("display_order")
    ]
    return {
        "id": question.id,
        "question_type": question.question_type,
        "text": question.text,
        "marks": question.marks,
        "display_order": question.display_order,
        "options": options,
        "selected_option_id": saved.selected_option_id if saved else None,
        "text_answer": (saved.text_answer if saved else "") or "",
    }


class TestNotOpen(APIError):
    status_code = 409
    code = "TEST_NOT_OPEN"


class TestClosed(APIError):
    status_code = 409
    code = "TEST_CLOSED"


def _fmt_when(dt) -> str:  # type: ignore[no-untyped-def]
    """A student-friendly local time, e.g. '20 Jun, 12:20 AM' (display tz)."""
    local = dt.astimezone(ZoneInfo(settings.DISPLAY_TIME_ZONE))
    hour12 = local.hour % 12 or 12
    ampm = "AM" if local.hour < 12 else "PM"
    return f"{local.day} {local:%b}, {hour12}:{local.minute:02d} {ampm}"


@router.post("/children/{child_id}/online-tests/{test_id}/start", response=StartResponse)
def start_online_test(request: HttpRequest, child_id: int, test_id: int) -> dict:
    student = get_parent_child(request, child_id)
    school = request.auth.school  # type: ignore[attr-defined]
    test = _resolve_online_test(student, school, test_id)
    if test is None:
        raise NotFound("No such online test for this child.")
    # Server-side gate behind the UI (which can be stale): reject before the
    # window opens or after it closes, with a message the app shows verbatim.
    now = timezone.now()
    if test.available_from and now < test.available_from:
        raise TestNotOpen(f"This test opens on {_fmt_when(test.available_from)}.")
    if test.available_until and now > test.available_until:
        raise TestClosed(f"This test closed on {_fmt_when(test.available_until)}.")

    # Find-or-create the submission; resumes if it already exists.
    submission, _created = TestSubmission.objects.get_or_create(
        test=test, student=student,
        defaults={"school": school, "max_marks": test.max_marks or 0},
    )
    if submission.is_submitted:
        # Already submitted — the take screen redirects to the result.
        raise Conflict("This test has already been submitted.")

    # Preload saved answers so the screen can show resume state.
    saved_by_q = {a.question_id: a for a in submission.answers.all()}
    questions = (
        test.questions.all()
        .prefetch_related("options")
        .order_by("display_order", "id")
    )
    return {
        "submission_id": submission.id,
        "test_id": test.id,
        "title": test.name,
        "subject": test.subject.name,
        "duration_min": test.duration_min,
        "seconds_remaining": _seconds_remaining(submission, test),
        "max_marks": test.max_marks or 0,
        "questions": [
            _serialize_question_for_take(q, saved_by_q.get(q.id)) for q in questions
        ],
    }


def _student_owns_submission(parent, submission_id: int) -> TestSubmission | None:
    return (
        TestSubmission.objects.filter(
            id=submission_id, student__parent_links__parent=parent
        )
        .select_related("test")
        .distinct()
        .first()
    )


@router.patch(
    "/children/{child_id}/submissions/{submission_id}/answer", response=SuccessAck,
)
def save_answer(
    request: HttpRequest, child_id: int, submission_id: int, payload: AnswerRequest,
) -> dict:
    student = get_parent_child(request, child_id)
    school = request.auth.school  # type: ignore[attr-defined]
    submission = TestSubmission.objects.filter(
        id=submission_id, student=student
    ).select_related("test").first()
    if submission is None:
        raise NotFound("No such submission.")
    if submission.is_submitted:
        raise ValidationFailed("This submission has already been submitted.")
    question = submission.test.questions.filter(id=payload.question_id).first()
    if question is None:
        raise NotFound("That question doesn't belong to this test.")

    selected_option = None
    if payload.option_id is not None:
        selected_option = MCQOption.objects.filter(
            id=payload.option_id, question=question
        ).first()
        if selected_option is None:
            raise ValidationFailed("That option doesn't belong to this question.")
    answer, _created = SubmissionAnswer.objects.get_or_create(
        submission=submission, question=question,
        defaults={"school": school},
    )
    answer.selected_option = selected_option
    answer.text_answer = (payload.text_answer or "").strip()
    answer.save(update_fields=["selected_option", "text_answer", "updated_at"])
    return {"success": True}


def _grade_submission(submission: TestSubmission) -> None:
    """Stamp is_correct + marks_awarded on every answer, total on submission."""
    answers = list(
        submission.answers.select_related("question", "selected_option")
    )
    total = 0
    for ans in answers:
        q = ans.question
        if q.question_type == QuestionType.MCQ:
            ans.is_correct = bool(
                ans.selected_option_id and ans.selected_option.is_correct
            )
        else:  # short_answer
            given = (ans.text_answer or "").strip().lower()
            expected = (q.correct_answer or "").strip().lower()
            ans.is_correct = bool(expected and given == expected)
        ans.marks_awarded = q.marks if ans.is_correct else 0
        total += ans.marks_awarded
    SubmissionAnswer.objects.bulk_update(answers, ["is_correct", "marks_awarded", "updated_at"])
    submission.total_marks = total
    # max_marks is the sum of every question's marks (not just the ones the
    # student answered — unanswered questions count as 0).
    submission.max_marks = sum(
        q.marks for q in submission.test.questions.all()
    )


def _result_payload(submission: TestSubmission) -> dict:
    test = submission.test
    answers_by_q = {a.question_id: a for a in submission.answers.all()}
    questions = (
        test.questions.all()
        .prefetch_related("options")
        .order_by("display_order", "id")
    )
    rows = []
    for q in questions:
        ans = answers_by_q.get(q.id)
        correct_opt = next(
            (o for o in q.options.all() if o.is_correct), None,
        ) if q.question_type == QuestionType.MCQ else None
        rows.append({
            "id": q.id,
            "question_type": q.question_type,
            "text": q.text,
            "marks": q.marks,
            "display_order": q.display_order,
            "options": [{"id": o.id, "text": o.text} for o in q.options.all().order_by("display_order")],
            "correct_option_id": correct_opt.id if correct_opt else None,
            "correct_answer": q.correct_answer or "",
            "selected_option_id": ans.selected_option_id if ans else None,
            "text_answer": (ans.text_answer if ans else "") or "",
            "is_correct": bool(ans.is_correct) if ans else False,
            "marks_awarded": ans.marks_awarded if ans else 0,
        })
    completed = submission.submitted_at.isoformat() if submission.submitted_at else ""
    return {
        "test_id": test.id,
        "submission_id": submission.id,
        "title": test.name,
        "subject": test.subject.name,
        "total_marks": submission.total_marks or 0,
        "max_marks": submission.max_marks,
        "duration_min": test.duration_min,
        "completed_date": completed,
        "questions": rows,
    }


@router.post(
    "/children/{child_id}/submissions/{submission_id}/submit", response=ResultOut,
)
def submit_test(request: HttpRequest, child_id: int, submission_id: int) -> dict:
    student = get_parent_child(request, child_id)
    submission = TestSubmission.objects.filter(
        id=submission_id, student=student
    ).select_related("test").first()
    if submission is None:
        raise NotFound("No such submission.")
    if submission.is_submitted:
        # Idempotent — re-submitting just returns the existing result.
        return _result_payload(submission)
    with transaction.atomic():
        _grade_submission(submission)
        submission.status = SubmissionStatus.SUBMITTED
        submission.submitted_at = timezone.now()
        submission.save(update_fields=[
            "status", "submitted_at", "total_marks", "max_marks", "updated_at",
        ])
        # Mirror to TestScore so the teacher report endpoint keeps working
        # for online tests too.
        TestScore.objects.update_or_create(
            test=submission.test, student=student,
            defaults={
                "school": submission.school,
                "marks_obtained": submission.total_marks,
                "is_absent": False,
            },
        )
    return _result_payload(submission)


@router.get(
    "/children/{child_id}/online-tests/{test_id}/result", response=ResultOut,
)
def get_test_result(request: HttpRequest, child_id: int, test_id: int) -> dict:
    student = get_parent_child(request, child_id)
    school = request.auth.school  # type: ignore[attr-defined]
    test = _resolve_online_test(student, school, test_id)
    if test is None:
        raise NotFound("No such online test for this child.")
    submission = TestSubmission.objects.filter(
        test=test, student=student, status=SubmissionStatus.SUBMITTED,
    ).first()
    if submission is None:
        raise NotFound("This test hasn't been submitted yet.")
    return _result_payload(submission)
