"""Auth business logic. API handlers are thin wrappers around these."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone
from ninja_jwt.tokens import RefreshToken

from apps.accounts.models import OneTimePassword, PasswordResetToken, Role, User
from apps.core.context import use_school
from apps.core.exceptions import Conflict, Unauthorized, ValidationFailed
from apps.schools.models import AcademicYear, Board, School

logger = logging.getLogger(__name__)

OTP_TTL = timedelta(minutes=10)
RESET_TOKEN_TTL = timedelta(minutes=15)


def issue_tokens_for_user(user: User) -> dict[str, str]:
    refresh = RefreshToken.for_user(user)
    refresh["school_id"] = user.school_id
    refresh["role"] = user.role
    access = refresh.access_token
    access["school_id"] = user.school_id
    access["role"] = user.role
    return {"access_token": str(access), "refresh_token": str(refresh)}


@transaction.atomic
def signup_school(
    *,
    school_name: str,
    board: str,
    address: str,
    academic_year_label: str,
    academic_year_start: Any,
    academic_year_end: Any,
    admin_first_name: str,
    admin_last_name: str,
    admin_phone: str,
    admin_email: str,
    admin_password: str,
) -> tuple[User, School, dict[str, str]]:
    if board not in Board.values:
        raise ValidationFailed("Invalid board.", {"board": ["unsupported value"]})

    if User.objects.filter(phone=admin_phone).exists():
        raise Conflict("An account already exists with that phone number.")

    school = School.objects.create(
        name=school_name,
        board=board,
        address=address,
    )
    year = AcademicYear.objects.create(
        school=school,
        label=academic_year_label,
        start_date=academic_year_start,
        end_date=academic_year_end,
        is_current=True,
    )
    school.current_academic_year = year
    school.save(update_fields=["current_academic_year"])

    with use_school(school):
        user = User.objects.create_user(
            phone=admin_phone,
            password=admin_password,
            school=school,
            role=Role.ADMIN,
            first_name=admin_first_name,
            last_name=admin_last_name,
            email=admin_email,
        )
    user.touch_last_login()
    tokens = issue_tokens_for_user(user)
    return user, school, tokens


def login(*, phone: str, password: str) -> tuple[User, School | None, dict[str, str]]:
    # ``authenticate`` uses the USERNAME_FIELD which is ``phone``.
    user = authenticate(phone=phone, password=password)
    if user is None or not getattr(user, "is_active", False):
        raise Unauthorized("Invalid phone or password.")
    user.touch_last_login()
    school = user.school
    tokens = issue_tokens_for_user(user)
    return user, school, tokens


def refresh_tokens(refresh_token: str) -> dict[str, str]:
    try:
        token = RefreshToken(refresh_token)
    except Exception as exc:  # ninja_jwt raises various exceptions
        raise Unauthorized("Invalid or expired refresh token.") from exc

    user_id = token.get(settings.NINJA_JWT["USER_ID_CLAIM"])
    user = User.objects.filter(id=user_id, is_active=True).first()
    if user is None:
        raise Unauthorized("User not found or inactive.")

    # Rotation: blacklist old, issue new pair.
    new = issue_tokens_for_user(user)
    try:
        token.blacklist()
    except AttributeError:
        # blacklist app not enabled — rotation still happens, just no revocation list
        pass
    return new


def _hash_otp(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def request_password_reset_otp(phone: str) -> str:
    """Generate an OTP for the phone. Always returns the (plain) OTP so the
    SMS/WhatsApp task can dispatch it. The hashed version is what we store."""
    user = User.objects.filter(phone=phone, is_active=True).first()
    if user is None:
        # Don't leak whether the phone exists — still return a fake-shaped
        # code so timing/response is uniform. The caller logs to console.
        logger.info("password_reset_requested phone=%s exists=False", phone)
        return secrets.choice(["123456", "234567", "345678"])

    code = f"{secrets.randbelow(1_000_000):06d}"
    OneTimePassword.objects.create(
        phone=phone,
        code_hash=_hash_otp(code),
        purpose="password_reset",
        expires_at=timezone.now() + OTP_TTL,
    )
    logger.info("password_reset_otp_generated phone=%s user_id=%s", phone, user.id)
    return code


def verify_password_reset_otp(phone: str, otp: str) -> tuple[str, Any]:
    record = (
        OneTimePassword.objects.filter(phone=phone, purpose="password_reset", consumed_at__isnull=True)
        .order_by("-created_at")
        .first()
    )
    if record is None or not record.is_valid():
        raise Unauthorized("Invalid or expired OTP.")
    record.attempts += 1
    if record.code_hash != _hash_otp(otp):
        record.save(update_fields=["attempts"])
        raise Unauthorized("Invalid or expired OTP.")
    record.consumed_at = timezone.now()
    record.save(update_fields=["consumed_at", "attempts"])

    user = User.objects.filter(phone=phone, is_active=True).first()
    if user is None:
        raise Unauthorized("Invalid or expired OTP.")

    token = secrets.token_urlsafe(48)
    reset = PasswordResetToken.objects.create(
        user=user,
        token=token,
        expires_at=timezone.now() + RESET_TOKEN_TTL,
    )
    return token, reset.expires_at


def reset_password(reset_token: str, new_password: str) -> User:
    record = PasswordResetToken.objects.filter(token=reset_token).first()
    if record is None or not record.is_valid():
        raise Unauthorized("Invalid or expired reset token.")
    user = record.user
    user.password = make_password(new_password)
    user.save(update_fields=["password"])
    record.used_at = timezone.now()
    record.save(update_fields=["used_at"])
    return user


def get_permissions(user: User) -> list[str]:
    if user.role == Role.ADMIN:
        return [
            "students.read",
            "students.write",
            "teachers.read",
            "teachers.write",
            "fees.read",
            "fees.write",
            "attendance.read",
            "attendance.write",
            "tests.read",
            "tests.write",
            "reports.read",
            "reports.write",
            "school.write",
        ]
    if user.role == Role.TEACHER:
        return [
            "students.read",
            "attendance.read",
            "attendance.write",
            "tests.read",
            "tests.write",
        ]
    return []


def check_user_password(user: User, raw: str) -> bool:
    return check_password(raw, user.password)
