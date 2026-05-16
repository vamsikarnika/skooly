"""TenantMiddleware — sets the current school on the request context.

The middleware extracts the school_id from the JWT in ``Authorization: Bearer``,
sets it on a contextvar (read by TenantManager), and — when RLS is enabled —
sets the ``app.current_school_id`` Postgres GUC for the connection so
Row-Level Security policies kick in.

The JWT itself is verified later by django-ninja-jwt at the endpoint level.
This middleware does NOT authenticate; it only reads the school_id claim if
present, and clears the context after the response.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import jwt
from django.conf import settings
from django.db import connection
from django.http import HttpRequest, HttpResponse

from .context import set_current_school_id

logger = logging.getLogger(__name__)


class TenantMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        school_id = self._extract_school_id(request)
        set_current_school_id(school_id)

        use_rls = getattr(settings, "TENANT_USE_POSTGRES_RLS", False)
        if use_rls and school_id is not None:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.current_school_id', %s, true)", [str(school_id)])

        try:
            response = self.get_response(request)
        finally:
            set_current_school_id(None)
        return response

    @staticmethod
    def _extract_school_id(request: HttpRequest) -> int | None:
        auth = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth.startswith("Bearer "):
            return None
        token = auth[len("Bearer ") :].strip()
        if not token:
            return None
        try:
            # We decode WITHOUT verifying the signature here on purpose — the
            # endpoint-level JWT auth will do the proper verification. We just
            # need the school_id to scope queries before the auth check runs.
            # IMPORTANT: never trust this value for authorization decisions —
            # only for queryset scoping. The auth layer enforces validity.
            payload = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError:
            return None
        school_id = payload.get("school_id")
        if isinstance(school_id, int):
            return school_id
        return None
