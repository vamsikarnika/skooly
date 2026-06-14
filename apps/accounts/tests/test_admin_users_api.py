"""HTTP tests for admin user management (skooly-stride Settings → Users)."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.accounts.models import Role, User


@pytest.mark.django_db
def test_list_admins(client: Client, admin_token_a, world_a):
    res = client.get("/api/v1/admin-users", HTTP_AUTHORIZATION=f"Bearer {admin_token_a}")
    assert res.status_code == 200, res.content
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["isCurrent"] is True
    assert rows[0]["isActive"] is True


@pytest.mark.django_db
def test_create_admin_returns_password_and_can_login(client: Client, admin_token_a, world_a):
    res = client.post(
        "/api/v1/admin-users",
        data={"firstName": "Rajesh", "lastName": "Kumar", "phone": "+919000000001", "email": "r@a.com"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    pwd = body["generatedPassword"]
    assert len(pwd) >= 8
    assert body["user"]["fullName"] == "Rajesh Kumar"
    assert body["user"]["isCurrent"] is False

    # The new admin can log in with the generated password.
    login = client.post(
        "/api/v1/auth/login",
        data={"phone": "+919000000001", "password": pwd},
        content_type="application/json",
    )
    assert login.status_code == 200, login.content
    assert login.json()["user"]["role"] == "admin"


@pytest.mark.django_db
def test_create_admin_duplicate_phone_conflict(client: Client, admin_token_a, world_a):
    res = client.post(
        "/api/v1/admin-users",
        data={"firstName": "Dup", "phone": world_a["admin"].phone},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 409


@pytest.mark.django_db
def test_teacher_cannot_create_admin(client: Client, teacher_token_a, world_a):
    res = client.post(
        "/api/v1/admin-users",
        data={"firstName": "X", "phone": "+919000000009"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {teacher_token_a}",
    )
    assert res.status_code == 403


@pytest.mark.django_db
def test_cannot_deactivate_self_or_last_admin(client: Client, admin_token_a, world_a):
    me = world_a["admin"]
    res = client.patch(
        f"/api/v1/admin-users/{me.id}",
        data={"isActive": False},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 422  # self-deactivate blocked


@pytest.mark.django_db
def test_deactivate_other_admin(client: Client, admin_token_a, world_a):
    school = world_a["school"]
    other = User.objects.create_user(
        phone="+919000000050", password="initpass1", school=school,
        role=Role.ADMIN, first_name="Other",
    )
    res = client.patch(
        f"/api/v1/admin-users/{other.id}",
        data={"isActive": False, "email": "other@a.com"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["isActive"] is False
    assert body["email"] == "other@a.com"
