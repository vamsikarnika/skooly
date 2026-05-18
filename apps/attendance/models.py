"""Daily attendance records.

One row per (student, date). Section is denormalised onto the row so we can
query a section roster's attendance for a date without joining through
enrollments — important for the daily mark screen.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import TenantScopedModel


class AttendanceStatus(models.TextChoices):
    PRESENT = "present", "Present"
    ABSENT = "absent", "Absent"
    LATE = "late", "Late"
    HALF_DAY = "half_day", "Half day"


class Attendance(TenantScopedModel):
    student = models.ForeignKey(
        "people.Student",
        on_delete=models.CASCADE,
        related_name="attendance",
    )
    section = models.ForeignKey(
        "academics.Section",
        on_delete=models.PROTECT,
        related_name="attendance",
    )
    date = models.DateField()
    status = models.CharField(
        max_length=16,
        choices=AttendanceStatus.choices,
        default=AttendanceStatus.PRESENT,
    )
    marked_by = models.ForeignKey(
        "people.Teacher",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_marked",
    )
    marked_at = models.DateTimeField(auto_now_add=True)
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "attendance"
        constraints = [
            models.UniqueConstraint(
                fields=["student", "date"],
                name="uniq_student_date_attendance",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "date"]),
            models.Index(fields=["section", "date"]),
            models.Index(fields=["student", "date"]),
        ]
        ordering = ["-date", "student_id"]

    def __str__(self) -> str:
        return f"{self.student_id} {self.date} {self.status}"
