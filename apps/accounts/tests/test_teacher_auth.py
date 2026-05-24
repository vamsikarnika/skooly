"""Foundation tests for the teacher API: the role-locked auth class, the
get_teacher profile resolver, and that the teacher NinjaAPI is mounted at
/api/v1/teacher/ without shadowing the admin API."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import Client, RequestFactory
from ninja_jwt.exceptions import InvalidToken

from apps.accounts.services import issue_tokens_for_user
from apps.accounts.teacher_auth import TeacherJWTAuth, get_teacher
from apps.core.exceptions import NotFound
from apps.people.tests.factories import TeacherFactory


def _access_token(user) -> str:  # type: ignore[no-untyped-def]
    return issue_tokens_for_user(user)["access_token"]


@pytest.mark.django_db
def test_teacher_api_mounted_and_admin_not_shadowed() -> None:
    client = Client()

    teacher_doc = client.get("/api/v1/teacher/openapi.json")
    assert teacher_doc.status_code == 200, teacher_doc.content
    assert teacher_doc.json()["info"]["title"] == "Skooly Teacher API"

    # The broader /api/v1/ prefix still resolves to the admin API and was not
    # swallowed by the teacher mount (and vice versa).
    admin_doc = client.get("/api/v1/openapi.json")
    assert admin_doc.status_code == 200, admin_doc.content
    assert admin_doc.json()["info"]["title"] == "Skooly API"


@pytest.mark.django_db
def test_teacher_auth_accepts_teacher_token(world_a) -> None:
    token = _access_token(world_a["teacher_user"])
    request = RequestFactory().get("/api/v1/teacher/")
    resolved = TeacherJWTAuth().authenticate(request, token)
    assert resolved is not None
    assert resolved.id == world_a["teacher_user"].id


@pytest.mark.django_db
def test_teacher_auth_rejects_admin_token(world_a) -> None:
    token = _access_token(world_a["admin"])
    request = RequestFactory().get("/api/v1/teacher/")
    assert TeacherJWTAuth().authenticate(request, token) is None


@pytest.mark.django_db
def test_teacher_auth_rejects_garbage_token() -> None:
    # ninja_jwt raises InvalidToken for a malformed token; Ninja turns that
    # into a 401 at the endpoint. Either way the caller is not authenticated.
    request = RequestFactory().get("/api/v1/teacher/")
    with pytest.raises(InvalidToken):
        TeacherJWTAuth().authenticate(request, "not-a-real-token")


@pytest.mark.django_db
def test_teacher_auth_returns_none_when_base_auth_returns_none() -> None:
    # Defensive branch: if the base JWTAuth resolves no user (rather than
    # raising), TeacherJWTAuth must also yield None — never an AttributeError.
    request = RequestFactory().get("/api/v1/teacher/")
    with patch("apps.accounts.auth.JWTAuth.authenticate", return_value=None):
        assert TeacherJWTAuth().authenticate(request, "whatever") is None


@pytest.mark.django_db
def test_get_teacher_returns_linked_profile(world_a) -> None:
    user = world_a["teacher_user"]
    teacher = TeacherFactory(school=world_a["school"], user=user)
    request = RequestFactory().get("/api/v1/teacher/")
    request.auth = user  # type: ignore[attr-defined]
    assert get_teacher(request).id == teacher.id


@pytest.mark.django_db
def test_get_teacher_without_profile_raises_404(world_a) -> None:
    request = RequestFactory().get("/api/v1/teacher/")
    request.auth = world_a["teacher_user"]  # type: ignore[attr-defined]
    with pytest.raises(NotFound):
        get_teacher(request)
