"""End-to-end HTTP tests for the teacher app login endpoint
(POST /api/v1/teacher/auth/login). Exercises success + every error path,
the admin-rejected role lock, and per-school scoping of the result."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.academics.models import TeacherAssignment
from apps.academics.tests.factories import SubjectFactory
from apps.accounts import services
from apps.people.tests.factories import TeacherFactory

LOGIN_URL = "/api/v1/teacher/auth/login"


def _setup_teacher(world: dict, subject_name: str = "Mathematics"):  # type: ignore[no-untyped-def]
    """Give a world's teacher_user a Teacher profile + a current-year
    assignment so the login response can resolve name/subject/school."""
    school = world["school"]
    user = world["teacher_user"]
    teacher = TeacherFactory(
        school=school,
        user=user,
        first_name="Priya",
        last_name="Sharma",
        email="priya.sharma@skooly.in",
        phone=user.phone,
        photo_url="https://cdn.skooly.in/avatars/t1.jpg",
    )
    subject = SubjectFactory(school=school, name=subject_name)
    TeacherAssignment.objects.create(
        school=school,
        teacher=teacher,
        subject=subject,
        section=world["section_a"],
        academic_year=world["year"],
    )
    return teacher, subject


def _post(client: Client, phone: str, password: str):  # type: ignore[no-untyped-def]
    return client.post(
        LOGIN_URL,
        data={"phone": phone, "password": password},
        content_type="application/json",
    )


@pytest.mark.django_db
def test_login_success_returns_token_and_teacher(client, world_a) -> None:
    teacher, _subject = _setup_teacher(world_a)
    res = _post(client, "+911111111102", "testpass123")
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["token"]
    t = body["teacher"]
    assert t["id"] == str(teacher.id)
    assert t["name"] == "Priya Sharma"
    assert t["subject"] == "Mathematics"
    assert t["school"] == "School A"
    assert t["phone"] == "+91 11111 11102"
    assert t["email"] == "priya.sharma@skooly.in"
    assert t["photoUrl"] == "https://cdn.skooly.in/avatars/t1.jpg"  # camelCase


@pytest.mark.django_db
def test_login_accepts_bare_10_digit_phone(client, world_a) -> None:
    _setup_teacher(world_a)
    res = _post(client, "1111111102", "testpass123")
    assert res.status_code == 200, res.content


@pytest.mark.django_db
def test_login_wrong_password_is_401(client, world_a) -> None:
    _setup_teacher(world_a)
    res = _post(client, "+911111111102", "wrongpass")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.django_db
def test_login_unknown_phone_is_404(client, world_a) -> None:
    _setup_teacher(world_a)
    res = _post(client, "+919999999999", "testpass123")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.django_db
def test_login_admin_credentials_rejected(client, world_a) -> None:
    # The admin account exists with this phone+password but role=admin, so the
    # teacher API must not authenticate it — 404, not a token.
    _setup_teacher(world_a)
    res = _post(client, world_a["admin"].phone, "testpass123")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.django_db
def test_login_scopes_result_to_teachers_own_school(client, world_a, world_b) -> None:
    _setup_teacher(world_a, subject_name="Mathematics")
    _setup_teacher(world_b, subject_name="Science")
    res = _post(client, world_b["teacher_user"].phone, "testpass123")
    assert res.status_code == 200, res.content
    t = res.json()["teacher"]
    assert t["school"] == "School B"
    assert t["subject"] == "Science"


@pytest.mark.django_db
def test_login_teacher_without_profile_succeeds(client, world_a) -> None:
    # A teacher User with no linked Teacher profile: login still works, falling
    # back to the user's own name and an empty subject.
    res = _post(client, world_a["teacher_user"].phone, "testpass123")
    assert res.status_code == 200, res.content
    t = res.json()["teacher"]
    assert t["id"] == str(world_a["teacher_user"].id)
    assert t["subject"] == ""
    assert t["school"] == "School A"
    assert t["photoUrl"] == ""


@pytest.mark.django_db
def test_primary_subject_falls_back_when_no_current_year(world_a) -> None:
    teacher, _subject = _setup_teacher(world_a)
    school = world_a["school"]
    school.current_academic_year = None
    school.save(update_fields=["current_academic_year"])
    school.refresh_from_db()
    # No current year set → falls back to the teacher's first assignment.
    assert services._teacher_primary_subject(teacher, school) == "Mathematics"


def test_format_phone_passthrough_when_not_ten_digits() -> None:
    assert services._format_in_phone("+9112345") == "+9112345"


REFRESH_URL = "/api/v1/teacher/auth/refresh"


def _auth_header(client: Client, phone: str, password: str) -> dict:  # type: ignore[no-untyped-def]
    res = _post(client, phone, password)
    assert res.status_code == 200
    return {"HTTP_AUTHORIZATION": f"Bearer {res.json()['token']}"}


@pytest.mark.django_db
def test_refresh_returns_new_token(client, world_a) -> None:
    _setup_teacher(world_a)
    headers = _auth_header(client, "+911111111102", "testpass123")
    res = client.post(REFRESH_URL, content_type="application/json", **headers)
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["token"]
    assert body["teacher"]["name"] == "Priya Sharma"


@pytest.mark.django_db
def test_refresh_without_token_is_401(client) -> None:
    res = client.post(REFRESH_URL, content_type="application/json")
    assert res.status_code == 401


@pytest.mark.django_db
def test_refresh_admin_token_rejected(client, world_a) -> None:
    """Admin tokens must not work on the teacher refresh endpoint."""
    from apps.accounts.services import issue_tokens_for_user
    token = issue_tokens_for_user(world_a["admin"])["access_token"]
    res = client.post(
        REFRESH_URL,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 401
