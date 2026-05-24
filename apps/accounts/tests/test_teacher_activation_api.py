"""End-to-end HTTP tests for teacher activation / first sign-in.

Flow: admin adds a Teacher profile (no login) -> teacher does otp/send ->
otp/verify lazily creates the User + sets password -> login works.
Covers the CU acceptance criteria incl. cross-tenant scoping and edge cases.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import OneTimePassword, Role, User
from apps.accounts.services import TEACHER_OTP_PURPOSE, _hash_otp
from apps.people.tests.factories import TeacherFactory

OTP_SEND = "/api/v1/teacher/auth/otp/send"
OTP_VERIFY = "/api/v1/teacher/auth/otp/verify"
LOGIN = "/api/v1/teacher/auth/login"

PHONE_10 = "9876512345"
PHONE_91 = "+919876512345"


def _add_teacher_profile(world: dict, phone: str = PHONE_91, **extra):  # type: ignore[no-untyped-def]
    return TeacherFactory(
        school=world["school"], first_name="Ravi", last_name="Kumar", phone=phone, **extra
    )


def _fixed_otp(monkeypatch, code: int = 123456) -> str:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("apps.accounts.services.secrets.randbelow", lambda _n: code)
    return f"{code:06d}"


def _send(client: Client, phone: str):  # type: ignore[no-untyped-def]
    return client.post(OTP_SEND, data={"phone": phone}, content_type="application/json")


def _verify(client: Client, phone: str, otp: str, new_password: str):  # type: ignore[no-untyped-def]
    return client.post(
        OTP_VERIFY,
        data={"phone": phone, "otp": otp, "newPassword": new_password},
        content_type="application/json",
    )


def _login(client: Client, phone: str, password: str):  # type: ignore[no-untyped-def]
    return client.post(
        LOGIN, data={"phone": phone, "password": password}, content_type="application/json"
    )


@pytest.mark.django_db
def test_otp_send_eligible_teacher_200(client, world_a) -> None:
    _add_teacher_profile(world_a)
    res = _send(client, PHONE_10)
    assert res.status_code == 200, res.content
    assert res.json()["message"] == "OTP sent"
    assert OneTimePassword.objects.filter(phone=PHONE_91, purpose=TEACHER_OTP_PURPOSE).count() == 1


@pytest.mark.django_db
def test_otp_send_unknown_phone_404(client, world_a) -> None:
    _add_teacher_profile(world_a)
    res = _send(client, "9999999999")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.django_db
def test_full_activation_chain(client, world_a, monkeypatch) -> None:
    teacher = _add_teacher_profile(world_a)
    assert teacher.user_id is None  # admin-added, no login yet

    otp = _fixed_otp(monkeypatch)
    assert _send(client, PHONE_10).status_code == 200

    res = _verify(client, PHONE_10, otp, "newpass123")
    assert res.status_code == 200, res.content
    assert res.json()["message"] == "Password reset successful"

    # User was lazily created, linked, scoped to the teacher's school.
    teacher.refresh_from_db()
    assert teacher.user_id is not None
    user = User.objects.get(id=teacher.user_id)
    assert user.role == Role.TEACHER
    assert user.school_id == world_a["school"].id
    assert user.phone == PHONE_91

    # And the teacher can now log in with the password they just set.
    login = _login(client, PHONE_10, "newpass123")
    assert login.status_code == 200, login.content
    assert login.json()["token"]
    assert login.json()["teacher"]["school"] == "School A"


@pytest.mark.django_db
def test_otp_verify_wrong_code_400(client, world_a, monkeypatch) -> None:
    _add_teacher_profile(world_a)
    _fixed_otp(monkeypatch)
    _send(client, PHONE_10)
    res = _verify(client, PHONE_10, "000000", "newpass123")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_OTP"


@pytest.mark.django_db
def test_otp_verify_expired_400(client, world_a) -> None:
    _add_teacher_profile(world_a)
    OneTimePassword.objects.create(
        phone=PHONE_91,
        code_hash=_hash_otp("123456"),
        purpose=TEACHER_OTP_PURPOSE,
        expires_at=timezone.now() - timedelta(minutes=1),
    )
    res = _verify(client, PHONE_10, "123456", "newpass123")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_OTP"
    assert not User.objects.filter(phone=PHONE_91).exists()


@pytest.mark.django_db
def test_otp_attempts_lockout(client, world_a, monkeypatch) -> None:
    _add_teacher_profile(world_a)
    otp = _fixed_otp(monkeypatch)
    _send(client, PHONE_10)
    for _ in range(5):
        assert _verify(client, PHONE_10, "000000", "newpass123").status_code == 400
    # Even the correct code is now rejected — the OTP is locked after 5 attempts.
    assert _verify(client, PHONE_10, otp, "newpass123").status_code == 400
    assert not User.objects.filter(phone=PHONE_91).exists()


@pytest.mark.django_db
def test_activation_scoped_to_teachers_own_school(client, world_a, world_b, monkeypatch) -> None:
    _add_teacher_profile(world_a)
    _add_teacher_profile(world_b, phone="+919812300000")
    otp = _fixed_otp(monkeypatch)
    _send(client, "9812300000")
    assert _verify(client, "9812300000", otp, "newpass123").status_code == 200

    user = User.objects.get(phone="+919812300000")
    assert user.school_id == world_b["school"].id
    assert _login(client, "9812300000", "newpass123").json()["teacher"]["school"] == "School B"


@pytest.mark.django_db
def test_reverify_resets_password(client, world_a, monkeypatch) -> None:
    _add_teacher_profile(world_a)
    otp1 = _fixed_otp(monkeypatch, 111111)
    _send(client, PHONE_10)
    _verify(client, PHONE_10, otp1, "firstpass1")
    assert _login(client, PHONE_10, "firstpass1").status_code == 200

    otp2 = _fixed_otp(monkeypatch, 222222)
    _send(client, PHONE_10)
    assert _verify(client, PHONE_10, otp2, "secondpass2").status_code == 200

    assert _login(client, PHONE_10, "secondpass2").status_code == 200
    assert _login(client, PHONE_10, "firstpass1").status_code == 401  # old password dead
    # Still exactly one user for this phone — reset, not duplicate.
    assert User.objects.filter(phone=PHONE_91).count() == 1


@pytest.mark.django_db
def test_phone_owned_by_non_teacher_user_conflicts(client, world_a, monkeypatch) -> None:
    # The admin's phone also happens to be added as a Teacher profile. Activation
    # must refuse to hijack the admin account.
    admin_phone = world_a["admin"].phone
    _add_teacher_profile(world_a, phone=admin_phone)
    otp = _fixed_otp(monkeypatch)
    assert _send(client, admin_phone).status_code == 200
    res = _verify(client, admin_phone, otp, "newpass123")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "CONFLICT"
    # Admin account untouched.
    assert User.objects.get(phone=admin_phone).role == Role.ADMIN


@pytest.mark.django_db
def test_otp_send_requires_active_profile(client, world_a, monkeypatch) -> None:
    # An inactive teacher profile is not eligible to sign in.
    _add_teacher_profile(world_a, status="inactive")
    assert _send(client, PHONE_10).status_code == 404


@pytest.mark.django_db
def test_otp_verify_after_profile_deactivated_404(client, world_a, monkeypatch) -> None:
    # Profile deactivated between otp/send and otp/verify -> no longer eligible.
    teacher = _add_teacher_profile(world_a)
    otp = _fixed_otp(monkeypatch)
    _send(client, PHONE_10)
    teacher.status = "inactive"
    teacher.save(update_fields=["status"])
    res = _verify(client, PHONE_10, otp, "newpass123")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"
    assert not User.objects.filter(phone=PHONE_91).exists()
