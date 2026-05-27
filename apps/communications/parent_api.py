"""Parent app in-app notifications — mounted on parent_api.

List is scoped to a single linked child; mark-read verifies the notification
belongs to one of the caller's children (404 otherwise — no existence leak).
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from django.conf import settings
from django.http import HttpRequest
from ninja import Router

from apps.accounts.parent_auth import get_parent, get_parent_child, parent_jwt_auth
from apps.accounts.parent_schemas import SuccessResponse
from apps.communications.models import Notification
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
    qs = Notification.objects.filter(student=student)
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
