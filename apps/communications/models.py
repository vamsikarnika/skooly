"""In-app notifications for the parent app.

Notifications are per-student rows with read-state on the row itself (shared
across a child's linked parents — see the v1 design note in the parent API).
Rows are seeded for now; auto-generation at source events (attendance marked,
test published, fee overdue) lands with the push/WhatsApp module.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import TenantScopedModel


class NotificationType(models.TextChoices):
    ATTENDANCE = "attendance", "Attendance"
    MARKS = "marks", "Marks"
    FEE = "fee", "Fee"
    ANNOUNCEMENT = "announcement", "Announcement"
    TEST = "test", "Test"


class Notification(TenantScopedModel):
    student = models.ForeignKey(
        "people.Student", on_delete=models.CASCADE, related_name="notifications"
    )
    type = models.CharField(max_length=16, choices=NotificationType.choices)
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=500, blank=True)
    link_to = models.CharField(max_length=120, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    # Optional. When set, the notification is hidden from the parent once it
    # passes (e.g. a "present today" notice expires at end of day so it doesn't
    # pile up). Null = never expires (default behaviour).
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "notifications"
        # Unread first, then newest.
        ordering = ["is_read", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["student", "is_read"]),
            models.Index(fields=["school", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"[{self.type}] {self.title} (student={self.student_id})"
