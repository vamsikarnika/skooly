"""Admin announcements — mounted on the admin API at /api/v1/.

Admins compose broadcast notices targeted school-wide, at a class, or at a
single section. Delivery (WhatsApp/push) lands with the comms module; for now
this persists the notice and reports how many active students it reaches.
The teacher and parent apps already consume these rows read-only.
"""

from __future__ import annotations

from datetime import date as date_type

from django.http import HttpRequest
from ninja import Query, Router

from apps.academics.models import Class, Section, StudentEnrollment, TeacherAssignment
from apps.accounts.auth import jwt_auth
from apps.accounts.models import Role
from apps.communications.models import (
    Announcement,
    AnnouncementCategory,
    AnnouncementRecipient,
)
from apps.core.audit import log_action
from apps.core.exceptions import Forbidden, NotFound, ValidationFailed
from apps.core.helpers import get_in_tenant, today_local
from apps.core.schemas import ActionResponse, CamelSchema
from apps.people.models import Student, Teacher

router = Router(tags=["announcements"], auth=jwt_auth, by_alias=True)

# A list this size covers a school's full notice history without pagination;
# revisit if a school ever blows past it.
LIST_LIMIT = 200


def _user(request: HttpRequest):  # type: ignore[no-untyped-def]
    return request.auth  # type: ignore[attr-defined]


def _require_admin(request: HttpRequest) -> None:
    if _user(request).role != Role.ADMIN:
        raise Forbidden("Admin role required.")


def _school(request: HttpRequest):  # type: ignore[no-untyped-def]
    school = _user(request).school
    if school is None:
        raise NotFound("Current user has no school.")
    return school


class AnnouncementOut(CamelSchema):
    id: int
    title: str
    body: str
    date: str
    category: str
    recipient_type: str
    target_class_id: int | None = None
    target_class_name: str | None = None
    target_section_id: int | None = None
    target_section_name: str | None = None
    audience: str
    recipient_count: int
    created_at: str


class AnnouncementCreateRequest(CamelSchema):
    title: str
    body: str = ""
    category: str
    recipient_type: str = AnnouncementRecipient.EVERYONE
    date: date_type | None = None
    target_class_id: int | None = None
    target_section_id: int | None = None


class RecipientCountOut(CamelSchema):
    recipient_count: int


def _student_count(school, target_class, target_section) -> int:  # type: ignore[no-untyped-def]
    """Active students in scope (the parent audience)."""
    if target_section is not None:
        return StudentEnrollment.objects.filter(
            section=target_section, status="active"
        ).count()
    if target_class is not None:
        return StudentEnrollment.objects.filter(
            section__class_obj=target_class, status="active"
        ).count()
    return Student.objects.filter(school=school, status="active").count()


def _teacher_count(school, target_class, target_section) -> int:  # type: ignore[no-untyped-def]
    """Distinct teachers in scope (the teacher audience). Class/section scope
    by assignment; school-wide counts every active teacher."""
    if target_section is not None:
        return (
            TeacherAssignment.objects.filter(section=target_section)
            .values("teacher")
            .distinct()
            .count()
        )
    if target_class is not None:
        return (
            TeacherAssignment.objects.filter(section__class_obj=target_class)
            .values("teacher")
            .distinct()
            .count()
        )
    return Teacher.objects.filter(school=school, status="active").count()


def _recipient_count(recipient_type, school, target_class, target_section) -> int:  # type: ignore[no-untyped-def]
    """How many people the notice reaches, per its intended audience."""
    if recipient_type == AnnouncementRecipient.TEACHERS:
        return _teacher_count(school, target_class, target_section)
    if recipient_type == AnnouncementRecipient.PARENTS:
        return _student_count(school, target_class, target_section)
    return _student_count(school, target_class, target_section) + _teacher_count(
        school, target_class, target_section
    )


def _audience(a: Announcement) -> str:
    """Human-readable target. Class names already carry the "Class N" label."""
    if a.target_section_id:
        return f"{a.target_section.class_obj.name} · Section {a.target_section.name}"
    if a.target_class_id:
        return f"{a.target_class.name} (all sections)"
    return "All school"


def _serialize(a: Announcement, school) -> dict:  # type: ignore[no-untyped-def]
    return {
        "id": a.id,
        "title": a.title,
        "body": a.body,
        "date": a.date.isoformat(),
        "category": a.category,
        "recipient_type": a.recipient_type,
        "target_class_id": a.target_class_id,
        "target_class_name": a.target_class.name if a.target_class_id else None,
        "target_section_id": a.target_section_id,
        "target_section_name": a.target_section.name if a.target_section_id else None,
        "audience": _audience(a),
        "recipient_count": _recipient_count(
            a.recipient_type, school, a.target_class, a.target_section
        ),
        "created_at": a.created_at.isoformat(),
    }


def _resolve_targets(school, recipient_type, target_class_id, target_section_id):  # type: ignore[no-untyped-def]
    """Validate the recipient/target combination and resolve the (tenant-scoped)
    class/section objects. Shared by create and the count preview."""
    if recipient_type not in AnnouncementRecipient.values:
        raise ValidationFailed(f"Unknown recipient '{recipient_type}'.")
    if target_class_id and target_section_id:
        raise ValidationFailed("Target a class or a section, not both.")
    target_class = (
        get_in_tenant(Class, school, pk=target_class_id) if target_class_id else None
    )
    target_section = (
        get_in_tenant(Section, school, pk=target_section_id) if target_section_id else None
    )
    return target_class, target_section


@router.get("/announcements/recipient-count", response=RecipientCountOut)
def recipient_count_preview(
    request: HttpRequest,
    recipient_type: str = Query(default=AnnouncementRecipient.EVERYONE, alias="recipientType"),
    target_class_id: int | None = Query(default=None, alias="targetClassId"),
    target_section_id: int | None = Query(default=None, alias="targetSectionId"),
) -> dict:
    """How many people the given audience would reach — for the compose preview.
    Same logic as create, so the preview never drifts from the real send."""
    school = _school(request)
    target_class, target_section = _resolve_targets(
        school, recipient_type, target_class_id, target_section_id
    )
    return {
        "recipient_count": _recipient_count(
            recipient_type, school, target_class, target_section
        )
    }


@router.get("/announcements", response=list[AnnouncementOut])
def list_announcements(request: HttpRequest) -> list[dict]:
    school = _school(request)
    rows = (
        Announcement.objects.filter(school=school)
        .select_related("target_class", "target_section__class_obj")
        .order_by("-date", "-id")[:LIST_LIMIT]
    )
    return [_serialize(a, school) for a in rows]


@router.post("/announcements", response=AnnouncementOut)
def create_announcement(request: HttpRequest, payload: AnnouncementCreateRequest) -> dict:
    _require_admin(request)
    school = _school(request)

    if not payload.title.strip():
        raise ValidationFailed("Title is required.")
    if payload.category not in AnnouncementCategory.values:
        raise ValidationFailed(f"Unknown category '{payload.category}'.")
    target_class, target_section = _resolve_targets(
        school, payload.recipient_type, payload.target_class_id, payload.target_section_id
    )

    announcement = Announcement.objects.create(
        school=school,
        title=payload.title.strip(),
        body=payload.body.strip(),
        date=payload.date or today_local(),
        category=payload.category,
        recipient_type=payload.recipient_type,
        target_class=target_class,
        target_section=target_section,
    )
    log_action(
        school_id=school.id,
        user_id=_user(request).id,
        action="announcement.create",
        model_name="Announcement",
        object_id=announcement.id,
    )
    return _serialize(announcement, school)


@router.delete("/announcements/{announcement_id}", response=ActionResponse)
def delete_announcement(request: HttpRequest, announcement_id: int) -> ActionResponse:
    _require_admin(request)
    school = _school(request)
    announcement = get_in_tenant(Announcement, school, pk=announcement_id)
    announcement.soft_delete()
    log_action(
        school_id=school.id,
        user_id=_user(request).id,
        action="announcement.delete",
        model_name="Announcement",
        object_id=announcement_id,
    )
    return ActionResponse(success=True, message="Announcement deleted.")
