"""Parent-app (skooly-parent) auth + bootstrap business logic.

Parents authenticate with a phone + OTP (no password). On first verify the
login ``User`` (role=parent) is created lazily and linked to the pre-seeded
``Parent`` profile, mirroring the teacher activation flow.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import OneTimePassword, Role, User
from apps.accounts.services import (
    _format_in_phone,
    _hash_otp,
    issue_tokens_for_user,
    normalize_in_phone,
)
from apps.core.context import use_school
from apps.core.exceptions import Conflict, InvalidOTP, NotFound

logger = logging.getLogger(__name__)

PARENT_OTP_PURPOSE = "parent_login"
OTP_TTL_SECONDS = 60 * 10  # 10 minutes; the app shows a 60s resend timer.

# Dev convenience: with the mock WhatsApp provider there is no real OTP
# delivery, so we accept a fixed code (matches the login screen's hint).
# Gated on the mock provider — real BSP providers never enable this.
DEV_MASTER_OTP = "123456"


def _dev_otp_enabled() -> bool:
    return getattr(settings, "WHATSAPP_PROVIDER", "mock") == "mock"

# Deterministic avatar palette. Returned as a ready-to-use Tailwind class so the
# app can drop it straight into className (the frontend never maps colours).
_AVATAR_COLORS = [
    "bg-violet-500",
    "bg-rose-500",
    "bg-sky-500",
    "bg-emerald-500",
    "bg-amber-500",
    "bg-indigo-500",
    "bg-teal-500",
    "bg-pink-500",
]


def _initials(name: str) -> str:
    parts = [p for p in name.strip().split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _avatar_color(student_id: int) -> str:
    return _AVATAR_COLORS[student_id % len(_AVATAR_COLORS)]


def find_eligible_parent(phone: str) -> Any:
    """Locate a parent profile by phone across tenants (runs pre-auth, before
    any school context is set)."""
    from apps.people.models import Parent

    normalized = normalize_in_phone(phone)
    return (
        Parent.objects.all_tenants()
        .filter(phone=normalized)
        .select_related("school")
        .first()
    )


def send_parent_otp(phone: str) -> str:
    """Issue an OTP for parent login. Rejects phones not registered against any
    school's parent registry. Returns the plain code for the dispatcher."""
    parent = find_eligible_parent(phone)
    if parent is None:
        raise NotFound("No parent account found for this number.")
    normalized = normalize_in_phone(phone)
    code = f"{secrets.randbelow(1_000_000):06d}"
    OneTimePassword.objects.create(
        phone=normalized,
        code_hash=_hash_otp(code),
        purpose=PARENT_OTP_PURPOSE,
        expires_at=timezone.now() + timezone.timedelta(seconds=OTP_TTL_SECONDS),
    )
    logger.info("parent_otp_generated phone=%s parent_id=%s", normalized, parent.id)
    if getattr(settings, "WHATSAPP_PROVIDER", "mock") == "mock":
        # No real OTP delivery until Module 5 — surface the code in dev only.
        logger.info("parent_otp_mock_delivery phone=%s code=%s", normalized, code)
    return code


def verify_parent_otp(phone: str, otp: str) -> dict[str, Any]:
    """Validate the OTP, lazily create+link the login User, and return the
    bootstrap payload (token + parent + children) in one round-trip.

    OTP validation runs outside the transaction so the attempts counter
    persists on a wrong guess (the lockout must survive the raise)."""
    normalized = normalize_in_phone(phone)

    # Dev master code (mock provider only) — skips the per-send record check so
    # logging in never depends on chasing the latest logged code.
    if _dev_otp_enabled() and otp == DEV_MASTER_OTP:
        logger.info("parent_otp_dev_master_used phone=%s", normalized)
    else:
        record = (
            OneTimePassword.objects.filter(
                phone=normalized, purpose=PARENT_OTP_PURPOSE, consumed_at__isnull=True
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

    parent = find_eligible_parent(normalized)
    if parent is None:
        raise NotFound("No parent account found for this number.")

    existing = User.objects.filter(phone=normalized).first()
    if existing is not None and existing.role != Role.PARENT:
        raise Conflict("That phone is already in use by another account.")

    with transaction.atomic():
        if existing is not None:
            user = existing
        else:
            user = User(
                phone=normalized,
                role=Role.PARENT,
                school=parent.school,
                first_name=parent.name.split(" ", 1)[0],
                last_name=parent.name.split(" ", 1)[1] if " " in parent.name else "",
                email=parent.email,
                is_active=True,
            )
            user.set_unusable_password()
            user.save()
        if parent.user_id != user.id:
            parent.user = user
            parent.save(update_fields=["user"])

    user.touch_last_login()
    token = issue_tokens_for_user(user)["access_token"]
    # This endpoint is unauthenticated, so no tenant context was pinned by the
    # JWT middleware — set it explicitly so the children query is not fail-closed.
    with use_school(parent.school):
        return {
            "token": token,
            "parent": build_parent_payload(parent),
            "children": build_children_payload(parent),
        }


def parent_refresh(*, user: Any) -> dict[str, str]:
    """Re-issue a fresh access token for an already-authenticated parent."""
    return {"token": issue_tokens_for_user(user)["access_token"]}


def build_parent_payload(parent: Any) -> dict[str, Any]:
    return {
        "id": parent.id,
        "name": parent.name,
        "phone": _format_in_phone(parent.phone),
        "email": parent.email,
    }


def build_child_payload(student: Any, school: Any) -> dict[str, Any]:
    """One child row matching the app's Child shape. Resolves the student's
    current-year enrollment for class/section/roll."""
    section = None
    roll_no: int | None = None
    year_id = school.current_academic_year_id if school else None
    enrollment = (
        student.enrollments.filter(status="active")
        .select_related("section__class_obj")
        .order_by("-academic_year_id")
    )
    if year_id is not None:
        current = enrollment.filter(academic_year_id=year_id).first()
        enroll = current or enrollment.first()
    else:
        enroll = enrollment.first()
    if enroll is not None:
        section = enroll.section
        roll_no = int(enroll.roll_number) if enroll.roll_number.isdigit() else None

    return {
        "id": student.id,
        "name": student.full_name,
        "class_": section.class_obj.name if section else "",
        "section": section.name if section else "",
        "roll_no": roll_no,
        "admission_no": student.admission_number,
        "school": school.name if school else "",
        "photo_initials": _initials(student.full_name),
        "photo_color": _avatar_color(student.id),
    }


def build_children_payload(parent: Any) -> list[dict[str, Any]]:
    school = parent.school
    students = (
        parent.students.filter(status="active")
        .prefetch_related("enrollments__section__class_obj")
        .order_by("id")
    )
    return [build_child_payload(s, school) for s in students]


def get_parent_me(*, user: Any) -> dict[str, Any]:
    try:
        parent = user.parent_profile
    except ObjectDoesNotExist as exc:
        raise NotFound("No parent profile linked to this account.") from exc
    payload = build_parent_payload(parent)
    payload["children"] = build_children_payload(parent)
    return payload
