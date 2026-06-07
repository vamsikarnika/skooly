"""HTTP tests for the parent app timetable endpoint."""

from __future__ import annotations

from datetime import date, time

import pytest
from django.test import Client

from apps.academics.models import DayOfWeek, StudentEnrollment, TimetablePeriod
from apps.academics.tests.factories import SubjectFactory
from apps.accounts.models import Role, User
from apps.accounts.services import issue_tokens_for_user
from apps.people.models import Parent, ParentStudent
from apps.people.tests.factories import StudentFactory


def _auth(user: User) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_tokens_for_user(user)['access_token']}"}


def _parent_with_child(world: dict, phone: str = "+919876512345"):
    school, year, section = world["school"], world["year"], world["section_a"]
    student = StudentFactory(school=school, first_name="Aarav", last_name="Reddy")
    StudentEnrollment.objects.create(
        school=school, student=student, section=section, academic_year=year,
        roll_number="14", enrollment_date=date(2025, 6, 1), status="active",
    )
    school.current_academic_year = year
    school.save(update_fields=["current_academic_year"])
    user = User.objects.create(
        phone=phone, role=Role.PARENT, school=school, first_name="Suresh", last_name="Reddy"
    )
    user.set_unusable_password()
    user.save()
    parent = Parent.objects.create(school=school, user=user, name="Suresh Reddy", phone=phone)
    ParentStudent.objects.create(school=school, parent=parent, student=student)
    return user, student, section


def _make_period(school, section, *, day, period, subject=None, start=time(8, 0), end=time(8, 45)):
    return TimetablePeriod.objects.create(
        school=school, section=section, day_of_week=day, period_number=period,
        subject=subject, start_time=start, end_time=end,
    )


@pytest.mark.django_db
def test_returns_week_grouped_by_day_in_chronological_order(client: Client, world_a) -> None:
    user, student, section = _parent_with_child(world_a)
    school = world_a["school"]
    math = SubjectFactory(school=school, name="Mathematics")
    sci = SubjectFactory(school=school, name="Science")
    # Insert in shuffled order to prove the API sorts.
    _make_period(school, section, day=DayOfWeek.WED, period=2, subject=sci,
                 start=time(8, 45), end=time(9, 30))
    _make_period(school, section, day=DayOfWeek.MON, period=1, subject=math,
                 start=time(8, 0), end=time(8, 45))
    _make_period(school, section, day=DayOfWeek.WED, period=1, subject=math,
                 start=time(8, 0), end=time(8, 45))

    res = client.get(f"/api/v1/parent/children/{student.id}/timetable", **_auth(user))
    assert res.status_code == 200, res.content
    days = res.json()["days"]
    assert [d["day"] for d in days] == ["Mon", "Wed"]
    # Wed has two periods, in period_number order.
    assert [p["period"] for p in days[1]["periods"]] == [1, 2]
    assert days[0]["periods"][0]["subject"] == "Mathematics"
    assert days[0]["periods"][0]["startTime"] == "08:00"
    assert days[0]["periods"][0]["endTime"] == "08:45"


@pytest.mark.django_db
def test_empty_when_section_has_no_timetable(client: Client, world_a) -> None:
    user, student, _section = _parent_with_child(world_a)
    res = client.get(f"/api/v1/parent/children/{student.id}/timetable", **_auth(user))
    assert res.status_code == 200, res.content
    assert res.json() == {"days": []}


@pytest.mark.django_db
def test_cross_tenant_child_404(client: Client, world_a, world_b) -> None:
    user_a, _, _ = _parent_with_child(world_a, phone="+919876512345")
    _, student_b, _ = _parent_with_child(world_b, phone="+919876599999")
    res = client.get(f"/api/v1/parent/children/{student_b.id}/timetable", **_auth(user_a))
    assert res.status_code == 404


@pytest.mark.django_db
def test_unlinked_child_same_school_404(client: Client, world_a) -> None:
    user, _, _ = _parent_with_child(world_a)
    stranger = StudentFactory(school=world_a["school"], first_name="Stranger")
    res = client.get(f"/api/v1/parent/children/{stranger.id}/timetable", **_auth(user))
    assert res.status_code == 404
