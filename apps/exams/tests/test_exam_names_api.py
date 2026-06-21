"""HTTP-layer tests for admin-managed exam names + the teacher read endpoint.

Covers:
- admin CRUD (list/create/dedup/reorder/rename/delete) and admin-only writes
- soft-delete frees the label for re-use
- cross-tenant isolation
- teacher GET /exam-names
- linking a created test to an exam name via examNameId (and ignoring bad ids)
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.academics.models import TeacherAssignment
from apps.academics.tests.factories import SubjectFactory
from apps.exams.models import ExamName, Test
from apps.people.tests.factories import TeacherFactory


def _admin(token: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _create(client: Client, token: str, label: str, *, is_series: bool = False):
    return client.post(
        "/api/v1/exam-names",
        data={"label": label, "isSeries": is_series},
        content_type="application/json",
        **_admin(token),
    )


# ---------------------------------------------------------------------------
# Admin CRUD
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_empty(client: Client, admin_token_a) -> None:
    res = client.get("/api/v1/exam-names", **_admin(admin_token_a))
    assert res.status_code == 200
    assert res.json() == []


@pytest.mark.django_db
def test_create_and_list_with_incrementing_order(client: Client, admin_token_a) -> None:
    a = _create(client, admin_token_a, "Quarterly Exam")
    b = _create(client, admin_token_a, "Weekly Test", is_series=True)
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["displayOrder"] == 1
    assert b.json()["displayOrder"] == 2
    assert b.json()["isSeries"] is True

    body = client.get("/api/v1/exam-names", **_admin(admin_token_a)).json()
    assert [e["label"] for e in body] == ["Quarterly Exam", "Weekly Test"]


@pytest.mark.django_db
def test_create_duplicate_case_insensitive_conflicts(client: Client, admin_token_a) -> None:
    assert _create(client, admin_token_a, "Unit Test").status_code == 200
    dup = _create(client, admin_token_a, "  unit test  ")
    assert dup.status_code == 409


@pytest.mark.django_db
def test_create_requires_admin(client: Client, teacher_token_a) -> None:
    res = _create(client, teacher_token_a, "Quarterly Exam")
    assert res.status_code == 403
    assert ExamName.objects.all_tenants().count() == 0


@pytest.mark.django_db
def test_update_rename_reorder_and_series_toggle(client: Client, admin_token_a) -> None:
    eid = _create(client, admin_token_a, "Weekly Test", is_series=True).json()["id"]
    res = client.patch(
        f"/api/v1/exam-names/{eid}",
        data={"label": "Weekly Assessment", "isSeries": False, "displayOrder": 5},
        content_type="application/json",
        **_admin(admin_token_a),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["label"] == "Weekly Assessment"
    assert body["isSeries"] is False
    assert body["displayOrder"] == 5


@pytest.mark.django_db
def test_update_to_existing_label_conflicts(client: Client, admin_token_a) -> None:
    _create(client, admin_token_a, "Quarterly Exam")
    eid = _create(client, admin_token_a, "Weekly Test").json()["id"]
    res = client.patch(
        f"/api/v1/exam-names/{eid}",
        data={"label": "quarterly exam"},
        content_type="application/json",
        **_admin(admin_token_a),
    )
    assert res.status_code == 409


@pytest.mark.django_db
def test_delete_soft_removes_and_frees_label(client: Client, admin_token_a) -> None:
    eid = _create(client, admin_token_a, "Unit Test").json()["id"]
    res = client.delete(f"/api/v1/exam-names/{eid}", **_admin(admin_token_a))
    assert res.status_code == 200
    assert client.get("/api/v1/exam-names", **_admin(admin_token_a)).json() == []
    # The row still exists (soft-deleted) so linked tests keep the reference.
    assert ExamName.objects.including_deleted().filter(id=eid).exists()
    # Re-creating the same label after delete is allowed.
    assert _create(client, admin_token_a, "Unit Test").status_code == 200


@pytest.mark.django_db
def test_delete_requires_admin(client: Client, admin_token_a, teacher_token_a) -> None:
    eid = _create(client, admin_token_a, "Unit Test").json()["id"]
    res = client.delete(f"/api/v1/exam-names/{eid}", **_admin(teacher_token_a))
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Cross-tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_cross_tenant_isolation(client: Client, admin_token_a, admin_token_b, world_a) -> None:
    eid = _create(client, admin_token_a, "Quarterly Exam").json()["id"]
    # School B sees its own (empty) list, not School A's name.
    assert client.get("/api/v1/exam-names", **_admin(admin_token_b)).json() == []
    # School B cannot mutate School A's exam name.
    res = client.patch(
        f"/api/v1/exam-names/{eid}",
        data={"label": "Hacked"},
        content_type="application/json",
        **_admin(admin_token_b),
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Teacher read endpoint + test linking
# ---------------------------------------------------------------------------


def _teacher_setup(world: dict):
    """Teacher + subject + assignment in section_a so create_test succeeds."""
    school, year, section = world["school"], world["year"], world["section_a"]
    teacher = TeacherFactory(school=school, user=world["teacher_user"])
    subject = SubjectFactory(school=school, name="Science")
    TeacherAssignment.objects.create(
        school=school, teacher=teacher, subject=subject, section=section, academic_year=year
    )
    school.current_academic_year = year
    school.save(update_fields=["current_academic_year"])
    return teacher, subject, section


@pytest.mark.django_db
def test_teacher_lists_exam_names(client: Client, admin_token_a, teacher_token_a) -> None:
    _create(client, admin_token_a, "Weekly Test", is_series=True)
    res = client.get("/api/v1/teacher/exam-names", **_admin(teacher_token_a))
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["label"] == "Weekly Test"
    assert body[0]["isSeries"] is True
    # Display order is an admin-only concern; not exposed to teachers.
    assert "displayOrder" not in body[0]


@pytest.mark.django_db
def test_create_test_links_exam_name(client: Client, teacher_token_a, world_a) -> None:
    _, _, section = _teacher_setup(world_a)
    exam_name = ExamName.objects.create(
        school=world_a["school"], label="Weekly Test", is_series=True, display_order=1
    )
    res = client.post(
        "/api/v1/teacher/tests",
        data={
            "sectionId": section.id,
            "name": "Weekly Test 3",
            "testDate": "2026-05-01",
            "maxMarks": 25,
            "mode": "offline",
            "examNameId": exam_name.id,
        },
        content_type="application/json",
        **_admin(teacher_token_a),
    )
    assert res.status_code == 200, res.content
    test = Test.objects.all_tenants().get(id=int(res.json()["id"]))
    assert test.exam_name_id == exam_name.id
    assert test.name == "Weekly Test 3"


@pytest.mark.django_db
def test_create_test_ignores_unknown_exam_name(client: Client, teacher_token_a, world_a) -> None:
    _, _, section = _teacher_setup(world_a)
    res = client.post(
        "/api/v1/teacher/tests",
        data={
            "sectionId": section.id,
            "name": "Surprise Quiz",
            "testDate": "2026-05-01",
            "maxMarks": 25,
            "mode": "offline",
            "examNameId": 999999,
        },
        content_type="application/json",
        **_admin(teacher_token_a),
    )
    assert res.status_code == 200, res.content
    test = Test.objects.all_tenants().get(id=int(res.json()["id"]))
    assert test.exam_name_id is None
