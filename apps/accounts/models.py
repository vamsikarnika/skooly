"""Custom User model. Always create this BEFORE the first migration.

Login identifier is ``phone`` scoped to a school. A single phone number can
exist in multiple schools (a teacher who works at two schools needs separate
accounts — that's by design for clean tenant isolation).
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class Role(models.TextChoices):
    ADMIN = "admin", "School Admin"
    TEACHER = "teacher", "Teacher"


class UserManager(BaseUserManager):
    """The User manager bypasses tenant scoping intentionally — auth
    happens BEFORE tenant context is set on the request."""

    use_in_migrations = True

    def create_user(
        self,
        *,
        phone: str,
        password: str | None = None,
        school: Any = None,
        role: str = Role.ADMIN,
        **extra: Any,
    ) -> User:
        if not phone:
            raise ValueError("Users must have a phone number.")
        user = self.model(phone=phone, school=school, role=role, **extra)
        user.password = make_password(password) if password else make_password(None)
        user.save(using=self._db)
        return user

    def create_superuser(self, *, phone: str, password: str, **extra: Any) -> User:
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", Role.ADMIN)
        return self.create_user(phone=phone, password=password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        related_name="users",
        null=True,
        blank=True,
    )
    phone = models.CharField(max_length=20, unique=True)
    email = models.EmailField(blank=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.ADMIN)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    last_login_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = ["first_name"]

    class Meta:
        db_table = "users"
        constraints = [
            models.UniqueConstraint(
                fields=["school", "email"],
                name="uniq_school_email",
                condition=models.Q(email__gt=""),
            ),
        ]
        indexes = [
            models.Index(fields=["school", "role"]),
        ]

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name} ({self.phone})".strip()

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def get_full_name(self) -> str:
        return self.full_name

    def get_short_name(self) -> str:
        return self.first_name

    def touch_last_login(self) -> None:
        self.last_login_at = timezone.now()
        self.save(update_fields=["last_login_at"])


class PasswordResetToken(models.Model):
    """Short-lived OTP-issued token used during the password reset flow."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reset_tokens")
    token = models.CharField(max_length=128, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "password_reset_tokens"
        indexes = [models.Index(fields=["token"])]

    def is_valid(self) -> bool:
        return self.used_at is None and self.expires_at > timezone.now()


class OneTimePassword(models.Model):
    """OTP for phone-based flows (forgot-password). Stores a hashed code."""

    phone = models.CharField(max_length=20, db_index=True)
    code_hash = models.CharField(max_length=128)
    purpose = models.CharField(max_length=40, default="password_reset")
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "one_time_passwords"
        indexes = [models.Index(fields=["phone", "purpose", "-created_at"])]

    def is_valid(self) -> bool:
        return self.consumed_at is None and self.expires_at > timezone.now() and self.attempts < 5
