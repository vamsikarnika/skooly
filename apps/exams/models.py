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
