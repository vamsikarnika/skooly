"""Permission helpers — used by endpoints to enforce role/tenant rules."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.http import HttpRequest

from .context import get_current_school_id
from .exceptions import Forbidden, Unauthorized


def require_authenticated(request: HttpRequest) -> Any:
    user = getattr(request, "auth", None)
    if user is None or not getattr(user, "is_authenticated", False):
        raise Unauthorized("Authentication required.")
    return user


def require_role(*roles: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Endpoint decorator. Use after the auth dependency."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
            user = require_authenticated(request)
            if user.role not in roles:
                raise Forbidden(f"Requires one of: {', '.join(roles)}.")
            return fn(request, *args, **kwargs)

        return wrapper

    return decorator


def require_school_match(request: HttpRequest, school_id: int) -> None:
    """Defence-in-depth: confirm the request's school context matches the
    school_id being accessed. The TenantManager already does this for ORM
    queries; this helper is for places that bypass the manager."""
    current = get_current_school_id()
    if current is None or current != school_id:
        raise Forbidden("Cross-tenant access denied.")
