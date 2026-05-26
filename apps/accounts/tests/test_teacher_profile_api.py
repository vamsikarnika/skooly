"""Tests for PATCH /api/v1/teacher/profile and POST /api/v1/teacher/auth/change-password."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.academics.models import TeacherAssignment
from apps.academics.tests.factories import SubjectFactory
from apps.people.models import Teacher
from apps.people.tests.factories import TeacherFactory

PROFILE_URL = "/api/v1/teacher/profile"         # profile_router mounted at /
CHANGE_PW_URL = "/api/v1/teacher/auth/change-password"  # auth router at /auth/
LOGIN_URL = "/api/v1/teacher/auth/login"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_teacher(world: dict) -> Teacher:
    school = world["school"]
    user = world["teacher_user"]
    teacher = TeacherFactory(
        school=school,
        user=user,
        first_name="Priya",
        last_name="Sharma",
        email="priya@skooly.in",
        phone=user.phone,
    )
    subject = SubjectFactory(school=school, name="Mathematics")
    TeacherAssignment.objects.create(
        school=school,
        teacher=teacher,
        subject=subject,
        section=world["section_a"],
        academic_year=world["year"],
    )
    return teacher


def _token(client: Client, phone: str, password: str = "testpass123") -> str:
    res = client.post(
        LOGIN_URL,
        data={"phone": phone, "password": password},
        content_type="application/json",
    )
    assert res.status_code == 200
    return res.json()["token"]


def _patch(client: Client, token: str, payload: dict):  # type: ignore[no-untyped-def]
    return client.patch(
        PROFILE_URL,
        data=payload,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def _change_pw(client: Client, token: str, current: str, new: str):  # type: ignore[no-untyped-def]
    return client.post(
        CHANGE_PW_URL,
        data={"currentPassword": current, "newPassword": new},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


# ---------------------------------------------------------------------------
# Update profile
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_update_profile_name_and_email(client: Client, world_a: dict) -> None:
    _setup_teacher(world_a)
    token = _token(client, "+911111111102")

    res = _patch(client, token, {"name": "Priya Reddy", "email": "priya.reddy@skooly.in"})
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["name"] == "Priya Reddy"
    assert body["email"] == "priya.reddy@skooly.in"
    assert body["phone"] == "+91 11111 11102"   # phone unchanged

    # Persisted in DB
    teacher = Teacher.objects.all_tenants().get(user=world_a["teacher_user"])
    assert teacher.first_name == "Priya"
    assert teacher.last_name == "Reddy"
    assert teacher.email == "priya.reddy@skooly.in"


@pytest.mark.django_db
def test_update_profile_single_word_name(client: Client, world_a: dict) -> None:
    _setup_teacher(world_a)
    token = _token(client, "+911111111102")
    res = _patch(client, token, {"name": "Priya", "email": "p@x.com"})
    assert res.status_code == 200
    assert res.json()["name"] == "Priya"
    teacher = Teacher.objects.all_tenants().get(user=world_a["teacher_user"])
    assert teacher.last_name == ""


@pytest.mark.django_db
def test_update_profile_requires_auth(client: Client) -> None:
    res = client.patch(
        PROFILE_URL,
        data={"name": "X", "email": "x@x.com"},
        content_type="application/json",
    )
    assert res.status_code == 401


@pytest.mark.django_db
def test_update_profile_missing_name_is_422(client: Client, world_a: dict) -> None:
    _setup_teacher(world_a)
    token = _token(client, "+911111111102")
    res = _patch(client, token, {"email": "x@x.com"})   # no name
    assert res.status_code == 422


@pytest.mark.django_db
def test_update_profile_cross_tenant_isolation(
    client: Client, world_a: dict, world_b: dict
) -> None:
    """Teacher from school A cannot affect school B's data."""
    _setup_teacher(world_a)
    teacher_b = _setup_teacher(world_b)
    original_email = teacher_b.email

    token_a = _token(client, world_a["teacher_user"].phone)
    # This updates school A's teacher — school B's record is untouched.
    _patch(client, token_a, {"name": "Hacker", "email": "evil@bad.com"})

    teacher_b.refresh_from_db()
    assert teacher_b.email == original_email


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_change_password_success(client: Client, world_a: dict) -> None:
    _setup_teacher(world_a)
    token = _token(client, "+911111111102")

    res = _change_pw(client, token, "testpass123", "newpass999")
    assert res.status_code == 200, res.content
    assert "successfully" in res.json()["message"].lower()

    # Can now log in with the new password.
    res2 = client.post(
        LOGIN_URL,
        data={"phone": "+911111111102", "password": "newpass999"},
        content_type="application/json",
    )
    assert res2.status_code == 200


@pytest.mark.django_db
def test_change_password_wrong_current_is_401(client: Client, world_a: dict) -> None:
    _setup_teacher(world_a)
    token = _token(client, "+911111111102")
    res = _change_pw(client, token, "wrongpassword", "newpass999")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.django_db
def test_change_password_too_short_is_422(client: Client, world_a: dict) -> None:
    _setup_teacher(world_a)
    token = _token(client, "+911111111102")
    res = _change_pw(client, token, "testpass123", "abc")   # < 6 chars
    assert res.status_code == 422


@pytest.mark.django_db
def test_change_password_requires_auth(client: Client) -> None:
    res = client.post(
        CHANGE_PW_URL,
        data={"currentPassword": "testpass123", "newPassword": "newpass999"},
        content_type="application/json",
    )
    assert res.status_code == 401
