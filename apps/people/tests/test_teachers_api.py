"""Teacher write endpoints — CRUD + tenant isolation."""

from __future__ import annotations

import pytest

from apps.people.tests.factories import TeacherFactory


@pytest.mark.django_db
def test_create_teacher(client, admin_token_a):
    res = client.post(
        "/api/v1/teachers",
        data={
            "firstName": "Lakshmi", "lastName": "Devi",
            "phone": "+919999000001",
            "qualification": "M.Sc., B.Ed.",
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    assert res.json()["phone"] == "+919999000001"


@pytest.mark.django_db
def test_create_teacher_rejects_duplicate_phone(client, admin_token_a, world_a):
    TeacherFactory(school=world_a["school"], phone="+919999000002")
    res = client.post(
        "/api/v1/teachers",
        data={"firstName": "Dup", "phone": "+919999000002"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 409


@pytest.mark.django_db
def test_update_teacher_cross_tenant_404(client, admin_token_a, world_b):
    teacher = TeacherFactory(school=world_b["school"], phone="+919999000099")
    res = client.patch(
        f"/api/v1/teachers/{teacher.id}",
        data={"qualification": "hacked"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_delete_teacher_marks_inactive(client, admin_token_a, world_a):
    """Marking inactive is operational — teacher stays queryable under
    status=inactive filter. deleted_at is not set."""
    teacher = TeacherFactory(school=world_a["school"], phone="+919999000003")
    res = client.delete(
        f"/api/v1/teachers/{teacher.id}",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200
    teacher.refresh_from_db()
    assert teacher.status == "inactive"
    assert teacher.deleted_at is None  # not soft-deleted

    # Filter by inactive → teacher should appear.
    res = client.get(
        "/api/v1/teachers?status=inactive",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200
    ids = {t["id"] for t in res.json()["items"]}
    assert teacher.id in ids


@pytest.mark.django_db
@pytest.mark.parametrize("bad_phone", [
    "9876543210",        # missing +91
    "+9198765432",       # too short
    "+919876543210x",    # trailing char
    "+91 9876543210",    # space not allowed
    "+9198765432101",    # too long
    "+929876543210",     # wrong country code
])
def test_create_teacher_rejects_invalid_phone(client, admin_token_a, bad_phone):
    res = client.post(
        "/api/v1/teachers",
        data={"firstName": "Test", "phone": bad_phone},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 422


@pytest.mark.django_db
def test_create_teacher_accepts_valid_phone(client, admin_token_a):
    res = client.post(
        "/api/v1/teachers",
        data={"firstName": "Test", "phone": "+919876543210"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200


@pytest.mark.django_db
def test_teacher_cannot_create_teacher(client, teacher_token_a):
    res = client.post(
        "/api/v1/teachers",
        data={"firstName": "Forbidden", "phone": "+919999000004"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {teacher_token_a}",
    )
    assert res.status_code == 403


@pytest.mark.django_db
def test_reset_teacher_password_creates_login(client, admin_token_a, world_a):
    """Admin generates a first-login password; the teacher (who had no User
    yet) can then sign in with it."""
    teacher = TeacherFactory(school=world_a["school"], phone="+919999000050")
    assert teacher.user is None

    res = client.post(
        f"/api/v1/teachers/{teacher.id}/reset-password",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    password = res.json()["password"]
    assert len(password) >= 8

    teacher.refresh_from_db()
    assert teacher.user is not None  # login account created on demand

    # The generated password actually works at the teacher login.
    login = client.post(
        "/api/v1/teacher/auth/login",
        data={"phone": "+919999000050", "password": password},
        content_type="application/json",
    )
    assert login.status_code == 200, login.content


@pytest.mark.django_db
def test_reset_teacher_password_regenerates(client, admin_token_a, world_a):
    """Calling twice yields a different password and the old one stops working."""
    teacher = TeacherFactory(school=world_a["school"], phone="+919999000051")
    first = client.post(
        f"/api/v1/teachers/{teacher.id}/reset-password",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    ).json()["password"]
    second = client.post(
        f"/api/v1/teachers/{teacher.id}/reset-password",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    ).json()["password"]
    assert first != second

    stale = client.post(
        "/api/v1/teacher/auth/login",
        data={"phone": "+919999000051", "password": first},
        content_type="application/json",
    )
    assert stale.status_code != 200


@pytest.mark.django_db
def test_reset_teacher_password_cross_tenant_404(client, admin_token_a, world_b):
    teacher = TeacherFactory(school=world_b["school"], phone="+919999000052")
    res = client.post(
        f"/api/v1/teachers/{teacher.id}/reset-password",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_teacher_cannot_reset_password(client, teacher_token_a, world_a):
    teacher = TeacherFactory(school=world_a["school"], phone="+919999000053")
    res = client.post(
        f"/api/v1/teachers/{teacher.id}/reset-password",
        HTTP_AUTHORIZATION=f"Bearer {teacher_token_a}",
    )
    assert res.status_code == 403


@pytest.mark.django_db
def test_reset_teacher_password_disabled_by_flag(client, admin_token_a, world_a, settings):
    """The temporary feature can be switched off via TEACHER_PASSWORD_PROVISIONING."""
    settings.TEACHER_PASSWORD_PROVISIONING = False
    teacher = TeacherFactory(school=world_a["school"], phone="+919999000054")
    res = client.post(
        f"/api/v1/teachers/{teacher.id}/reset-password",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404
