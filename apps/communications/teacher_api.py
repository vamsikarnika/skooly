"""Teacher app announcements — mounted on teacher_api.

Consumption-only: teachers see school-wide announcements plus any targeted at
a class or section they're assigned to this academic year. Read state is
per-teacher (AnnouncementTeacherRead), independent of the parent-scoped
Announcement.is_read flag.
"""

from __future__ import annotations

from typing import Any

from dateutil.relativedelta import relativedelta
from django.db.models import Q
from django.http import HttpRequest
from ninja import Query, Router

from apps.academics.models import TeacherAssignment
from apps.accounts.teacher_auth import get_teacher, teacher_jwt_auth
from apps.communications.models import (
    Announcement,
    AnnouncementRecipient,
    AnnouncementTeacherRead,
)
from apps.core.exceptions import NotFound
from apps.core.helpers import today_local
from apps.core.schemas import ActionResponse, CamelSchema

router = Router(tags=["teacher-announcements"], auth=teacher_jwt_auth, by_alias=True)

# Allowed look-back windows in months. Anything else falls back to 1; capped
# at 12 so the list never grows unbounded.
ALLOWED_MONTHS = (1, 3, 6, 12)

# Announcements a teacher is allowed to see, by intended audience.
TEACHER_RECIPIENTS = (AnnouncementRecipient.TEACHERS, AnnouncementRecipient.EVERYONE)


class AnnouncementOut(CamelSchema):
    id: int
    title: str
    body: str
    date: str
    category: str
    is_read: bool


def _academic_year_id(request: HttpRequest) -> int | None:
    school = request.auth.school  # type: ignore[attr-defined]
    return school.current_academic_year_id if school else None


def _teacher_scope(teacher: Any, academic_year_id: int | None) -> tuple[list[int], list[int]]:
    """The class + section ids the teacher is assigned to this year."""
    assignments = TeacherAssignment.objects.filter(
        teacher=teacher, academic_year_id=academic_year_id
    )
    class_ids = list(
        assignments.values_list("section__class_obj_id", flat=True).distinct()
    )
    section_ids = list(assignments.values_list("section_id", flat=True).distinct())
    return class_ids, section_ids


def _visible_q(class_ids: list[int], section_ids: list[int]) -> Q:
    """School-wide announcements + ones targeted at the teacher's classes/sections."""
    return (
        Q(target_class__isnull=True, target_section__isnull=True)
        | Q(target_class_id__in=class_ids)
        | Q(target_section_id__in=section_ids)
    )


@router.get("/announcements", response=list[AnnouncementOut])
def list_announcements(request: HttpRequest, months: int = Query(1)) -> list[dict]:
    teacher = get_teacher(request)
    months = months if months in ALLOWED_MONTHS else 1
    cutoff = today_local() - relativedelta(months=months)
    class_ids, section_ids = _teacher_scope(teacher, _academic_year_id(request))
    rows = list(
        Announcement.objects.filter(
            _visible_q(class_ids, section_ids),
            date__gte=cutoff,
            recipient_type__in=TEACHER_RECIPIENTS,
        ).order_by("-date", "-id")[:50]
    )
    read_ids = set(
        AnnouncementTeacherRead.objects.filter(
            teacher=teacher, announcement_id__in=[a.id for a in rows]
        ).values_list("announcement_id", flat=True)
    )
    return [
        {
            "id": a.id,
            "title": a.title,
            "body": a.body,
            "date": a.date.isoformat(),
            "category": a.category,
            "is_read": a.id in read_ids,
        }
        for a in rows
    ]


@router.patch("/announcements/{announcement_id}/read", response=ActionResponse)
def mark_announcement_read(request: HttpRequest, announcement_id: int) -> dict:
    teacher = get_teacher(request)
    class_ids, section_ids = _teacher_scope(teacher, _academic_year_id(request))
    announcement = (
        Announcement.objects.filter(id=announcement_id)
        .filter(_visible_q(class_ids, section_ids))
        .filter(recipient_type__in=TEACHER_RECIPIENTS)
        .first()
    )
    if announcement is None:
        raise NotFound("No such announcement.")
    AnnouncementTeacherRead.objects.get_or_create(
        school=announcement.school, announcement=announcement, teacher=teacher
    )
    return {"success": True}
