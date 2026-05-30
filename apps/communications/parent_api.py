"""Parent app in-app notifications — mounted on parent_api.

List is scoped to a single linked child; mark-read verifies the notification
belongs to one of the caller's children (404 otherwise — no existence leak).
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Q
from django.http import HttpRequest
from django.utils import timezone
from ninja import Router

from apps.accounts.parent_auth import get_parent, get_parent_child, parent_jwt_auth
from apps.accounts.parent_schemas import SuccessResponse
from apps.communications.models import Announcement, Notification
from apps.core.exceptions import NotFound
from apps.core.schemas import CamelSchema

router = Router(tags=["parent-notifications"], auth=parent_jwt_auth, by_alias=True)

_IST = ZoneInfo(getattr(settings, "DISPLAY_TIME_ZONE", "Asia/Kolkata"))


class NotificationOut(CamelSchema):
    id: int
    type: str
    title: str
    body: str
    is_read: bool
    created_at: str
    link_to: str | None = None


class NotificationListOut(CamelSchema):
    unread_count: int
    notifications: list[NotificationOut]


def _serialize(n: Notification) -> dict:
    return {
        "id": n.id,
        "type": n.type,
        "title": n.title,
        "body": n.body,
        "is_read": n.is_read,
        "created_at": n.created_at.astimezone(_IST).isoformat(),
        "link_to": n.link_to or None,
    }


@router.get("/children/{child_id}/notifications", response=NotificationListOut)
def list_notifications(request: HttpRequest, child_id: int) -> dict:
    student = get_parent_child(request, child_id)
    # Hide notifications past their expiry; null expiry never expires.
    qs = Notification.objects.filter(student=student).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    )
    unread_count = qs.filter(is_read=False).count()
    # Model ordering already puts unread first, then newest.
    rows = list(qs[:50])
    return {
        "unread_count": unread_count,
        "notifications": [_serialize(n) for n in rows],
    }


@router.patch("/notifications/{notification_id}/read", response=SuccessResponse)
def mark_read(request: HttpRequest, notification_id: int) -> dict:
    parent = get_parent(request)
    notification = (
        Notification.objects.filter(id=notification_id, student__parent_links__parent=parent)
        .distinct()
        .first()
    )
    if notification is None:
        raise NotFound("No such notification.")
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read", "updated_at"])
    return {"success": True}


@router.post("/children/{child_id}/notifications/read-all", response=SuccessResponse)
def mark_all_read(request: HttpRequest, child_id: int) -> dict:
    student = get_parent_child(request, child_id)
    Notification.objects.filter(student=student, is_read=False).update(is_read=True)
    return {"success": True}


# ---------------------------------------------------------------------------
# Announcements
# ---------------------------------------------------------------------------


class AnnouncementOut(CamelSchema):
    id: int
    title: str
    body: str
    date: str
    category: str
    is_read: bool


def _student_class_section(student) -> tuple[int | None, int | None]:
    """Resolve the child's current class + section ids for announcement scoping."""
    enrollment = (
        student.enrollments.filter(status="active")
        .select_related("section__class_obj")
        .order_by("-academic_year_id")
        .first()
    )
    if enrollment is None:
        return None, None
    return enrollment.section.class_obj_id, enrollment.section_id


def announcement_queryset_for(student):
    """School-wide announcements + ones targeted at the child's class or
    section. Tenant scoping comes from the manager."""
    class_id, section_id = _student_class_section(student)
    # School-wide: no target_class AND no target_section.
    school_wide = Q(target_class__isnull=True, target_section__isnull=True)
    class_match = Q(target_class_id=class_id) if class_id is not None else Q(pk__in=[])
    section_match = Q(target_section_id=section_id) if section_id is not None else Q(pk__in=[])
    return Announcement.objects.filter(school_wide | class_match | section_match)


@router.get("/children/{child_id}/announcements", response=list[AnnouncementOut])
def list_announcements(request: HttpRequest, child_id: int) -> list[dict]:
    student = get_parent_child(request, child_id)
    qs = announcement_queryset_for(student).order_by("-date", "-id")[:50]
    return [
        {
            "id": a.id,
            "title": a.title,
            "body": a.body,
            "date": a.date.isoformat(),
            "category": a.category,
            "is_read": a.is_read,
        }
        for a in qs
    ]


@router.patch("/announcements/{announcement_id}/read", response=SuccessResponse)
def mark_announcement_read(request: HttpRequest, announcement_id: int) -> dict:
    parent = get_parent(request)
    # Verify the announcement is one this parent can actually see (via any of
    # their linked children's class/section, or school-wide).
    parent_class_ids = list(
        parent.students.filter(status="active")
        .values_list("enrollments__section__class_obj_id", flat=True)
        .distinct()
    )
    parent_section_ids = list(
        parent.students.filter(status="active")
        .values_list("enrollments__section_id", flat=True)
        .distinct()
    )
    visible = (
        Q(target_class__isnull=True, target_section__isnull=True)
        | Q(target_class_id__in=parent_class_ids)
        | Q(target_section_id__in=parent_section_ids)
    )
    announcement = Announcement.objects.filter(id=announcement_id).filter(visible).first()
    if announcement is None:
        raise NotFound("No such announcement.")
    if not announcement.is_read:
        announcement.is_read = True
        announcement.save(update_fields=["is_read", "updated_at"])
    return {"success": True}
