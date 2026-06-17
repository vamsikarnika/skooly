"""API tests for auth endpoints."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.accounts.tests.factories import UserFactory
from apps.schools.models import School


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def admin_user(db) -> User:
    return UserFactory(phone="+919999999999")


SIGNUP_PAYLOAD = {
    "schoolName": "Sunrise School",
    "board": "AP_STATE",
    "address": "12 Main St",
    "academicYearLabel": "2025-26",
    "academicYearStart": "2025-06-01",
    "academicYearEnd": "2026-04-30",
    "adminFirstName": "Vamsi",
    "adminLastName": "Krishna",
    "adminPhone": "+919876543210",
    "adminEmail": "vamsi@sunrise.edu",
    "adminPassword": "supersecret123",
}


@pytest.mark.django_db
def test_signup_creates_school_and_admin(client: Client) -> None:
    res = client.post("/api/v1/auth/signup", data=SIGNUP_PAYLOAD, content_type="application/json")
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["user"]["phone"] == "+919876543210"
    assert body["school"]["name"] == "Sunrise School"
    assert "accessToken" in body and "refreshToken" in body
    assert School.objects.count() == 1
    assert User.objects.count() == 1


@pytest.mark.django_db
def test_signup_rejects_duplicate_phone(client: Client) -> None:
    client.post("/api/v1/auth/signup", data=SIGNUP_PAYLOAD, content_type="application/json")
    res = client.post("/api/v1/auth/signup", data=SIGNUP_PAYLOAD, content_type="application/json")
    assert res.status_code == 409, res.content
    assert res.json()["error"]["code"] == "CONFLICT"


@pytest.mark.django_db
def test_signup_validates_required_fields(client: Client) -> None:
    bad = {**SIGNUP_PAYLOAD, "adminPassword": "short"}
    res = client.post("/api/v1/auth/signup", data=bad, content_type="application/json")
    assert res.status_code == 422


@pytest.mark.django_db
def test_signup_blocked_without_token_when_secret_set(client: Client, settings) -> None:
    settings.SIGNUP_SECRET = "topsecret"
    res = client.post("/api/v1/auth/signup", data=SIGNUP_PAYLOAD, content_type="application/json")
    assert res.status_code == 403, res.content
    assert res.json()["error"]["code"] == "FORBIDDEN"
    assert School.objects.count() == 0


@pytest.mark.django_db
def test_signup_allowed_with_correct_token(client: Client, settings) -> None:
    settings.SIGNUP_SECRET = "topsecret"
    res = client.post(
        "/api/v1/auth/signup",
        data=SIGNUP_PAYLOAD,
        content_type="application/json",
        headers={"X-Signup-Token": "topsecret"},
    )
    assert res.status_code == 200, res.content
    assert School.objects.count() == 1


@pytest.mark.django_db
def test_login_success(client: Client, admin_user: User) -> None:
    res = client.post(
        "/api/v1/auth/login",
        data={"phone": admin_user.phone, "password": "testpass123"},
        content_type="application/json",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["user"]["phone"] == admin_user.phone
    assert body["accessToken"]
    assert body["refreshToken"]


@pytest.mark.django_db
def test_login_wrong_password(client: Client, admin_user: User) -> None:
    res = client.post(
        "/api/v1/auth/login",
        data={"phone": admin_user.phone, "password": "nope"},
        content_type="application/json",
    )
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.django_db
def test_login_inactive_user(client: Client, admin_user: User) -> None:
    admin_user.is_active = False
    admin_user.save()
    res = client.post(
        "/api/v1/auth/login",
        data={"phone": admin_user.phone, "password": "testpass123"},
        content_type="application/json",
    )
    assert res.status_code == 401


@pytest.mark.django_db
def test_refresh_rotates_tokens(client: Client, admin_user: User) -> None:
    login = client.post(
        "/api/v1/auth/login",
        data={"phone": admin_user.phone, "password": "testpass123"},
        content_type="application/json",
    ).json()
    res = client.post(
        "/api/v1/auth/refresh",
        data={"refreshToken": login["refreshToken"]},
        content_type="application/json",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["accessToken"] != login["accessToken"]


@pytest.mark.django_db
def test_refresh_rejects_invalid_token(client: Client) -> None:
    res = client.post(
        "/api/v1/auth/refresh",
        data={"refreshToken": "not-a-real-token"},
        content_type="application/json",
    )
    assert res.status_code == 401


@pytest.mark.django_db
def test_me_requires_auth(client: Client) -> None:
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401


@pytest.mark.django_db
def test_me_returns_user_and_school(client: Client, admin_user: User) -> None:
    login = client.post(
        "/api/v1/auth/login",
        data={"phone": admin_user.phone, "password": "testpass123"},
        content_type="application/json",
    ).json()
    res = client.get(
        "/api/v1/auth/me",
        HTTP_AUTHORIZATION=f"Bearer {login['accessToken']}",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["user"]["phone"] == admin_user.phone
    assert body["school"]["id"] == admin_user.school_id
    assert "students.read" in body["permissions"]


@pytest.mark.django_db
def test_forgot_password_returns_uniform_response(client: Client, admin_user: User) -> None:
    res = client.post(
        "/api/v1/auth/forgot-password",
        data={"phone": admin_user.phone},
        content_type="application/json",
    )
    assert res.status_code == 200
    assert res.json()["success"] is True

    res2 = client.post(
        "/api/v1/auth/forgot-password",
        data={"phone": "+919000000000"},
        content_type="application/json",
    )
    assert res2.status_code == 200
    # Same shape — we don't leak whether the phone exists.
    assert res2.json()["success"] is True


@pytest.mark.django_db
def test_password_reset_full_flow(client: Client, admin_user: User) -> None:
    from apps.accounts import services

    otp = services.request_password_reset_otp(admin_user.phone)
    verify = client.post(
        "/api/v1/auth/verify-otp",
        data={"phone": admin_user.phone, "otp": otp},
        content_type="application/json",
    )
    assert verify.status_code == 200, verify.content
    reset_token = verify.json()["resetToken"]

    reset = client.post(
        "/api/v1/auth/reset-password",
        data={"resetToken": reset_token, "newPassword": "newsecret123"},
        content_type="application/json",
    )
    assert reset.status_code == 200

    # Old password no longer works
    bad = client.post(
        "/api/v1/auth/login",
        data={"phone": admin_user.phone, "password": "testpass123"},
        content_type="application/json",
    )
    assert bad.status_code == 401

    good = client.post(
        "/api/v1/auth/login",
        data={"phone": admin_user.phone, "password": "newsecret123"},
        content_type="application/json",
    )
    assert good.status_code == 200


@pytest.mark.django_db
def test_password_reset_wrong_otp(client: Client, admin_user: User) -> None:
    from apps.accounts import services

    services.request_password_reset_otp(admin_user.phone)
    res = client.post(
        "/api/v1/auth/verify-otp",
        data={"phone": admin_user.phone, "otp": "000000"},
        content_type="application/json",
    )
    assert res.status_code == 401
