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


class AnnouncementCategory(models.TextChoices):
    SCHOOL = "school", "School"
    CLASS = "class", "Class"
    EXAM = "exam", "Exam"
    HOLIDAY = "holiday", "Holiday"
    FEE = "fee", "Fee"


class AnnouncementRecipient(models.TextChoices):
    """Who an announcement is intended for. The class/section targeting still
    scopes *which* parents/teachers; this decides which audience sees it at
    all. EVERYONE preserves the original broadcast-to-all behaviour."""

    PARENTS = "parents", "Parents"
    TEACHERS = "teachers", "Teachers"
    EVERYONE = "everyone", "Everyone"


class Announcement(TenantScopedModel):
    """A broadcast notice. Targeting: school-wide (no target_class/section),
    class-wide (target_class set), or section-wide (target_section set).

    v1 simplification: is_read lives on the row and is shared across all
    parents who can see it. Acceptable for the single-active-parent demo; will
    need an AnnouncementReceipt join when multi-parent usage lands.
    """

    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    date = models.DateField()
    category = models.CharField(max_length=16, choices=AnnouncementCategory.choices)
    recipient_type = models.CharField(
        max_length=16,
        choices=AnnouncementRecipient.choices,
        default=AnnouncementRecipient.EVERYONE,
    )
    target_class = models.ForeignKey(
        "academics.Class",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="announcements",
    )
    target_section = models.ForeignKey(
        "academics.Section",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="announcements",
    )
    is_read = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = "announcements"
        ordering = ["-date", "-id"]
        indexes = [
            models.Index(fields=["school", "-date"]),
            models.Index(fields=["target_class", "-date"]),
            models.Index(fields=["target_section", "-date"]),
        ]

    def __str__(self) -> str:
        scope = "school"
        if self.target_section_id:
            scope = f"section={self.target_section_id}"
        elif self.target_class_id:
            scope = f"class={self.target_class_id}"
        return f"[{self.category}] {self.title} ({scope})"


class AnnouncementTeacherRead(TenantScopedModel):
    """Per-teacher read state for an announcement.

    Announcement.is_read is parent-scoped (the v1 simplification noted above).
    Teachers track their own read state here so marking an announcement read in
    the teacher app never affects what parents see, and vice versa.
    """

    announcement = models.ForeignKey(
        Announcement, on_delete=models.CASCADE, related_name="teacher_reads"
    )
    teacher = models.ForeignKey(
        "people.Teacher", on_delete=models.CASCADE, related_name="announcement_reads"
    )
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "announcement_teacher_reads"
        constraints = [
            models.UniqueConstraint(
                fields=["announcement", "teacher"],
                name="uniq_announcement_teacher_read",
            ),
        ]
        indexes = [
            models.Index(fields=["teacher", "announcement"]),
        ]

    def __str__(self) -> str:
        return f"teacher={self.teacher_id} read announcement={self.announcement_id}"


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
