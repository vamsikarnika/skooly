"""Teacher-app JWT auth.

The teacher mobile app (skooly-guru) talks to its own NinjaAPI mounted at
``/api/v1/teacher/``. Every route there uses :data:`teacher_jwt_auth`, which
rejects any token that isn't a teacher's — an admin or parent token gets a
401, so the API surface is hard-locked to teachers regardless of the handler.

Tenant scoping is inherited from the base ``JWTAuth``: it re-pins
``school_id`` on the request context, so the ``TenantManager`` keeps every
query scoped to the teacher's school.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest

from apps.accounts.auth import JWTAuth
from apps.accounts.models import Role, User
from apps.core.exceptions import NotFound


class TeacherJWTAuth(JWTAuth):
    def authenticate(self, request: Any, token: str) -> User | None:
        user = super().authenticate(request, token)
        if user is None:
            return None
        if user.role != Role.TEACHER:
            # Not a teacher token — treat as unauthenticated for this API.
            return None
        return user


teacher_jwt_auth = TeacherJWTAuth()


def get_teacher(request: HttpRequest) -> Any:
    """Resolve the ``Teacher`` profile for the authenticated teacher user.

    Intra-school scoping anchor: teacher endpoints filter through this profile
    (their assignments, their tests) on top of the school-level TenantManager.
    Raises 404 if the user has no linked teacher profile.
    """
    user = request.auth  # type: ignore[attr-defined]
    try:
        return user.teacher_profile
    except ObjectDoesNotExist as exc:
        raise NotFound("No teacher profile linked to this account.") from exc
