"""Tests and per-student scores.

Each Test is one (section, subject, date, type) row. TestScore stores
the per-student outcome with a unique constraint on (test, student) so a
re-mark UPDATEs rather than duplicating.

``published_at`` null = draft (teacher app territory). Read endpoints
filter to published-only by default; the teacher-app POSTs will set
``published_at`` and queue WhatsApp dispatch.
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
    test_date = models.DateField()
    max_marks = models.PositiveSmallIntegerField()
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
        return f"{self.section_id} · {self.subject_id} · {self.test_type} ({self.test_date})"

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
