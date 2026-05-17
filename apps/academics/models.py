"""Subjects, classes, sections, and enrollment models."""

from __future__ import annotations

from django.db import models

from apps.core.models import TenantScopedModel


class Subject(TenantScopedModel):
    name = models.CharField(max_length=80)
    code = models.CharField(max_length=20, blank=True)

    class Meta:
        db_table = "subjects"
        unique_together = [("school", "name")]
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Class(TenantScopedModel):
    """A grade level — 'Class 6', 'Class 10', etc. Sections live under it."""

    academic_year = models.ForeignKey(
        "schools.AcademicYear",
        on_delete=models.PROTECT,
        related_name="classes",
    )
    name = models.CharField(max_length=40)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "classes"
        unique_together = [("school", "academic_year", "name")]
        ordering = ["display_order", "name"]
        verbose_name_plural = "classes"

    def __str__(self) -> str:
        return self.name


class Section(TenantScopedModel):
    """A class section — Class 6-A, Class 6-B, etc."""

    class_obj = models.ForeignKey(
        Class,
        on_delete=models.CASCADE,
        related_name="sections",
    )
    name = models.CharField(max_length=10, help_text="e.g. A, B, C")
    class_teacher = models.ForeignKey(
        "people.Teacher",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="class_teacher_of",
    )
    room_number = models.CharField(max_length=20, blank=True)
    capacity = models.PositiveSmallIntegerField(default=40)

    class Meta:
        db_table = "sections"
        unique_together = [("class_obj", "name")]
        ordering = ["class_obj__display_order", "name"]

    def __str__(self) -> str:
        return f"{self.class_obj.name}-{self.name}"


class StudentEnrollment(TenantScopedModel):
    """Links a student to a section for a given academic year."""

    student = models.ForeignKey(
        "people.Student",
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    section = models.ForeignKey(
        Section,
        on_delete=models.PROTECT,
        related_name="enrollments",
    )
    academic_year = models.ForeignKey(
        "schools.AcademicYear",
        on_delete=models.PROTECT,
        related_name="student_enrollments",
    )
    roll_number = models.CharField(max_length=10, blank=True)
    enrollment_date = models.DateField()

    STATUS_CHOICES = [
        ("active", "Active"),
        ("transferred", "Transferred"),
        ("withdrawn", "Withdrawn"),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")

    class Meta:
        db_table = "student_enrollments"
        constraints = [
            models.UniqueConstraint(
                fields=["student", "academic_year"],
                condition=models.Q(status="active"),
                name="uniq_active_enrollment_per_year",
            ),
        ]
        indexes = [
            models.Index(fields=["section", "status"]),
            models.Index(fields=["academic_year", "status"]),
        ]


class TeacherAssignment(TenantScopedModel):
    """Teacher teaches Subject X to Section Y in academic year Z."""

    teacher = models.ForeignKey("people.Teacher", on_delete=models.CASCADE, related_name="assignments")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="assignments")
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="teacher_assignments")
    academic_year = models.ForeignKey(
        "schools.AcademicYear",
        on_delete=models.PROTECT,
        related_name="teacher_assignments",
    )

    class Meta:
        db_table = "teacher_assignments"
        unique_together = [("teacher", "subject", "section", "academic_year")]


class SubjectClassMapping(TenantScopedModel):
    """Which subjects are taught at which class level."""

    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="class_mappings")
    class_obj = models.ForeignKey(Class, on_delete=models.CASCADE, related_name="subject_mappings")

    class Meta:
        db_table = "subject_class_mappings"
        unique_together = [("subject", "class_obj")]
