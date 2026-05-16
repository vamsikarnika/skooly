"""JWT auth dependency for Django Ninja endpoints.

Wraps ninja_jwt's JWTAuth so that on successful auth we set the tenant
context (school_id) for the rest of the request.
"""

from __future__ import annotations

from typing import Any

from ninja_jwt.authentication import JWTAuth as _NinjaJWTAuth

from apps.accounts.models import User
from apps.core.context import set_current_school_id


class JWTAuth(_NinjaJWTAuth):
    def authenticate(self, request: Any, token: str) -> User | None:
        user = super().authenticate(request, token)
        if user is None:
            return None
        # ninja_jwt sets request.auth = user; we also pin the tenant context.
        set_current_school_id(user.school_id)
        return user


jwt_auth = JWTAuth()
