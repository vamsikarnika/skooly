"""HTTP tests for the parent app notifications endpoints."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.academics.models import StudentEnrollment
from apps.accounts.models import Role, User
from apps.accounts.services import issue_tokens_for_user
from apps.communications.models import Notification, NotificationType
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


def _notif(school, student, *, title: str, is_read: bool, type=NotificationType.ATTENDANCE):
    return Notification.objects.create(
        school=school, student=student, type=type, title=title, body="b", is_read=is_read
    )


@pytest.mark.django_db
def test_list_unread_first_with_count(client: Client, world_a) -> None:
    user, student = _parent_with_child(world_a)
    school = world_a["school"]
    _notif(school, student, title="old read", is_read=True)
    _notif(school, student, title="unread 1", is_read=False)
    _notif(school, student, title="unread 2", is_read=False)

    res = client.get(f"/api/v1/parent/children/{student.id}/notifications", **_auth(user))
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["unreadCount"] == 2
    assert len(body["notifications"]) == 3
    # Unread first.
    assert body["notifications"][0]["isRead"] is False
    assert body["notifications"][-1]["isRead"] is True
    assert "createdAt" in body["notifications"][0]


@pytest.mark.django_db
def test_mark_read(client: Client, world_a) -> None:
    user, student = _parent_with_child(world_a)
    n = _notif(world_a["school"], student, title="x", is_read=False)
    res = client.patch(f"/api/v1/parent/notifications/{n.id}/read", **_auth(user))
    assert res.status_code == 200, res.content
    assert res.json() == {"success": True}
    n.refresh_from_db()
    assert n.is_read is True


@pytest.mark.django_db
def test_mark_all_read(client: Client, world_a) -> None:
    user, student = _parent_with_child(world_a)
    _notif(world_a["school"], student, title="a", is_read=False)
    _notif(world_a["school"], student, title="b", is_read=False)
    res = client.post(
        f"/api/v1/parent/children/{student.id}/notifications/read-all", **_auth(user)
    )
    assert res.status_code == 200, res.content
    assert Notification.objects.filter(student=student, is_read=False).count() == 0


@pytest.mark.django_db
def test_expired_notifications_are_hidden(client: Client, world_a) -> None:
    user, student = _parent_with_child(world_a)
    school = world_a["school"]
    now = timezone.now()
    # Visible: never-expires + future expiry. Hidden: past expiry.
    _notif(school, student, title="no expiry", is_read=False)
    future = _notif(school, student, title="future", is_read=False)
    future.expires_at = now + timedelta(hours=1)
    future.save(update_fields=["expires_at"])
    expired = _notif(school, student, title="expired", is_read=False)
    expired.expires_at = now - timedelta(minutes=1)
    expired.save(update_fields=["expires_at"])

    res = client.get(f"/api/v1/parent/children/{student.id}/notifications", **_auth(user))
    assert res.status_code == 200, res.content
    body = res.json()
    titles = {n["title"] for n in body["notifications"]}
    assert titles == {"no expiry", "future"}
    # Expired one is excluded from the unread count too.
    assert body["unreadCount"] == 2


@pytest.mark.django_db
def test_unlinked_child_list_404(client: Client, world_a) -> None:
    user, _student = _parent_with_child(world_a)
    stranger = StudentFactory(school=world_a["school"], first_name="Stranger")
    res = client.get(f"/api/v1/parent/children/{stranger.id}/notifications", **_auth(user))
    assert res.status_code == 404


@pytest.mark.django_db
def test_cross_tenant_mark_read_404(client: Client, world_a, world_b) -> None:
    user_a, _ = _parent_with_child(world_a, phone="+919876512345")
    _ub, student_b = _parent_with_child(world_b, phone="+919876599999")
    other = _notif(world_b["school"], student_b, title="theirs", is_read=False)
    res = client.patch(f"/api/v1/parent/notifications/{other.id}/read", **_auth(user_a))
    assert res.status_code == 404
    other.refresh_from_db()
    assert other.is_read is False
