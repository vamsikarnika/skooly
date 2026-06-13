"""Tests, per-student scores, and online-test question bank.

Each Test is one (section, subject, date, type) row.  ``mode`` distinguishes
offline paper tests from online (student-attempted) tests.

Offline flow: teacher enters marks manually → publish.
Online flow:  teacher builds questions → publish → students attempt between
              ``available_from`` and ``available_until``.

``published_at`` null = draft.  For online tests students can *see* the test
after publish but can only *attempt* it once ``available_from`` is reached.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import TenantScopedModel


class TestType(models.TextChoices):
    FA1 = "FA1", "Formative Assessment 1"
    FA2 = "FA2", "Formative Assessment 2"
    FA3 = "FA3", "Formative Assessment 3"
    FA4 = "FA4", "Formative Assessment 4"
    SA1 = "SA1", "Summative Assessment 1"
    SA2 = "SA2", "Summative Assessment 2"
    OTHER = "OTHER", "Other / Unit test"


class TestMode(models.TextChoices):
    OFFLINE = "offline", "Offline (paper)"
    ONLINE = "online", "Online (student-attempted)"


class QuestionType(models.TextChoices):
    MCQ = "mcq", "Multiple Choice"
    SHORT_ANSWER = "short_answer", "Short Answer"


class Difficulty(models.TextChoices):
    EASY = "easy", "Easy"
    MEDIUM = "medium", "Medium"
    HARD = "hard", "Hard"


class Test(TenantScopedModel):
    section = models.ForeignKey(
        "academics.Section",
        on_delete=models.PROTECT,
        related_name="tests",
    )
    subject = models.ForeignKey(
        "academics.Subject",
        on_delete=models.PROTECT,
        related_name="tests",
    )
    name = models.CharField(max_length=120)
    test_type = models.CharField(max_length=16, choices=TestType.choices, default=TestType.OTHER)
    mode = models.CharField(
        max_length=10, choices=TestMode.choices, default=TestMode.OFFLINE, db_index=True
    )
    test_date = models.DateField()
    # Online-only scheduling fields (null for offline tests)
    available_from = models.DateTimeField(null=True, blank=True)
    available_until = models.DateTimeField(null=True, blank=True)
    # Duration in minutes — 0 for offline (no time limit), >0 for online
    duration_min = models.PositiveSmallIntegerField(default=0)
    # Null for fresh online tests until questions are saved (auto-calculated from question marks)
    max_marks = models.PositiveSmallIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(
        "people.Teacher",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tests_created",
    )
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "tests"
        indexes = [
            models.Index(fields=["school", "-test_date"]),
            models.Index(fields=["section", "-test_date"]),
            models.Index(fields=["subject", "-test_date"]),
        ]
        ordering = ["-test_date", "-id"]

    def __str__(self) -> str:
        return f"{self.section_id} · {self.name} ({self.test_date})"

    @property
    def is_published(self) -> bool:
        return self.published_at is not None


class TestScore(TenantScopedModel):
    test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="scores")
    student = models.ForeignKey(
        "people.Student", on_delete=models.CASCADE, related_name="test_scores"
    )
    marks_obtained = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    is_absent = models.BooleanField(default=False)
    entered_by = models.ForeignKey(
        "people.Teacher",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scores_entered",
    )
    entered_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "test_scores"
        constraints = [
            models.UniqueConstraint(fields=["test", "student"], name="uniq_test_student_score"),
        ]
        indexes = [
            models.Index(fields=["test"]),
            models.Index(fields=["student"]),
        ]


class Question(TenantScopedModel):
    """A single question belonging to an online test."""

    test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="questions")
    question_type = models.CharField(max_length=16, choices=QuestionType.choices)
    text = models.TextField()
    marks = models.PositiveSmallIntegerField(default=1)
    display_order = models.PositiveSmallIntegerField(default=0)
    difficulty = models.CharField(
        max_length=8, choices=Difficulty.choices, blank=True, default=""
    )
    topic = models.CharField(max_length=80, blank=True, default="")
    # For short-answer questions — case-insensitive match at grading time
    correct_answer = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        db_table = "test_questions"
        ordering = ["display_order", "id"]
        indexes = [
            models.Index(fields=["test"]),
        ]

    def __str__(self) -> str:
        return f"Q{self.display_order + 1} [{self.question_type}] {self.text[:60]}"


class MCQOption(models.Model):
    """One of the four options for an MCQ question."""

    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    text = models.CharField(max_length=500)
    is_correct = models.BooleanField(default=False)
    display_order = models.PositiveSmallIntegerField(default=0)  # 0-3

    class Meta:
        db_table = "test_mcq_options"
        ordering = ["display_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["question", "display_order"],
                name="uniq_option_display_order",
            ),
        ]

    def __str__(self) -> str:
        marker = " ✓" if self.is_correct else ""
        return f"{['A','B','C','D'][self.display_order]}. {self.text}{marker}"


class ReportCardTerm(models.TextChoices):
    """AP State Board terms. Annual = year-end summary across terms."""

    TERM_1 = "term1", "Term 1"
    TERM_2 = "term2", "Term 2"
    ANNUAL = "annual", "Annual"


class ReportCard(TenantScopedModel):
    """A student's report card for one term.

    The full rendered payload lives in ``data_snapshot`` so that corrections
    to underlying test scores never silently rewrite a report the parent has
    already seen. The teacher generates by aggregating TestScore rows
    (deferred to a follow-up ticket) and publishes by setting
    ``published_at``; drafts are invisible to the parent.
    """

    student = models.ForeignKey(
        "people.Student", on_delete=models.CASCADE, related_name="report_cards"
    )
    academic_year = models.ForeignKey(
        "schools.AcademicYear", on_delete=models.PROTECT, related_name="report_cards"
    )
    # Free-text report name set by the teacher, e.g. "Term 1", "Unit Test 1",
    # "Half-Yearly". The parent app renders this as the report title. Kept on a
    # field named `term` because the parent serializer + unique key reference it.
    term = models.CharField(max_length=60)
    generated_by = models.ForeignKey(
        "people.Teacher",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="report_cards_generated",
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    # Full rendered payload — see apps/exams/parent_api.ReportCardOut for the
    # exact shape the parent app consumes.
    data_snapshot = models.JSONField(default=dict)
    pdf_url = models.URLField(blank=True)

    class Meta:
        db_table = "report_cards"
        constraints = [
            models.UniqueConstraint(
                fields=["student", "academic_year", "term"],
                name="uniq_student_year_term_report",
            ),
        ]
        indexes = [
            models.Index(fields=["student", "-published_at"]),
            models.Index(fields=["school", "-published_at"]),
        ]
        ordering = ["-published_at", "-id"]

    def __str__(self) -> str:
        return f"ReportCard(student={self.student_id} term={self.term})"

    @property
    def is_published(self) -> bool:
        return self.published_at is not None


# ---------------------------------------------------------------------------
# Online test submissions
# ---------------------------------------------------------------------------


class SubmissionStatus(models.TextChoices):
    """A submission is either in-progress (the student is taking the test, or
    paused mid-test on a re-open) or submitted (graded, immutable)."""

    IN_PROGRESS = "in_progress", "In progress"
    SUBMITTED = "submitted", "Submitted"


class TestSubmission(TenantScopedModel):
    """A student's attempt at one online test.

    Exactly one row per (test, student) - re-opening the test resumes the
    same submission rather than starting fresh. ``total_marks`` is populated
    only at submit time, alongside an aggregate ``TestScore`` row so the
    existing teacher reports keep working for online tests too.
    """

    test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey(
        "people.Student", on_delete=models.CASCADE, related_name="test_submissions"
    )
    status = models.CharField(
        max_length=16,
        choices=SubmissionStatus.choices,
        default=SubmissionStatus.IN_PROGRESS,
    )
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    # Populated at submit time; null while in progress.
    total_marks = models.PositiveSmallIntegerField(null=True, blank=True)
    max_marks = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "test_submissions"
        constraints = [
            models.UniqueConstraint(fields=["test", "student"], name="uniq_test_student_submission"),
        ]
        indexes = [
            models.Index(fields=["student", "-submitted_at"]),
            models.Index(fields=["test"]),
        ]
        ordering = ["-submitted_at", "-id"]

    def __str__(self) -> str:
        return f"Submission(test={self.test_id} student={self.student_id} {self.status})"

    @property
    def is_submitted(self) -> bool:
        return self.status == SubmissionStatus.SUBMITTED


class SubmissionAnswer(TenantScopedModel):
    """One student answer within a submission.

    For MCQ questions, ``selected_option`` references the chosen MCQOption.
    For short-answer questions, ``text_answer`` holds the free text.
    ``is_correct`` + ``marks_awarded`` are stamped at submit time by the
    auto-grader and remain null while the submission is in progress.
    """

    submission = models.ForeignKey(
        TestSubmission, on_delete=models.CASCADE, related_name="answers"
    )
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="answers")
    # MCQ -> one of the question's options. Short answer -> null.
    selected_option = models.ForeignKey(
        MCQOption, on_delete=models.SET_NULL, null=True, blank=True, related_name="answers"
    )
    # Short answer -> typed response. MCQ -> blank.
    text_answer = models.CharField(max_length=200, blank=True)
    is_correct = models.BooleanField(null=True, blank=True)
    marks_awarded = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "submission_answers"
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "question"], name="uniq_submission_question_answer"
            ),
        ]
        indexes = [
            models.Index(fields=["submission"]),
        ]
        ordering = ["question__display_order"]

    def __str__(self) -> str:
        return f"Answer(submission={self.submission_id} q={self.question_id})"
