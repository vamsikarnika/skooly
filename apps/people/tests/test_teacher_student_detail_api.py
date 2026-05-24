"""HTTP tests for the teacher app single-student detail endpoint."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.academics.models import StudentEnrollment, TeacherAssignment
from apps.academics.tests.factories import SubjectFactory
from apps.accounts.services import issue_tokens_for_user
from apps.attendance.models import Attendance, AttendanceStatus
from apps.exams.models import Test, TestScore
from apps.people.tests.factories import StudentFactory, TeacherFactory


def _auth(user) -> dict:  # type: ignore[no-untyped-def]
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_tokens_for_user(user)['access_token']}"}


def _setup_teacher(world: dict):  # type: ignore[no-untyped-def]
    school, year, section = world["school"], world["year"], world["section_a"]
    teacher = TeacherFactory(school=school, user=world["teacher_user"])
    subject = SubjectFactory(school=school, name="Science")
    TeacherAssignment.objects.create(
        school=school, teacher=teacher, subject=subject, section=section, academic_year=year
    )
    school.current_academic_year = year
    school.save(update_fields=["current_academic_year"])
    return teacher, subject


def _enroll(world: dict, section, roll: int = 5):  # type: ignore[no-untyped-def]
    school, year = world["school"], world["year"]
    student = StudentFactory(
        school=school, first_name="Aarav", last_name="Reddy", parent1_phone="+919876500010"
    )
    StudentEnrollment.objects.create(
        school=school, student=student, section=section, academic_year=year,
        roll_number=str(roll), enrollment_date=date(2025, 6, 1), status="active",
    )
    return student


@pytest.mark.django_db
def test_student_detail_shape(client: Client, world_a) -> None:
    _teacher, subject = _setup_teacher(world_a)
    school, section = world_a["school"], world_a["section_a"]
    student = _enroll(world_a, section, roll=5)

    today = timezone.now().date()
    for i in range(4):
        Attendance.objects.create(
            school=school, student=student, section=section,
            date=today - timedelta(days=i), status=AttendanceStatus.PRESENT,
        )
    Attendance.objects.create(
        school=school, student=student, section=section,
        date=today - timedelta(days=4), status=AttendanceStatus.ABSENT,
    )

    test = Test.objects.create(
        school=school, section=section, subject=subject, name="Acids & Bases",
        test_type="FA1", test_date=date(2026, 5, 18), max_marks=25,
        published_at=timezone.now(),
    )
    TestScore.objects.create(school=school, test=test, student=student, marks_obtained=19)

    res = client.get(f"/api/v1/teacher/students/{student.id}", **_auth(world_a["teacher_user"]))
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["id"] == str(student.id)
    assert body["rollNo"] == 5
    assert body["name"] == "Aarav Reddy"
    assert body["gender"] == "M"
    assert body["classId"] == str(section.id)
    assert body["className"] == "Class 6"
    assert body["section"] == "A"
    assert body["attendance"] == {"totalDays": 5, "present": 4, "absent": 1, "rate": 80}
    assert len(body["testScores"]) == 1
    score = body["testScores"][0]
    assert score["testId"] == str(test.id)
    assert score["testTitle"] == "Acids & Bases"
    assert score["maxMarks"] == 25
    assert score["marks"] == 19
    assert score["percentage"] == 76


@pytest.mark.django_db
def test_student_detail_404_outside_teachers_sections(client: Client, world_a) -> None:
    _setup_teacher(world_a)  # assigned to section_a
    other = _enroll(world_a, world_a["section_b"], roll=3)  # student in section_b
    res = client.get(f"/api/v1/teacher/students/{other.id}", **_auth(world_a["teacher_user"]))
    assert res.status_code == 404


@pytest.mark.django_db
def test_student_detail_cross_tenant_404(client: Client, world_a, world_b) -> None:
    _setup_teacher(world_a)
    foreign = _enroll(world_b, world_b["section_a"], roll=1)
    res = client.get(f"/api/v1/teacher/students/{foreign.id}", **_auth(world_a["teacher_user"]))
    assert res.status_code == 404


@pytest.mark.django_db
def test_student_detail_rejects_admin_token(client: Client, world_a) -> None:
    _setup_teacher(world_a)
    student = _enroll(world_a, world_a["section_a"])
    res = client.get(f"/api/v1/teacher/students/{student.id}", **_auth(world_a["admin"]))
    assert res.status_code == 401
