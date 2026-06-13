"""HTTP tests for the teacher app announcements endpoints."""

from __future__ import annotations

from datetime import date

import pytest
from django.test import Client

from apps.academics.models import TeacherAssignment
from apps.academics.tests.factories import SubjectFactory
from apps.accounts.services import issue_tokens_for_user
from apps.communications.models import (
    Announcement,
    AnnouncementCategory,
    AnnouncementTeacherRead,
)
from apps.people.tests.factories import TeacherFactory


def _auth(user) -> dict:  # type: ignore[no-untyped-def]
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_tokens_for_user(user)['access_token']}"}


def _teacher(world: dict, *, section=None):  # type: ignore[no-untyped-def]
    """Teacher assigned to one section (default: section_a) for the current year."""
    school, year = world["school"], world["year"]
    section = section or world["section_a"]
    teacher = TeacherFactory(school=school, user=world["teacher_user"])
    subject = SubjectFactory(school=school, name="Science")
    TeacherAssignment.objects.create(
        school=school, teacher=teacher, subject=subject, section=section, academic_year=year
    )
    school.current_academic_year = year
    school.save(update_fields=["current_academic_year"])
    return teacher


def _ann(school, *, title, target_class=None, target_section=None, is_read=False):  # type: ignore[no-untyped-def]
    return Announcement.objects.create(
        school=school, title=title, body="b", date=date(2026, 5, 20),
        category=AnnouncementCategory.SCHOOL,
        target_class=target_class, target_section=target_section, is_read=is_read,
    )


@pytest.mark.django_db
def test_list_returns_school_class_and_section_scoped(client: Client, world_a) -> None:
    _teacher(world_a)  # assigned to section_a
    school, cls = world_a["school"], world_a["class"]

    _ann(school, title="school-wide")
    _ann(school, title="class match", target_class=cls)
    _ann(school, title="my section", target_section=world_a["section_a"])
    _ann(school, title="other section", target_section=world_a["section_b"])

    res = client.get("/api/v1/teacher/announcements", **_auth(world_a["teacher_user"]))
    assert res.status_code == 200, res.content
    titles = {a["title"] for a in res.json()}
    assert titles == {"school-wide", "class match", "my section"}


@pytest.mark.django_db
def test_list_is_read_reflects_per_teacher_state(client: Client, world_a) -> None:
    teacher = _teacher(world_a)
    a = _ann(world_a["school"], title="hi")
    AnnouncementTeacherRead.objects.create(
        school=world_a["school"], announcement=a, teacher=teacher
    )
    res = client.get("/api/v1/teacher/announcements", **_auth(world_a["teacher_user"]))
    assert res.status_code == 200, res.content
    rows = res.json()
    assert rows[0]["title"] == "hi"
    assert rows[0]["isRead"] is True


@pytest.mark.django_db
def test_mark_read_creates_per_teacher_row_without_touching_announcement(
    client: Client, world_a
) -> None:
    teacher = _teacher(world_a)
    a = _ann(world_a["school"], title="hi", is_read=False)

    res = client.patch(
        f"/api/v1/teacher/announcements/{a.id}/read", **_auth(world_a["teacher_user"])
    )
    assert res.status_code == 200, res.content
    assert AnnouncementTeacherRead.objects.all_tenants().filter(
        announcement=a, teacher=teacher
    ).exists()
    # The parent-scoped flag must be untouched.
    a.refresh_from_db()
    assert a.is_read is False


@pytest.mark.django_db
def test_mark_read_is_idempotent(client: Client, world_a) -> None:
    teacher = _teacher(world_a)
    a = _ann(world_a["school"], title="hi")
    auth = _auth(world_a["teacher_user"])
    client.patch(f"/api/v1/teacher/announcements/{a.id}/read", **auth)
    client.patch(f"/api/v1/teacher/announcements/{a.id}/read", **auth)
    assert (
        AnnouncementTeacherRead.objects.all_tenants()
        .filter(announcement=a, teacher=teacher)
        .count()
        == 1
    )


@pytest.mark.django_db
def test_mark_read_other_section_in_same_school_404(client: Client, world_a) -> None:
    """Teacher assigned to section A can't mark a section-B-only announcement read."""
    _teacher(world_a)  # section_a
    other = _ann(world_a["school"], title="section B only", target_section=world_a["section_b"])
    res = client.patch(
        f"/api/v1/teacher/announcements/{other.id}/read", **_auth(world_a["teacher_user"])
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_mark_read_cross_tenant_404(client: Client, world_a, world_b) -> None:
    _teacher(world_a)
    _teacher(world_b)
    other = _ann(world_b["school"], title="theirs")
    res = client.patch(
        f"/api/v1/teacher/announcements/{other.id}/read", **_auth(world_a["teacher_user"])
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_requires_auth(client: Client, world_a) -> None:
    res = client.get("/api/v1/teacher/announcements")
    assert res.status_code == 401
