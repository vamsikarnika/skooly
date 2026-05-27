"""Student and Teacher models."""

from __future__ import annotations

from django.db import models

from apps.core.models import TenantScopedModel


class Relation(models.TextChoices):
    FATHER = "Father", "Father"
    MOTHER = "Mother", "Mother"
    GUARDIAN = "Guardian", "Guardian"


class StudentStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    WITHDRAWN = "withdrawn", "Withdrawn"
    GRADUATED = "graduated", "Graduated"


class TeacherStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"


class Gender(models.TextChoices):
    MALE = "Male", "Male"
    FEMALE = "Female", "Female"


class Student(TenantScopedModel):
    admission_number = models.CharField(max_length=40)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    dob = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, choices=Gender.choices)

    aadhaar_last4 = models.CharField(
        max_length=4,
        blank=True,
        help_text="Last 4 digits only — full Aadhaar encrypted in v2.",
    )
    photo_url = models.URLField(blank=True)
    blood_group = models.CharField(max_length=6, blank=True)
    address = models.TextField(blank=True)

    parent1_name = models.CharField(max_length=200, blank=True)
    parent1_phone = models.CharField(max_length=20, blank=True)
    parent1_relation = models.CharField(max_length=20, choices=Relation.choices, blank=True)
    parent1_email = models.EmailField(blank=True)
    parent1_whatsapp = models.BooleanField(default=True)

    parent2_name = models.CharField(max_length=200, blank=True)
    parent2_phone = models.CharField(max_length=20, blank=True)
    parent2_relation = models.CharField(max_length=20, choices=Relation.choices, blank=True)
    parent2_email = models.EmailField(blank=True)
    parent2_whatsapp = models.BooleanField(default=False)

    primary_whatsapp_phone = models.CharField(max_length=20, blank=True)
    emergency_contact_name = models.CharField(max_length=200, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)

    previous_school = models.CharField(max_length=200, blank=True)
    admission_date = models.DateField()
    withdrawal_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=StudentStatus.choices, default=StudentStatus.ACTIVE)

    class Meta:
        db_table = "students"
        unique_together = [("school", "admission_number")]
        indexes = [
            models.Index(fields=["school", "status"]),
            models.Index(fields=["first_name", "last_name"]),
        ]
        ordering = ["first_name", "last_name"]

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name} ({self.admission_number})".strip()

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class Teacher(TenantScopedModel):
    user = models.OneToOneField(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="teacher_profile",
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    photo_url = models.URLField(blank=True)
    qualification = models.CharField(max_length=200, blank=True)
    joining_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=TeacherStatus.choices, default=TeacherStatus.ACTIVE)

    class Meta:
        db_table = "teachers"
        indexes = [
            models.Index(fields=["school", "status"]),
            models.Index(fields=["first_name", "last_name"]),
        ]
        ordering = ["first_name", "last_name"]

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name} ({self.phone})".strip()

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class Parent(TenantScopedModel):
    """A parent/guardian who logs into the skooly-parent mobile app via OTP.

    Identity mirrors Teacher: a login ``User`` (role=parent) plus a profile row.
    The phone is the login credential; children are linked via ``ParentStudent``.
    """

    user = models.OneToOneField(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="parent_profile",
    )
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    students = models.ManyToManyField(
        Student,
        through="people.ParentStudent",
        related_name="parents",
    )

    class Meta:
        db_table = "parents"
        indexes = [
            models.Index(fields=["school", "phone"]),
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.phone})".strip()


class ParentStudent(TenantScopedModel):
    """Links a Parent to one of their children, with the relationship label."""

    parent = models.ForeignKey(Parent, on_delete=models.CASCADE, related_name="links")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="parent_links")
    relation = models.CharField(max_length=20, choices=Relation.choices, blank=True)

    class Meta:
        db_table = "parent_students"
        constraints = [
            models.UniqueConstraint(fields=["parent", "student"], name="uniq_parent_student"),
        ]
        indexes = [
            models.Index(fields=["student"]),
        ]
