"""Parent-app JWT auth.

The parent mobile app (skooly-parent) talks to its own NinjaAPI mounted at
``/api/v1/parent/``. Every route there uses :data:`parent_jwt_auth`, which
rejects any token that isn't a parent's — an admin or teacher token gets a
401, so the API surface is hard-locked to parents regardless of the handler.

Tenant scoping is inherited from the base ``JWTAuth``: it re-pins ``school_id``
on the request context, so the ``TenantManager`` keeps every query scoped to
the parent's school.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest

from apps.accounts.auth import JWTAuth
from apps.accounts.models import Role, User
from apps.core.exceptions import NotFound


class ParentJWTAuth(JWTAuth):
    def authenticate(self, request: Any, token: str) -> User | None:
        user = super().authenticate(request, token)
        if user is None:
            return None
        if user.role != Role.PARENT:
            # Not a parent token — treat as unauthenticated for this API.
            return None
        return user


parent_jwt_auth = ParentJWTAuth()


def get_parent(request: HttpRequest) -> Any:
    """Resolve the ``Parent`` profile for the authenticated parent user.

    Every parent endpoint scopes through this profile (their linked children)
    on top of the school-level TenantManager. Raises 404 if the user has no
    linked parent profile.
    """
    user = request.auth  # type: ignore[attr-defined]
    try:
        return user.parent_profile
    except ObjectDoesNotExist as exc:
        raise NotFound("No parent profile linked to this account.") from exc


def get_parent_child(request: HttpRequest, child_id: int) -> Any:
    """Resolve a ``Student`` that belongs to the authenticated parent.

    The 404 (not 403) is deliberate: a parent must never be able to tell
    whether ``child_id`` exists at another school or under another parent.
    Combined with the TenantManager this is the per-parent scoping anchor.
    """
    from apps.people.models import Student

    parent = get_parent(request)
    student = (
        Student.objects.filter(id=child_id, parent_links__parent=parent)
        .distinct()
        .first()
    )
    if student is None:
        raise NotFound("No such child linked to this account.")
    return student
