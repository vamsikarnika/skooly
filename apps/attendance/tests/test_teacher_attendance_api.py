"""HTTP tests for the teacher attendance endpoints."""

from __future__ import annotations

from datetime import date

import pytest
from django.test import Client
from django.utils import timezone

from apps.academics.models import StudentEnrollment, TeacherAssignment
from apps.academics.tests.factories import SubjectFactory
from apps.accounts.services import issue_tokens_for_user
from apps.attendance.models import Attendance, AttendanceStatus
from apps.people.tests.factories import StudentFactory, TeacherFactory


def _auth(user) -> dict:  # type: ignore[no-untyped-def]
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_tokens_for_user(user)['access_token']}"}


def _setup(world: dict):  # type: ignore[no-untyped-def]
    school, year, section = world["school"], world["year"], world["section_a"]
    teacher = TeacherFactory(school=school, user=world["teacher_user"])
    subject = SubjectFactory(school=school, name="Science")
    TeacherAssignment.objects.create(
        school=school, teacher=teacher, subject=subject, section=section, academic_year=year
    )
    school.current_academic_year = year
    school.save(update_fields=["current_academic_year"])
    return teacher, subject, section


def _enroll(world: dict, section, roll: int = 1):  # type: ignore[no-untyped-def]
    school, year = world["school"], world["year"]
    student = StudentFactory(school=school, first_name="Aarav", last_name="Reddy")
    StudentEnrollment.objects.create(
        school=school, student=student, section=section, academic_year=year,
        roll_number=str(roll), enrollment_date=date(2025, 6, 1), status="active",
    )
    return student


@pytest.mark.django_db
def test_get_attendance_empty(client: Client, world_a) -> None:
    """Returns all students as 'present' when no records exist yet."""
    _setup(world_a)
    section = world_a["section_a"]
    _enroll(world_a, section, roll=1)
    today = timezone.now().date().isoformat()
    res = client.get(
        f"/api/v1/teacher/attendance/{section.id}?date={today}",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["status"] == "present"


@pytest.mark.django_db
def test_get_attendance_with_existing_records(client: Client, world_a) -> None:
    """Pre-fills existing attendance records correctly."""
    _setup(world_a)
    section = world_a["section_a"]
    student = _enroll(world_a, section, roll=1)
    today = timezone.now().date()
    Attendance.objects.create(
        school=world_a["school"], student=student, section=section,
        date=today, status=AttendanceStatus.ABSENT,
    )
    res = client.get(
        f"/api/v1/teacher/attendance/{section.id}?date={today.isoformat()}",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 200
    assert res.json()[0]["status"] == "absent"


@pytest.mark.django_db
def test_save_attendance_creates_records(client: Client, world_a) -> None:
    _setup(world_a)
    section = world_a["section_a"]
    s1 = _enroll(world_a, section, roll=1)
    s2 = _enroll(world_a, section, roll=2)
    today = timezone.now().date().isoformat()
    res = client.post(
        f"/api/v1/teacher/attendance/{section.id}",
        content_type="application/json",
        data={
            "date": today,
            "records": [
                {"studentId": str(s1.id), "status": "present"},
                {"studentId": str(s2.id), "status": "absent"},
            ],
        },
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 200
    assert res.json()["saved"] == 2
    assert Attendance.objects.all_tenants().filter(student=s2, status=AttendanceStatus.ABSENT).exists()


@pytest.mark.django_db
def test_save_attendance_upserts(client: Client, world_a) -> None:
    """Saving twice on same day updates, doesn't duplicate."""
    _setup(world_a)
    section = world_a["section_a"]
    student = _enroll(world_a, section, roll=1)
    today = timezone.now().date().isoformat()
    payload = {"date": today, "records": [{"studentId": str(student.id), "status": "absent"}]}
    client.post(f"/api/v1/teacher/attendance/{section.id}", content_type="application/json",
                data=payload, **_auth(world_a["teacher_user"]))
    payload["records"][0]["status"] = "present"
    client.post(f"/api/v1/teacher/attendance/{section.id}", content_type="application/json",
                data=payload, **_auth(world_a["teacher_user"]))
    assert Attendance.objects.all_tenants().filter(student=student).count() == 1
    assert Attendance.objects.all_tenants().get(student=student).status == AttendanceStatus.PRESENT


@pytest.mark.django_db
def test_attendance_summary(client: Client, world_a) -> None:
    _setup(world_a)
    section = world_a["section_a"]
    s1 = _enroll(world_a, section, roll=1)
    s2 = _enroll(world_a, section, roll=2)
    today = timezone.now().date()
    Attendance.objects.create(school=world_a["school"], student=s1, section=section,
                              date=today, status=AttendanceStatus.PRESENT)
    Attendance.objects.create(school=world_a["school"], student=s2, section=section,
                              date=today, status=AttendanceStatus.ABSENT)
    res = client.get(
        f"/api/v1/teacher/attendance/summary?date={today.isoformat()}",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    card = body[0]
    assert card["sectionId"] == str(section.id)
    assert card["present"] == 1
    assert card["absent"] == 1
    assert card["rate"] == 50
    assert card["marked"] is True


@pytest.mark.django_db
def test_attendance_404_unassigned_section(client: Client, world_a) -> None:
    _setup(world_a)  # assigned to section_a only
    today = timezone.now().date().isoformat()
    res = client.get(
        f"/api/v1/teacher/attendance/{world_a['section_b'].id}?date={today}",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_attendance_cross_tenant_404(client: Client, world_a, world_b) -> None:
    _setup(world_a)
    _setup(world_b)
    today = timezone.now().date().isoformat()
    res = client.get(
        f"/api/v1/teacher/attendance/{world_b['section_a'].id}?date={today}",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_attendance_summary_deduplicates_multi_subject_sections(client: Client, world_a) -> None:
    """Teacher assigned to same section via two subjects → summary returns one card."""
    school, year, section = world_a["school"], world_a["year"], world_a["section_a"]
    teacher = TeacherFactory(school=school, user=world_a["teacher_user"])
    sub1 = SubjectFactory(school=school, name="Math")
    sub2 = SubjectFactory(school=school, name="Science")
    TeacherAssignment.objects.create(
        school=school, teacher=teacher, subject=sub1, section=section, academic_year=year
    )
    TeacherAssignment.objects.create(
        school=school, teacher=teacher, subject=sub2, section=section, academic_year=year
    )
    school.current_academic_year = year
    school.save(update_fields=["current_academic_year"])
    today = timezone.now().date().isoformat()
    res = client.get(
        f"/api/v1/teacher/attendance/summary?date={today}",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 200
    body = res.json()
    # Only one card even though there are two assignments to the same section
    section_ids = [card["sectionId"] for card in body]
    assert section_ids.count(str(section.id)) == 1


@pytest.mark.django_db
def test_attendance_rejects_admin_token(client: Client, world_a) -> None:
    _setup(world_a)
    today = timezone.now().date().isoformat()
    res = client.get(
        f"/api/v1/teacher/attendance/{world_a['section_a'].id}?date={today}",
        **_auth(world_a["admin"]),
    )
    assert res.status_code == 401
