"""Admin user management (skooly-stride Settings → Users).

Access is controlled: only an existing admin can provision accounts — there's
no self-registration. New admins get an auto-generated password to share; they
can change it later. Single admin role (full access).
"""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router

from apps.accounts import services
from apps.accounts.auth import jwt_auth
from apps.accounts.models import Role, User
from apps.accounts.schemas import (
    AdminUserOut,
    CreateAdminRequest,
    CreateAdminResult,
    UpdateAdminRequest,
)
from apps.core.exceptions import Forbidden, NotFound, ValidationFailed

router = Router(tags=["admin-users"], auth=jwt_auth, by_alias=True)


def _actor(request: HttpRequest) -> User:
    return request.auth  # type: ignore[attr-defined,return-value]


def _require_admin(request: HttpRequest) -> None:
    if _actor(request).role != Role.ADMIN:
        raise Forbidden("Admin role required.")


def _school(request: HttpRequest):  # type: ignore[no-untyped-def]
    school = _actor(request).school
    if school is None:
        raise NotFound("Current user has no school.")
    return school


def _serialize(user: User, *, current_id: int) -> dict:
    return {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "full_name": user.get_full_name() or user.first_name,
        "phone": services._format_in_phone(user.phone),
        "email": user.email,
        "is_active": user.is_active,
        "last_login_at": user.last_login_at,
        "is_current": user.id == current_id,
    }


def _get_admin(school, user_id: int) -> User:  # type: ignore[no-untyped-def]
    user = User.objects.filter(school=school, role=Role.ADMIN, pk=user_id).first()
    if user is None:
        raise NotFound("No such admin user.")
    return user


@router.get("/admin-users", response=list[AdminUserOut])
def list_admins(request: HttpRequest) -> list[dict]:
    school = _school(request)
    current_id = _actor(request).id
    admins = User.objects.filter(school=school, role=Role.ADMIN).order_by(
        "-is_active", "first_name", "id"
    )
    return [_serialize(u, current_id=current_id) for u in admins]


@router.post("/admin-users", response=CreateAdminResult)
def create_admin(request: HttpRequest, payload: CreateAdminRequest) -> dict:
    _require_admin(request)
    school = _school(request)
    user, password = services.create_admin_user(
        school=school,
        first_name=payload.first_name,
        last_name=payload.last_name,
        phone=payload.phone,
        email=payload.email,
    )
    return {
        "user": _serialize(user, current_id=_actor(request).id),
        "generated_password": password,
    }


@router.patch("/admin-users/{user_id}", response=AdminUserOut)
def update_admin(request: HttpRequest, user_id: int, payload: UpdateAdminRequest) -> dict:
    _require_admin(request)
    school = _school(request)
    actor = _actor(request)
    user = _get_admin(school, user_id)

    if payload.is_active is False:
        if user.id == actor.id:
            raise ValidationFailed("You can't deactivate your own account.")
        active_admins = User.objects.filter(
            school=school, role=Role.ADMIN, is_active=True
        ).count()
        if active_admins <= 1:
            raise ValidationFailed("At least one active admin is required.")

    if payload.first_name is not None:
        user.first_name = payload.first_name.strip()
    if payload.last_name is not None:
        user.last_name = payload.last_name.strip()
    if payload.email is not None:
        email = payload.email.strip()
        if (
            email
            and User.objects.filter(school=school, email__iexact=email)
            .exclude(pk=user.id)
            .exists()
        ):
            raise ValidationFailed("That email is already in use at this school.")
        user.email = email
    if payload.is_active is not None:
        user.is_active = payload.is_active

    user.save()
    return _serialize(user, current_id=actor.id)
