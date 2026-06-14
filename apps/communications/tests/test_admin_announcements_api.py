"""HTTP tests for the admin announcements endpoints (skooly-stride)."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.academics.models import StudentEnrollment, TeacherAssignment
from apps.academics.tests.factories import SubjectFactory
from apps.communications.models import Announcement, AnnouncementCategory
from apps.people.tests.factories import StudentFactory, TeacherFactory


def _enroll(world: dict, section, n: int) -> None:
    """Create n active students enrolled in the given section."""
    school, year = world["school"], world["year"]
    for _ in range(n):
        student = StudentFactory(school=school)
        StudentEnrollment.objects.create(
            school=school,
            student=student,
            section=section,
            academic_year=year,
            enrollment_date=student.admission_date,
        )


@pytest.mark.django_db
def test_create_school_wide(client: Client, admin_token_a, world_a):
    res = client.post(
        "/api/v1/announcements",
        data={"title": "Sports Day", "body": "Save the date", "category": "school"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["audience"] == "All school"
    assert body["targetClassId"] is None
    assert body["category"] == "school"


@pytest.mark.django_db
def test_create_section_targeted_counts_recipients(client: Client, admin_token_a, world_a):
    _enroll(world_a, world_a["section_a"], 3)
    _enroll(world_a, world_a["section_b"], 2)
    res = client.post(
        "/api/v1/announcements",
        data={
            "title": "PTM",
            "body": "Saturday 10am",
            "category": "class",
            "targetSectionId": world_a["section_a"].id,
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["targetSectionId"] == world_a["section_a"].id
    assert body["recipientCount"] == 3  # only section A, not B
    assert "Section" in body["audience"]


@pytest.mark.django_db
def test_create_teacher_recipient_counts_teachers(client: Client, admin_token_a, world_a):
    school, year = world_a["school"], world_a["section_a"].class_obj.academic_year
    # Two distinct teachers assigned to section A.
    for i in range(2):
        teacher = TeacherFactory(school=school, phone=f"+91888800{i}999")
        subject = SubjectFactory(school=school, name=f"Subject {i}")
        TeacherAssignment.objects.create(
            school=school, teacher=teacher, subject=subject,
            section=world_a["section_a"], academic_year=year,
        )
    res = client.post(
        "/api/v1/announcements",
        data={
            "title": "Staff meeting",
            "category": "school",
            "recipientType": "teachers",
            "targetSectionId": world_a["section_a"].id,
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["recipientType"] == "teachers"
    assert body["recipientCount"] == 2


@pytest.mark.django_db
def test_create_rejects_bad_recipient(client: Client, admin_token_a, world_a):
    res = client.post(
        "/api/v1/announcements",
        data={"title": "x", "category": "school", "recipientType": "aliens"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 422


@pytest.mark.django_db
def test_recipient_count_preview(client: Client, admin_token_a, world_a):
    _enroll(world_a, world_a["section_a"], 4)
    # parents + section A
    res = client.get(
        f"/api/v1/announcements/recipient-count?recipientType=parents&targetSectionId={world_a['section_a'].id}",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    assert res.json()["recipientCount"] == 4
    # bad recipient rejected
    res = client.get(
        "/api/v1/announcements/recipient-count?recipientType=aliens",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 422


@pytest.mark.django_db
def test_create_rejects_bad_category(client: Client, admin_token_a, world_a):
    res = client.post(
        "/api/v1/announcements",
        data={"title": "x", "category": "nonsense"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 422


@pytest.mark.django_db
def test_create_rejects_class_and_section_together(client: Client, admin_token_a, world_a):
    res = client.post(
        "/api/v1/announcements",
        data={
            "title": "x",
            "category": "school",
            "targetClassId": world_a["class"].id,
            "targetSectionId": world_a["section_a"].id,
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 422


@pytest.mark.django_db
def test_teacher_cannot_create(client: Client, teacher_token_a, world_a):
    res = client.post(
        "/api/v1/announcements",
        data={"title": "x", "category": "school"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {teacher_token_a}",
    )
    assert res.status_code == 403


@pytest.mark.django_db
def test_list_and_delete(client: Client, admin_token_a, world_a):
    school = world_a["school"]
    a1 = Announcement.objects.create(
        school=school, title="One", body="", date="2026-01-10",
        category=AnnouncementCategory.SCHOOL,
    )
    Announcement.objects.create(
        school=school, title="Two", body="", date="2026-02-10",
        category=AnnouncementCategory.HOLIDAY,
    )

    res = client.get("/api/v1/announcements", HTTP_AUTHORIZATION=f"Bearer {admin_token_a}")
    assert res.status_code == 200, res.content
    titles = [a["title"] for a in res.json()]
    assert titles == ["Two", "One"]  # newest date first

    res = client.delete(
        f"/api/v1/announcements/{a1.id}", HTTP_AUTHORIZATION=f"Bearer {admin_token_a}"
    )
    assert res.status_code == 200

    res = client.get("/api/v1/announcements", HTTP_AUTHORIZATION=f"Bearer {admin_token_a}")
    assert [a["title"] for a in res.json()] == ["Two"]
