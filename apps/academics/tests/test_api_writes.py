"""Write endpoints for academics: classes, sections, subjects, assignments."""

from __future__ import annotations

import pytest

from apps.academics.tests.factories import SubjectFactory
from apps.people.tests.factories import TeacherFactory


@pytest.mark.django_db
def test_create_class(client, admin_token_a, world_a):
    res = client.post(
        "/api/v1/classes",
        data={"academicYearId": world_a["year"].id, "name": "Class 7", "displayOrder": 7},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    assert res.json()["name"] == "Class 7"


@pytest.mark.django_db
def test_create_class_cross_tenant_year_404(client, admin_token_a, world_b):
    res = client.post(
        "/api/v1/classes",
        data={"academicYearId": world_b["year"].id, "name": "Class 99"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_delete_class_with_sections_rejected(client, admin_token_a, world_a):
    res = client.delete(
        f"/api/v1/classes/{world_a['class'].id}",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 409
    assert "sections" in res.json()["error"]["message"].lower()


@pytest.mark.django_db
def test_create_section_with_class_teacher(client, admin_token_a, world_a):
    teacher = TeacherFactory(school=world_a["school"], phone="+918888000001")
    res = client.post(
        "/api/v1/sections",
        data={
            "classId": world_a["class"].id,
            "name": "C",
            "classTeacherId": teacher.id,
            "roomNumber": "6C",
            "capacity": 35,
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["name"] == "C"
    assert body["classTeacherId"] == teacher.id


@pytest.mark.django_db
def test_create_section_cross_tenant_teacher_404(client, admin_token_a, world_a, world_b):
    foreign_teacher = TeacherFactory(school=world_b["school"], phone="+918888000099")
    res = client.post(
        "/api/v1/sections",
        data={
            "classId": world_a["class"].id, "name": "Z",
            "classTeacherId": foreign_teacher.id,
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_delete_section_with_active_enrollments_rejected(client, admin_token_a, world_a):
    """Create a student in section A then try to delete the section."""
    payload = {
        "firstName": "Test", "gender": "Male", "admissionDate": "2025-06-15",
        "sectionId": world_a["section_a"].id,
    }
    client.post(
        "/api/v1/students", data=payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    res = client.delete(
        f"/api/v1/sections/{world_a['section_a'].id}",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 409


@pytest.mark.django_db
def test_subject_crud(client, admin_token_a, world_a):
    res = client.post(
        "/api/v1/subjects",
        data={"name": "Mathematics", "code": "MAT"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200
    subject_id = res.json()["id"]

    res = client.patch(
        f"/api/v1/subjects/{subject_id}",
        data={"code": "MATH"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200
    assert res.json()["code"] == "MATH"

    res = client.delete(
        f"/api/v1/subjects/{subject_id}",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200


@pytest.mark.django_db
def test_teacher_assignment_create_and_delete(client, admin_token_a, world_a):
    teacher = TeacherFactory(school=world_a["school"], phone="+918888001000")
    subject = SubjectFactory(school=world_a["school"], name="English")
    res = client.post(
        "/api/v1/teacher-assignments",
        data={
            "teacherId": teacher.id,
            "subjectId": subject.id,
            "sectionId": world_a["section_a"].id,
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    assignment_id = res.json()["data"]["id"]

    # Duplicate should fail
    res2 = client.post(
        "/api/v1/teacher-assignments",
        data={
            "teacherId": teacher.id,
            "subjectId": subject.id,
            "sectionId": world_a["section_a"].id,
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res2.status_code == 409

    res3 = client.delete(
        f"/api/v1/teacher-assignments/{assignment_id}",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res3.status_code == 200


@pytest.mark.django_db
def test_teacher_assignment_cross_tenant_404(
    client, admin_token_a, world_a, world_b
):
    """Admin A tries to assign A's teacher to B's section → 404 on section lookup."""
    teacher = TeacherFactory(school=world_a["school"], phone="+918888002000")
    subject = SubjectFactory(school=world_a["school"], name="Hindi")
    res = client.post(
        "/api/v1/teacher-assignments",
        data={
            "teacherId": teacher.id,
            "subjectId": subject.id,
            "sectionId": world_b["section_a"].id,
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_teacher_cannot_create_class(client, teacher_token_a, world_a):
    res = client.post(
        "/api/v1/classes",
        data={"academicYearId": world_a["year"].id, "name": "Class 99"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {teacher_token_a}",
    )
    assert res.status_code == 403
