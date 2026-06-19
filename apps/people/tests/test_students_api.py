"""End-to-end tests for student write endpoints."""

from __future__ import annotations

import pytest

from apps.core.context import use_school
from apps.people.models import Student
from apps.people.tests.factories import StudentFactory

BASE_PAYLOAD = {
    "firstName": "Aarav",
    "lastName": "Reddy",
    "gender": "Male",
    "admissionDate": "2025-06-15",
    "bloodGroup": "B+",
    "address": "1-2, MG Road, Vijayawada, AP",
    "parents": [
        {"name": "Rajesh Reddy", "relation": "Father", "phone": "+919800000001", "whatsapp": True},
        {"name": "Priya Reddy", "relation": "Mother", "phone": "+919800000002", "whatsapp": False},
    ],
}


@pytest.mark.django_db
def test_create_student_auto_admission(client, admin_token_a, world_a):
    payload = {**BASE_PAYLOAD, "sectionId": world_a["section_a"].id}
    res = client.post(
        "/api/v1/students",
        data=payload,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["fullName"] == "Aarav Reddy"
    assert body["admissionNumber"]  # auto-generated
    assert body["className"] == "Class 6"
    assert body["sectionName"] == "A"
    assert len(body["parents"]) == 2


@pytest.mark.django_db
def test_create_student_explicit_admission_number(client, admin_token_a, world_a):
    payload = {**BASE_PAYLOAD, "sectionId": world_a["section_a"].id, "admissionNumber": "VB001"}
    res = client.post(
        "/api/v1/students", data=payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200
    assert res.json()["admissionNumber"] == "VB001"


@pytest.mark.django_db
def test_create_student_rejects_duplicate_admission(client, admin_token_a, world_a):
    payload = {**BASE_PAYLOAD, "sectionId": world_a["section_a"].id, "admissionNumber": "VB001"}
    client.post(
        "/api/v1/students", data=payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    res = client.post(
        "/api/v1/students", data=payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 409


@pytest.mark.django_db
def test_create_student_teacher_forbidden(client, teacher_token_a, world_a):
    payload = {**BASE_PAYLOAD, "sectionId": world_a["section_a"].id}
    res = client.post(
        "/api/v1/students", data=payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {teacher_token_a}",
    )
    assert res.status_code == 403


@pytest.mark.django_db
def test_create_student_cross_tenant_section_404(
    client, admin_token_a, world_a, world_b
):
    """Admin of A cannot enroll students into a section from school B."""
    payload = {**BASE_PAYLOAD, "sectionId": world_b["section_a"].id}
    res = client.post(
        "/api/v1/students", data=payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_update_student(client, admin_token_a, world_a):
    student = StudentFactory(school=world_a["school"], admission_number="VB100")
    res = client.patch(
        f"/api/v1/students/{student.id}",
        data={"firstName": "Updated", "bloodGroup": "O+"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    assert res.json()["firstName"] == "Updated"
    assert res.json()["bloodGroup"] == "O+"


@pytest.mark.django_db
def test_update_student_cross_tenant_404(client, admin_token_a, world_b):
    student = StudentFactory(school=world_b["school"], admission_number="X1")
    res = client.patch(
        f"/api/v1/students/{student.id}",
        data={"firstName": "Hacked"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404
    student.refresh_from_db()
    assert student.first_name != "Hacked"


@pytest.mark.django_db
def test_delete_student_marks_withdrawn(client, admin_token_a, world_a):
    """Withdraw should be operational only — student stays visible under the
    `status=withdrawn` filter. deleted_at is reserved for true purges (no UI)."""
    student = StudentFactory(school=world_a["school"], admission_number="VB200")
    res = client.delete(
        f"/api/v1/students/{student.id}",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200
    student.refresh_from_db()
    assert student.status == "withdrawn"
    assert student.deleted_at is None  # NOT soft-deleted, just status change

    # Filter by status=withdrawn → still visible.
    res = client.get(
        "/api/v1/students?status=withdrawn",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200
    ids = {s["id"] for s in res.json()["items"]}
    assert student.id in ids


@pytest.mark.django_db
def test_student_phone_validation(client, admin_token_a, world_a):
    """Parent phones must be +91 + 10 digits exactly."""
    payload = {
        **BASE_PAYLOAD,
        "sectionId": world_a["section_a"].id,
        "parents": [
            {"name": "Bad Phone", "relation": "Father", "phone": "+9198", "whatsapp": True},
        ],
    }
    res = client.post(
        "/api/v1/students", data=payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 422


@pytest.mark.django_db
def test_delete_student_cross_tenant_404(client, admin_token_a, world_b):
    student = StudentFactory(school=world_b["school"], admission_number="X2")
    res = client.delete(
        f"/api/v1/students/{student.id}",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_transfer_student_preserves_history(client, admin_token_a, world_a):
    # Create student via API into section A
    payload = {**BASE_PAYLOAD, "sectionId": world_a["section_a"].id}
    student_id = client.post(
        "/api/v1/students", data=payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    ).json()["id"]

    # Transfer to section B
    res = client.post(
        f"/api/v1/students/{student_id}/transfer",
        data={"sectionId": world_a["section_b"].id, "rollNumber": "07"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    assert res.json()["sectionName"] == "B"
    assert res.json()["rollNumber"] == "07"

    with use_school(world_a["school"]):
        student = Student.objects.get(id=student_id)
        enrollments = list(student.enrollments.order_by("id"))
        assert len(enrollments) == 2
        assert enrollments[0].status == "transferred"
        assert enrollments[1].status == "active"
        assert enrollments[1].section_id == world_a["section_b"].id


@pytest.mark.django_db
def test_transfer_to_same_section_rejected(client, admin_token_a, world_a):
    payload = {**BASE_PAYLOAD, "sectionId": world_a["section_a"].id}
    student_id = client.post(
        "/api/v1/students", data=payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    ).json()["id"]
    res = client.post(
        f"/api/v1/students/{student_id}/transfer",
        data={"sectionId": world_a["section_a"].id},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 409


@pytest.mark.django_db
def test_transfer_cross_tenant_target_404(client, admin_token_a, world_a, world_b):
    payload = {**BASE_PAYLOAD, "sectionId": world_a["section_a"].id}
    student_id = client.post(
        "/api/v1/students", data=payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    ).json()["id"]
    res = client.post(
        f"/api/v1/students/{student_id}/transfer",
        data={"sectionId": world_b["section_a"].id},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_export_students_returns_xlsx(client, admin_token_a, world_a):
    StudentFactory(school=world_a["school"], admission_number="E1", first_name="Ananya")
    res = client.get(
        "/api/v1/students/export",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200
    assert res["Content-Type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml")
    assert res.content[:4] == b"PK\x03\x04"  # zip magic = xlsx


@pytest.mark.django_db
def test_reset_parent_password_provisions_login(client, admin_token_a, world_a):
    """Admin generates a parent-app password; the parent can then log in, and
    the password is readable back on the student detail."""
    student = StudentFactory(
        school=world_a["school"], parent1_name="Suresh Reddy",
        parent1_phone="+919812345678", parent1_relation="Father",
    )
    res = client.post(
        f"/api/v1/students/{student.id}/parents/reset-password",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    password = res.json()["password"]

    login = client.post(
        "/api/v1/parent/auth/login",
        data={"phone": "+919812345678", "password": password},
        content_type="application/json",
    )
    assert login.status_code == 200, login.content

    detail = client.get(
        f"/api/v1/students/{student.id}",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    ).json()
    assert detail["parentAppPhone"] == "+919812345678"
    assert detail["parentAppPassword"] == password  # retrievable


@pytest.mark.django_db
def test_reset_parent_password_requires_phone(client, admin_token_a, world_a):
    student = StudentFactory(school=world_a["school"], parent1_name="No Phone", parent1_phone="")
    res = client.post(
        f"/api/v1/students/{student.id}/parents/reset-password",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 422


@pytest.mark.django_db
def test_reset_parent_password_teacher_forbidden(client, teacher_token_a, world_a):
    student = StudentFactory(school=world_a["school"], parent1_phone="+919812345600")
    res = client.post(
        f"/api/v1/students/{student.id}/parents/reset-password",
        HTTP_AUTHORIZATION=f"Bearer {teacher_token_a}",
    )
    assert res.status_code == 403


@pytest.mark.django_db
def test_reset_parent_password_disabled_by_flag(client, admin_token_a, world_a, settings):
    settings.PARENT_PASSWORD_PROVISIONING = False
    student = StudentFactory(school=world_a["school"], parent1_phone="+919812345601")
    res = client.post(
        f"/api/v1/students/{student.id}/parents/reset-password",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404
