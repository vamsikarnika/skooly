"""Read-side attendance endpoint tests."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from apps.academics.models import StudentEnrollment
from apps.attendance.models import Attendance, AttendanceStatus
from apps.people.tests.factories import StudentFactory


def _make_student_in_section(world, *, admission, roll="01"):
    s = StudentFactory(school=world["school"], admission_number=admission)
    StudentEnrollment.objects.create(
        school=world["school"],
        student=s,
        section=world["section_a"],
        academic_year=world["year"],
        roll_number=roll,
        enrollment_date=date(2025, 6, 1),
        status="active",
    )
    return s


def _mark(world, student, day, status=AttendanceStatus.PRESENT):
    return Attendance.objects.create(
        school=world["school"],
        student=student,
        section=world["section_a"],
        date=day,
        status=status,
    )


@pytest.mark.django_db
def test_section_attendance_for_date(client, admin_token_a, world_a):
    s1 = _make_student_in_section(world_a, admission="A1", roll="01")
    s2 = _make_student_in_section(world_a, admission="A2", roll="02")
    day = date(2026, 5, 10)
    _mark(world_a, s1, day, AttendanceStatus.PRESENT)
    _mark(world_a, s2, day, AttendanceStatus.ABSENT)

    res = client.get(
        f"/api/v1/sections/{world_a['section_a'].id}/attendance?date={day}",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["sectionName"] == "A"
    assert body["className"] == "Class 6"
    assert body["summary"]["present"] == 1
    assert body["summary"]["absent"] == 1
    assert body["summary"]["notMarked"] == 0
    assert {m["studentName"] for m in body["marks"]} == {s1.full_name, s2.full_name}


@pytest.mark.django_db
def test_section_attendance_unmarked_students(client, admin_token_a, world_a):
    """Students enrolled but not marked appear with status=null."""
    s = _make_student_in_section(world_a, admission="UN1")
    res = client.get(
        f"/api/v1/sections/{world_a['section_a'].id}/attendance?date=2026-05-11",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200
    body = res.json()
    assert body["summary"]["notMarked"] == 1
    mark = next(m for m in body["marks"] if m["studentId"] == s.id)
    assert mark["status"] is None


@pytest.mark.django_db
def test_section_attendance_cross_tenant_404(client, admin_token_a, world_b):
    res = client.get(
        f"/api/v1/sections/{world_b['section_a'].id}/attendance",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_section_summary_math(client, admin_token_a, world_a):
    """4 marks: 2 present, 1 absent, 1 half_day → attendance % = (2 + 0 + 0.5) / 4 = 62.5%."""
    s = _make_student_in_section(world_a, admission="SM1")
    base = date(2026, 5, 1)
    _mark(world_a, s, base, AttendanceStatus.PRESENT)
    _mark(world_a, s, base + timedelta(days=1), AttendanceStatus.PRESENT)
    _mark(world_a, s, base + timedelta(days=2), AttendanceStatus.ABSENT)
    _mark(world_a, s, base + timedelta(days=3), AttendanceStatus.HALF_DAY)

    res = client.get(
        f"/api/v1/sections/{world_a['section_a'].id}/attendance/summary"
        f"?from={base}&to={base + timedelta(days=4)}",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200
    body = res.json()
    row = next(r for r in body["students"] if r["studentId"] == s.id)
    assert row["present"] == 2
    assert row["absent"] == 1
    assert row["halfDay"] == 1
    assert row["totalMarked"] == 4
    assert row["attendancePct"] == 62.5
    assert body["schoolDays"] == 4


@pytest.mark.django_db
def test_section_summary_late_counts_as_present(client, admin_token_a, world_a):
    """Late students are still present — should count fully toward attendance."""
    s = _make_student_in_section(world_a, admission="LT1")
    base = date(2026, 5, 1)
    _mark(world_a, s, base, AttendanceStatus.LATE)
    _mark(world_a, s, base + timedelta(days=1), AttendanceStatus.LATE)
    _mark(world_a, s, base + timedelta(days=2), AttendanceStatus.PRESENT)

    res = client.get(
        f"/api/v1/sections/{world_a['section_a'].id}/attendance/summary"
        f"?from={base}&to={base + timedelta(days=3)}",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    row = next(r for r in res.json()["students"] if r["studentId"] == s.id)
    assert row["attendancePct"] == 100.0
    assert row["late"] == 2


@pytest.mark.django_db
def test_section_summary_cross_tenant_404(client, admin_token_a, world_b):
    res = client.get(
        f"/api/v1/sections/{world_b['section_a'].id}/attendance/summary",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_student_history(client, admin_token_a, world_a):
    s = _make_student_in_section(world_a, admission="H1")
    base = date(2026, 5, 1)
    for i, status in enumerate([
        AttendanceStatus.PRESENT, AttendanceStatus.PRESENT,
        AttendanceStatus.ABSENT, AttendanceStatus.PRESENT,
    ]):
        _mark(world_a, s, base + timedelta(days=i), status)

    res = client.get(
        f"/api/v1/students/{s.id}/attendance?from={base}&to={base + timedelta(days=10)}",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert len(body["days"]) == 4
    assert body["summary"]["present"] == 3
    assert body["summary"]["absent"] == 1
    assert body["attendancePct"] == 75.0


@pytest.mark.django_db
def test_student_history_cross_tenant_404(client, admin_token_a, world_b):
    other = StudentFactory(school=world_b["school"], admission_number="X1")
    res = client.get(
        f"/api/v1/students/{other.id}/attendance",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_attendance_requires_auth(client, world_a):
    res = client.get(f"/api/v1/sections/{world_a['section_a'].id}/attendance")
    assert res.status_code == 401


@pytest.mark.django_db
def test_student_with_no_attendance_history_returns_empty(client, admin_token_a, world_a):
    s = _make_student_in_section(world_a, admission="EMPTY1")
    res = client.get(
        f"/api/v1/students/{s.id}/attendance?from=2026-05-01&to=2026-05-31",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200
    body = res.json()
    assert body["days"] == []
    assert body["attendancePct"] == 0.0
    assert body["summary"]["present"] == 0


@pytest.mark.django_db
def test_attendance_sections_rollup(client, admin_token_a, world_a):
    """Single endpoint returns every section with its daily summary in one shot.
    Avoids the N+1 the dashboard would otherwise create."""
    s1 = _make_student_in_section(world_a, admission="R1", roll="01")
    s2 = _make_student_in_section(world_a, admission="R2", roll="02")
    day = date(2026, 5, 10)
    _mark(world_a, s1, day, AttendanceStatus.PRESENT)
    _mark(world_a, s2, day, AttendanceStatus.ABSENT)

    res = client.get(
        f"/api/v1/attendance/sections?date={day}",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["totalSectionCount"] >= 2  # section_a + section_b from world fixture
    assert body["markedSectionCount"] == 1  # only section_a has marks on this date

    section_a = next(s for s in body["sections"] if s["sectionId"] == world_a["section_a"].id)
    assert section_a["activeStudentCount"] == 2
    assert section_a["summary"]["present"] == 1
    assert section_a["summary"]["absent"] == 1
    assert section_a["summary"]["notMarked"] == 0
    # The class teacher is populated on the row.
    assert "classTeacherName" in section_a

    section_b = next(s for s in body["sections"] if s["sectionId"] == world_a["section_b"].id)
    assert section_b["summary"]["present"] == 0
    assert section_b["summary"]["absent"] == 0

    assert body["totals"]["present"] == 1
    assert body["totals"]["absent"] == 1


@pytest.mark.django_db
def test_attendance_sections_rollup_cross_tenant_isolated(
    client, admin_token_a, world_a, world_b
):
    """Admin of A should only see A's sections, never B's."""
    other_student = StudentFactory(school=world_b["school"], admission_number="LEAK1")
    Attendance.objects.create(
        school=world_b["school"],
        student=other_student,
        section=world_b["section_a"],
        date=date(2026, 5, 10),
        status=AttendanceStatus.PRESENT,
    )

    res = client.get(
        "/api/v1/attendance/sections?date=2026-05-10",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200
    body = res.json()
    section_ids = {s["sectionId"] for s in body["sections"]}
    assert world_b["section_a"].id not in section_ids
    assert world_b["section_b"].id not in section_ids
