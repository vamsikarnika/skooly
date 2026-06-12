"""HTTP tests for the teacher app timetable endpoints."""

from __future__ import annotations

from datetime import date, time

import pytest
from django.test import Client

from apps.academics import teacher_services
from apps.academics.models import DayOfWeek, TimetablePeriod
from apps.academics.tests.factories import SubjectFactory
from apps.accounts.services import issue_tokens_for_user
from apps.people.tests.factories import TeacherFactory

# A known Monday — pinned so "today" filtering is deterministic regardless of
# the day the suite runs on.
FIXED_MONDAY = date(2024, 1, 1)


def _auth(user) -> dict:  # type: ignore[no-untyped-def]
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_tokens_for_user(user)['access_token']}"}


def _teacher(world: dict):  # type: ignore[no-untyped-def]
    school, year = world["school"], world["year"]
    school.current_academic_year = year
    school.save(update_fields=["current_academic_year"])
    return TeacherFactory(school=world["school"], user=world["teacher_user"])


def _make_period(school, section, teacher, *, day, period, subject=None,
                 start=time(8, 0), end=time(8, 45)):  # type: ignore[no-untyped-def]
    return TimetablePeriod.objects.create(
        school=school, section=section, teacher=teacher, day_of_week=day,
        period_number=period, subject=subject, start_time=start, end_time=end,
    )


@pytest.mark.django_db
def test_today_orders_by_start_time_and_filters_to_today(
    client: Client, world_a, monkeypatch
) -> None:
    monkeypatch.setattr(teacher_services, "today_local", lambda: FIXED_MONDAY)
    school = world_a["school"]
    teacher = _teacher(world_a)
    sec_a, sec_b = world_a["section_a"], world_a["section_b"]
    math = SubjectFactory(school=school, name="Mathematics")
    sci = SubjectFactory(school=school, name="Science")

    # Two Monday periods inserted out of order to prove the API sorts by start.
    _make_period(school, sec_b, teacher, day=DayOfWeek.MON, period=3, subject=sci,
                 start=time(10, 0), end=time(10, 45))
    _make_period(school, sec_a, teacher, day=DayOfWeek.MON, period=1, subject=math,
                 start=time(8, 0), end=time(8, 45))
    # A Tuesday period that must NOT appear in today's list.
    _make_period(school, sec_a, teacher, day=DayOfWeek.TUE, period=1, subject=math,
                 start=time(8, 0), end=time(8, 45))

    res = client.get("/api/v1/teacher/timetable/today", **_auth(world_a["teacher_user"]))
    assert res.status_code == 200, res.content
    rows = res.json()
    assert [r["startTime"] for r in rows] == ["08:00", "10:00"]
    assert rows[0]["subject"] == "Mathematics"
    assert rows[0]["sectionLabel"] == "Class 6 - A"
    assert rows[1]["sectionLabel"] == "Class 6 - B"


@pytest.mark.django_db
def test_today_excludes_other_teachers_periods(
    client: Client, world_a, monkeypatch
) -> None:
    monkeypatch.setattr(teacher_services, "today_local", lambda: FIXED_MONDAY)
    school = world_a["school"]
    teacher = _teacher(world_a)
    other = TeacherFactory(school=school)  # different teacher, same school
    sec = world_a["section_a"]

    _make_period(school, sec, teacher, day=DayOfWeek.MON, period=1)
    _make_period(school, sec, other, day=DayOfWeek.MON, period=2,
                 start=time(9, 0), end=time(9, 45))

    res = client.get("/api/v1/teacher/timetable/today", **_auth(world_a["teacher_user"]))
    assert res.status_code == 200, res.content
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["period"] == 1


@pytest.mark.django_db
def test_week_groups_by_day_in_chronological_order(client: Client, world_a) -> None:
    school = world_a["school"]
    teacher = _teacher(world_a)
    sec = world_a["section_a"]
    math = SubjectFactory(school=school, name="Mathematics")
    sci = SubjectFactory(school=school, name="Science")

    # Shuffled insert order to prove grouping + chronological sort.
    _make_period(school, sec, teacher, day=DayOfWeek.WED, period=2, subject=sci,
                 start=time(8, 45), end=time(9, 30))
    _make_period(school, sec, teacher, day=DayOfWeek.MON, period=1, subject=math,
                 start=time(8, 0), end=time(8, 45))
    _make_period(school, sec, teacher, day=DayOfWeek.WED, period=1, subject=math,
                 start=time(8, 0), end=time(8, 45))

    res = client.get("/api/v1/teacher/timetable", **_auth(world_a["teacher_user"]))
    assert res.status_code == 200, res.content
    days = res.json()
    assert [d["day"] for d in days] == ["Mon", "Wed"]
    assert [p["startTime"] for p in days[1]["periods"]] == ["08:00", "08:45"]
    assert days[1]["periods"][0]["sectionLabel"] == "Class 6 - A"


@pytest.mark.django_db
def test_week_empty_when_no_timetable(client: Client, world_a) -> None:
    _teacher(world_a)
    res = client.get("/api/v1/teacher/timetable", **_auth(world_a["teacher_user"]))
    assert res.status_code == 200, res.content
    assert res.json() == []


@pytest.mark.django_db
def test_tenant_isolation_teacher_sees_only_own_school(
    client: Client, world_a, world_b
) -> None:
    # world_a teacher has a period; world_b teacher should see nothing.
    teacher_a = _teacher(world_a)
    _make_period(world_a["school"], world_a["section_a"], teacher_a, day=DayOfWeek.MON, period=1)
    _teacher(world_b)

    res = client.get("/api/v1/teacher/timetable", **_auth(world_b["teacher_user"]))
    assert res.status_code == 200, res.content
    assert res.json() == []


@pytest.mark.django_db
def test_requires_auth(client: Client, world_a) -> None:
    res = client.get("/api/v1/teacher/timetable/today")
    assert res.status_code == 401
