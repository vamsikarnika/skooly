"""API tests for /api/v1/schools/* including cross-tenant isolation."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.accounts.models import Role
from apps.accounts.tests.factories import UserFactory
from apps.schools.models import AcademicYear, School
from apps.schools.tests.factories import AcademicYearFactory, SchoolFactory


def _login(client: Client, user) -> str:
    res = client.post(
        "/api/v1/auth/login",
        data={"phone": user.phone, "password": "testpass123"},
        content_type="application/json",
    )
    return res.json()["accessToken"]


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def school_a(db) -> School:
    school = SchoolFactory(name="School A")
    AcademicYearFactory(school=school, label="2025-26", is_current=True)
    return school


@pytest.fixture
def school_b(db) -> School:
    school = SchoolFactory(name="School B")
    AcademicYearFactory(school=school, label="2025-26", is_current=True)
    return school


@pytest.fixture
def admin_a(school_a) -> object:
    return UserFactory(school=school_a, phone="+911111111111", role=Role.ADMIN)


@pytest.fixture
def admin_b(school_b) -> object:
    return UserFactory(school=school_b, phone="+912222222222", role=Role.ADMIN)


@pytest.fixture
def teacher_a(school_a) -> object:
    return UserFactory(school=school_a, phone="+913333333333", role=Role.TEACHER)


@pytest.mark.django_db
def test_get_current_school(client: Client, admin_a) -> None:
    token = _login(client, admin_a)
    res = client.get("/api/v1/schools/current", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["name"] == "School A"
    assert body["currentAcademicYear"]["label"] == "2025-26"


@pytest.mark.django_db
def test_get_current_school_requires_auth(client: Client) -> None:
    res = client.get("/api/v1/schools/current")
    assert res.status_code == 401


@pytest.mark.django_db
def test_patch_school_admin_only(client: Client, teacher_a) -> None:
    token = _login(client, teacher_a)
    res = client.patch(
        "/api/v1/schools/current",
        data={"name": "Hacked"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 403, res.content


@pytest.mark.django_db
def test_patch_school_updates_fields(client: Client, admin_a) -> None:
    token = _login(client, admin_a)
    res = client.patch(
        "/api/v1/schools/current",
        data={"name": "School A Renamed", "primaryColor": "#ff0000"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["name"] == "School A Renamed"
    assert body["primaryColor"] == "#ff0000"


@pytest.mark.django_db
def test_list_academic_years(client: Client, admin_a, school_a) -> None:
    AcademicYearFactory(school=school_a, label="2024-25", is_current=False)
    token = _login(client, admin_a)
    res = client.get("/api/v1/schools/academic-years", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 2
    labels = {y["label"] for y in items}
    assert labels == {"2024-25", "2025-26"}


@pytest.mark.django_db
def test_create_academic_year_sets_current(client: Client, admin_a, school_a) -> None:
    token = _login(client, admin_a)
    res = client.post(
        "/api/v1/schools/academic-years",
        data={
            "label": "2026-27",
            "startDate": "2026-06-01",
            "endDate": "2027-04-30",
            "isCurrent": True,
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 200, res.content
    # Old current is no longer current.
    assert AcademicYear.objects.filter(school=school_a, is_current=True).count() == 1
    school_a.refresh_from_db()
    assert school_a.current_academic_year.label == "2026-27"


@pytest.mark.django_db
def test_cross_tenant_isolation_get_school(client: Client, admin_a, admin_b, school_a, school_b) -> None:
    """Admin from School B logging in must not see School A's data."""
    token_b = _login(client, admin_b)
    res = client.get("/api/v1/schools/current", HTTP_AUTHORIZATION=f"Bearer {token_b}")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == school_b.id
    assert body["name"] == "School B"
    assert body["id"] != school_a.id


@pytest.mark.django_db
def test_cross_tenant_isolation_academic_years(client: Client, admin_a, admin_b, school_a, school_b) -> None:
    """Years listed must be scoped to the requester's school."""
    AcademicYearFactory(school=school_a, label="A-2024", is_current=False)
    AcademicYearFactory(school=school_b, label="B-2024", is_current=False)

    token_a = _login(client, admin_a)
    res = client.get("/api/v1/schools/academic-years", HTTP_AUTHORIZATION=f"Bearer {token_a}")
    labels = {y["label"] for y in res.json()}
    assert "A-2024" in labels
    assert "B-2024" not in labels


@pytest.mark.django_db
def test_cross_tenant_isolation_year_patch(client: Client, admin_a, school_b) -> None:
    """Admin from A trying to patch a year that belongs to school B → 404 (not 403)."""
    foreign_year = AcademicYearFactory(school=school_b, label="2099-00")
    token_a = _login(client, admin_a)
    res = client.patch(
        f"/api/v1/schools/academic-years/{foreign_year.id}",
        data={"label": "pwned"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token_a}",
    )
    assert res.status_code == 404, res.content
    foreign_year.refresh_from_db()
    assert foreign_year.label == "2099-00"
