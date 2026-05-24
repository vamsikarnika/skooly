"""HTTP tests for the teacher app classes + roster endpoints."""

from __future__ import annotations

from datetime import date

import pytest
from django.test import Client

from apps.academics.models import StudentEnrollment, TeacherAssignment
from apps.academics.tests.factories import SubjectFactory
from apps.accounts.services import issue_tokens_for_user
from apps.attendance.models import Attendance, AttendanceStatus
from apps.core.helpers import today_local
from apps.people.tests.factories import StudentFactory, TeacherFactory


def _token(user) -> str:  # type: ignore[no-untyped-def]
    return issue_tokens_for_user(user)["access_token"]


def _auth(user) -> dict:  # type: ignore[no-untyped-def]
    return {"HTTP_AUTHORIZATION": f"Bearer {_token(user)}"}


def _setup(world: dict, subject_name: str = "Science"):  # type: ignore[no-untyped-def]
    school, year, section = world["school"], world["year"], world["section_a"]
    teacher = TeacherFactory(school=school, user=world["teacher_user"])
    subject = SubjectFactory(school=school, name=subject_name)
    TeacherAssignment.objects.create(
        school=school, teacher=teacher, subject=subject, section=section, academic_year=year
    )
    school.current_academic_year = year
    school.save(update_fields=["current_academic_year"])
    return teacher


def _enroll(world: dict, roll: int, name: str = "Aarav Reddy", gender: str = "Male"):  # type: ignore[no-untyped-def]
    school, year, section = world["school"], world["year"], world["section_a"]
    first, _, last = name.partition(" ")
    student = StudentFactory(
        school=school, first_name=first, last_name=last, gender=gender, parent1_phone="+919876500010"
    )
    StudentEnrollment.objects.create(
        school=school,
        student=student,
        section=section,
        academic_year=year,
        roll_number=str(roll),
        enrollment_date=date(2025, 6, 1),
        status="active",
    )
    return student


@pytest.mark.django_db
def test_classes_lists_assigned_section_with_counts(client: Client, world_a) -> None:
    _setup(world_a)
    s1 = _enroll(world_a, 1)
    _enroll(world_a, 2)
    Attendance.objects.create(
        school=world_a["school"], student=s1, section=world_a["section_a"],
        date=today_local(), status=AttendanceStatus.PRESENT,
    )

    res = client.get("/api/v1/teacher/classes", **_auth(world_a["teacher_user"]))
    assert res.status_code == 200, res.content
    body = res.json()
    assert len(body) == 1
    card = body[0]
    assert card["id"] == str(world_a["section_a"].id)
    assert card["name"] == "Class 6"
    assert card["section"] == "A"
    assert card["subject"] == "Science"
    assert card["enrollment"] == 2
    assert card["attendanceMarked"] is True
    assert card["attendanceTime"] is not None
    assert card["schedule"] == ""  # stubbed


@pytest.mark.django_db
def test_classes_empty_without_assignments(client: Client, world_a) -> None:
    TeacherFactory(school=world_a["school"], user=world_a["teacher_user"])
    world_a["school"].current_academic_year = world_a["year"]
    world_a["school"].save(update_fields=["current_academic_year"])
    res = client.get("/api/v1/teacher/classes", **_auth(world_a["teacher_user"]))
    assert res.status_code == 200
    assert res.json() == []


@pytest.mark.django_db
def test_class_students_roster_ordered_by_roll(client: Client, world_a) -> None:
    _setup(world_a)
    _enroll(world_a, 2, name="Bhavna Rao", gender="Female")
    _enroll(world_a, 1, name="Aarav Reddy")
    _enroll(world_a, 10, name="Charan Das")
    section_id = world_a["section_a"].id

    res = client.get(f"/api/v1/teacher/classes/{section_id}/students", **_auth(world_a["teacher_user"]))
    assert res.status_code == 200, res.content
    body = res.json()
    assert [r["rollNo"] for r in body] == [1, 2, 10]
    first = body[0]
    assert first["name"] == "Aarav Reddy"
    assert first["gender"] == "M"
    assert first["parentPhone"] == "+919876500010"
    assert body[1]["gender"] == "F"


@pytest.mark.django_db
def test_class_students_404_for_unassigned_section(client: Client, world_a) -> None:
    _setup(world_a)  # assigned to section_a only
    res = client.get(
        f"/api/v1/teacher/classes/{world_a['section_b'].id}/students",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_classes_rejects_admin_token(client: Client, world_a) -> None:
    _setup(world_a)
    res = client.get("/api/v1/teacher/classes", **_auth(world_a["admin"]))
    assert res.status_code == 401


@pytest.mark.django_db
def test_class_students_cross_tenant_404(client: Client, world_a, world_b) -> None:
    _setup(world_a)
    res = client.get(
        f"/api/v1/teacher/classes/{world_b['section_a'].id}/students",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 404
