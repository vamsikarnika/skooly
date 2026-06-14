"""HTTP tests for the parent app announcements endpoints."""

from __future__ import annotations

from datetime import date

import pytest
from django.test import Client

from apps.academics.models import StudentEnrollment
from apps.accounts.models import Role, User
from apps.accounts.services import issue_tokens_for_user
from apps.communications.models import Announcement, AnnouncementCategory
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
    return user, student


def _ann(school, *, title, target_class=None, target_section=None, is_read=False):
    return Announcement.objects.create(
        school=school, title=title, body="b", date=date(2026, 5, 20),
        category=AnnouncementCategory.SCHOOL,
        target_class=target_class, target_section=target_section, is_read=is_read,
    )


@pytest.mark.django_db
def test_list_returns_school_class_and_section_scoped(client: Client, world_a) -> None:
    user, student = _parent_with_child(world_a)
    school = world_a["school"]
    cls = world_a["class"]
    section_a = world_a["section_a"]
    section_b = world_a["section_b"]

    _ann(school, title="school-wide")
    _ann(school, title="class match", target_class=cls)
    _ann(school, title="my section", target_section=section_a)
    _ann(school, title="other section", target_section=section_b)

    res = client.get(f"/api/v1/parent/children/{student.id}/announcements", **_auth(user))
    assert res.status_code == 200, res.content
    titles = {a["title"] for a in res.json()}
    assert titles == {"school-wide", "class match", "my section"}


@pytest.mark.django_db
def test_mark_read(client: Client, world_a) -> None:
    user, _ = _parent_with_child(world_a)
    a = _ann(world_a["school"], title="hi")
    res = client.patch(f"/api/v1/parent/announcements/{a.id}/read", **_auth(user))
    assert res.status_code == 200, res.content
    a.refresh_from_db()
    assert a.is_read is True


@pytest.mark.django_db
def test_teacher_only_announcement_hidden_from_parents(client: Client, world_a) -> None:
    from apps.communications.models import AnnouncementRecipient

    user, student = _parent_with_child(world_a)
    school = world_a["school"]
    Announcement.objects.create(
        school=school, title="staff-only", body="", date=date(2026, 5, 20),
        category=AnnouncementCategory.SCHOOL,
        recipient_type=AnnouncementRecipient.TEACHERS,
    )
    Announcement.objects.create(
        school=school, title="for-parents", body="", date=date(2026, 5, 20),
        category=AnnouncementCategory.SCHOOL,
        recipient_type=AnnouncementRecipient.PARENTS,
    )
    res = client.get(f"/api/v1/parent/children/{student.id}/announcements", **_auth(user))
    titles = {a["title"] for a in res.json()}
    assert "staff-only" not in titles
    assert "for-parents" in titles


@pytest.mark.django_db
def test_mark_read_cross_tenant_404(client: Client, world_a, world_b) -> None:
    user_a, _ = _parent_with_child(world_a, phone="+919876512345")
    _parent_with_child(world_b, phone="+919876599999")
    other = _ann(world_b["school"], title="theirs")
    res = client.patch(f"/api/v1/parent/announcements/{other.id}/read", **_auth(user_a))
    assert res.status_code == 404
    other.refresh_from_db()
    assert other.is_read is False


@pytest.mark.django_db
def test_mark_read_other_class_in_same_school_404(client: Client, world_a) -> None:
    """Parent at section A can't mark a section-B-only announcement read."""
    user, _ = _parent_with_child(world_a)
    other = _ann(world_a["school"], title="section B only", target_section=world_a["section_b"])
    res = client.patch(f"/api/v1/parent/announcements/{other.id}/read", **_auth(user))
    assert res.status_code == 404


@pytest.mark.django_db
def test_home_feed_includes_unread_announcement(client: Client, world_a) -> None:
    user, student = _parent_with_child(world_a)
    _ann(world_a["school"], title="PTM Saturday", is_read=False)
    res = client.get(f"/api/v1/parent/children/{student.id}/feed", **_auth(user))
    assert res.status_code == 200, res.content
    items = res.json()["items"]
    anns = [i for i in items if i["type"] == "announcement"]
    assert anns and anns[0]["message"] == "PTM Saturday"
    assert anns[0]["linkTo"] == "/more/announcements"
