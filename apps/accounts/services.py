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
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone
from ninja_jwt.tokens import RefreshToken

from apps.accounts.models import OneTimePassword, PasswordResetToken, Role, User
from apps.core.context import use_school
from apps.core.exceptions import Conflict, InvalidOTP, NotFound, Unauthorized, ValidationFailed
from apps.schools.models import AcademicYear, Board, School

logger = logging.getLogger(__name__)

OTP_TTL = timedelta(minutes=10)
RESET_TOKEN_TTL = timedelta(minutes=15)
TEACHER_OTP_PURPOSE = "teacher_login"


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


def normalize_in_phone(raw: str) -> str:
    """Accept ``XXXXXXXXXX`` or ``+91XXXXXXXXXX`` (any separators) and return
    the canonical ``+91XXXXXXXXXX`` form we store on User."""
    digits = "".join(ch for ch in raw if ch.isdigit())
    last10 = digits[-10:]
    return f"+91{last10}"


def _format_in_phone(stored: str) -> str:
    """``+919876543210`` -> ``+91 98765 43210`` for display in the app."""
    digits = "".join(ch for ch in stored if ch.isdigit())[-10:]
    if len(digits) != 10:
        return stored
    return f"+91 {digits[:5]} {digits[5:]}"


def _teacher_primary_subject(teacher: Any, school: School) -> str:
    """First subject the teacher is assigned to in the school's current year.
    The login response carries a single subject; teachers may teach several."""
    from apps.academics.models import TeacherAssignment

    qs = TeacherAssignment.objects.all_tenants().filter(school=school, teacher=teacher)
    year = school.current_academic_year_id
    if year is not None:
        current = qs.filter(academic_year_id=year).select_related("subject").first()
        if current is not None:
            return current.subject.name
    first = qs.select_related("subject").first()
    return first.subject.name if first is not None else ""


def teacher_login(*, phone: str, password: str) -> tuple[User, dict[str, Any]]:
    """Authenticate a teacher for the skooly-guru app.

    Per the teacher API spec this distinguishes 404 (no account) from 401
    (wrong password). Non-teacher accounts are treated as not-found so the
    teacher API never authenticates an admin.
    """
    normalized = normalize_in_phone(phone)
    user = User.objects.filter(phone=normalized, role=Role.TEACHER, is_active=True).first()
    if user is None:
        raise NotFound("No account with that phone number.")
    if not check_user_password(user, password):
        raise Unauthorized("Incorrect password.")

    user.touch_last_login()
    school = user.school
    try:
        teacher = user.teacher_profile
    except ObjectDoesNotExist:
        teacher = None

    name = teacher.full_name if teacher is not None else user.full_name
    email = (teacher.email if teacher is not None else "") or user.email
    photo_url = teacher.photo_url if teacher is not None else ""
    subject = _teacher_primary_subject(teacher, school) if (teacher and school) else ""

    teacher_payload = {
        "id": str(teacher.id) if teacher is not None else str(user.id),
        "name": name,
        "phone": _format_in_phone(user.phone),
        "email": email,
        "subject": subject,
        "school": school.name if school is not None else "",
        "photo_url": photo_url,
    }
    token = issue_tokens_for_user(user)["access_token"]
    return user, {"token": token, "teacher": teacher_payload}


def teacher_refresh(*, user: Any) -> dict[str, Any]:
    """Re-issue a fresh access token for an already-authenticated teacher.

    Called from the ``/auth/refresh`` endpoint which is already protected by
    :data:`teacher_jwt_auth`.  The caller's existing token must still be valid;
    this function simply mints a new one with a fresh expiry so the teacher
    stays logged in without having to re-enter their password.
    """
    from django.core.exceptions import ObjectDoesNotExist

    school = user.school
    try:
        teacher = user.teacher_profile
    except ObjectDoesNotExist:
        teacher = None

    name = teacher.full_name if teacher is not None else user.full_name
    email = (teacher.email if teacher is not None else "") or user.email
    photo_url = teacher.photo_url if teacher is not None else ""
    subject = _teacher_primary_subject(teacher, school) if (teacher and school) else ""

    teacher_payload = {
        "id": str(teacher.id) if teacher is not None else str(user.id),
        "name": name,
        "phone": _format_in_phone(user.phone),
        "email": email,
        "subject": subject,
        "school": school.name if school is not None else "",
        "photo_url": photo_url,
    }
    token = issue_tokens_for_user(user)["access_token"]
    return {"token": token, "teacher": teacher_payload}


def update_teacher_profile(*, user: Any, name: str, email: str) -> dict[str, Any]:
    """Update the teacher's display name and email.

    ``name`` is treated as a full name and split into first/last on the first
    space so the Teacher model's separate columns stay consistent.
    Phone is deliberately not updatable here — it is the login credential and
    can only be changed by a school admin.
    """
    from django.core.exceptions import ObjectDoesNotExist

    name = name.strip()
    email = email.strip()

    try:
        teacher = user.teacher_profile
    except ObjectDoesNotExist as exc:
        raise NotFound("No teacher profile linked to this account.") from exc

    parts = name.split(" ", 1)
    teacher.first_name = parts[0]
    teacher.last_name = parts[1] if len(parts) > 1 else ""
    teacher.email = email
    teacher.save(update_fields=["first_name", "last_name", "email", "updated_at"])

    # Keep User.email in sync so admin views are consistent.
    if user.email != email:
        user.email = email
        user.save(update_fields=["email"])

    school = user.school
    subject = _teacher_primary_subject(teacher, school) if school else ""
    return {
        "id": str(teacher.id),
        "name": teacher.full_name,
        "phone": _format_in_phone(user.phone),
        "email": teacher.email,
        "subject": subject,
        "school": school.name if school else "",
        "photo_url": teacher.photo_url,
    }


def change_teacher_password(*, user: Any, current_password: str, new_password: str) -> None:
    """Verify the current password then set the new one.

    Raises :exc:`~apps.core.exceptions.Unauthorized` when the current password
    is wrong so the caller gets a 401 (not a 422 — the credentials are the
    problem, not the payload shape).
    """
    if not check_user_password(user, current_password):
        raise Unauthorized("Current password is incorrect.")
    user.set_password(new_password)
    user.save(update_fields=["password"])


def find_eligible_teacher(phone: str) -> Any:
    """A teacher is eligible to sign in if an admin has added their phone as an
    active Teacher profile. Queried across tenants because this runs pre-auth
    (no school context yet)."""
    from apps.people.models import Teacher, TeacherStatus

    normalized = normalize_in_phone(phone)
    return (
        Teacher.objects.all_tenants()
        .filter(phone=normalized, status=TeacherStatus.ACTIVE)
        .select_related("school")
        .first()
    )


def send_teacher_otp(phone: str) -> str:
    """Issue an OTP for teacher activation / password reset. Rejects phones not
    registered as a teacher (no self-registration). Returns the plain code for
    the SMS/WhatsApp dispatcher to send."""
    teacher = find_eligible_teacher(phone)
    if teacher is None:
        raise NotFound("No account with that phone number.")
    normalized = normalize_in_phone(phone)
    code = f"{secrets.randbelow(1_000_000):06d}"
    OneTimePassword.objects.create(
        phone=normalized,
        code_hash=_hash_otp(code),
        purpose=TEACHER_OTP_PURPOSE,
        expires_at=timezone.now() + OTP_TTL,
    )
    logger.info("teacher_otp_generated phone=%s teacher_id=%s", normalized, teacher.id)
    if getattr(settings, "WHATSAPP_PROVIDER", "mock") == "mock":
        # No real OTP delivery until Module 5 — surface the code in dev only.
        logger.info("teacher_otp_mock_delivery phone=%s code=%s", normalized, code)
    return code


def activate_or_reset_teacher(phone: str, otp: str, new_password: str) -> User:
    """Verify the OTP and set the teacher's password. On first activation this
    lazily creates the login User and links it to the Teacher profile; on a
    later call it resets the existing teacher's password.

    OTP validation runs *outside* a transaction so the attempts counter
    persists on a wrong guess (the lockout must survive the raise). Only the
    user mutation is wrapped in a transaction.
    """
    normalized = normalize_in_phone(phone)
    record = (
        OneTimePassword.objects.filter(
            phone=normalized, purpose=TEACHER_OTP_PURPOSE, consumed_at__isnull=True
        )
        .order_by("-created_at")
        .first()
    )
    if record is None or not record.is_valid():
        raise InvalidOTP("The OTP you entered is incorrect or has expired.")
    record.attempts += 1
    if record.code_hash != _hash_otp(otp):
        record.save(update_fields=["attempts"])
        raise InvalidOTP("The OTP you entered is incorrect or has expired.")
    record.consumed_at = timezone.now()
    record.save(update_fields=["consumed_at", "attempts"])

    teacher = find_eligible_teacher(normalized)
    if teacher is None:
        raise NotFound("No account with that phone number.")

    existing = User.objects.filter(phone=normalized).first()
    if existing is not None and existing.role != Role.TEACHER:
        raise Conflict("That phone is already in use by another account.")

    with transaction.atomic():
        if existing is not None:
            user = existing
        else:
            user = User(
                phone=normalized,
                role=Role.TEACHER,
                school=teacher.school,
                first_name=teacher.first_name,
                last_name=teacher.last_name,
                email=teacher.email,
                is_active=True,
            )
        user.set_password(new_password)
        user.save()
        if teacher.user_id != user.id:
            teacher.user = user
            teacher.save(update_fields=["user"])
    return user


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
