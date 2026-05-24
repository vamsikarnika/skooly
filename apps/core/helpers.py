"""Cross-cutting helpers used by service layers.

`get_in_tenant` is the defence-in-depth guard for write endpoints: even if a
caller is authenticated, we never let them mutate a row that doesn't belong
to their school. Always 404 (not 403) to avoid leaking existence.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Model, QuerySet
from django.utils import timezone

from apps.core.exceptions import NotFound
from apps.schools.models import School


def display_tz() -> ZoneInfo:
    """The timezone the API presents times in (IST). Storage stays UTC."""
    return ZoneInfo(getattr(settings, "DISPLAY_TIME_ZONE", "Asia/Kolkata"))


def today_local() -> date_type:
    """Today's date in the display timezone (school-local), not UTC."""
    return timezone.now().astimezone(display_tz()).date()


def hhmm_local(dt: datetime | None) -> str | None:
    """Format a stored (UTC) datetime as ``HH:MM`` in the display timezone."""
    if dt is None:
        return None
    return dt.astimezone(display_tz()).strftime("%H:%M")


def roll_to_int(raw: str | None) -> int | None:
    """Roll numbers are stored as free-text; expose as int when numeric."""
    if raw and raw.isdigit():
        return int(raw)
    return None


def gender_code(value: str) -> str:
    """Map the stored gender label to the single-letter code the apps use."""
    return {"Male": "M", "Female": "F"}.get(value, value[:1].upper() if value else "")


def get_in_tenant[T: Model](
    queryset: QuerySet[T] | type[T],
    school: School,
    *,
    pk: Any = None,
    **filters: Any,
) -> T:
    """Fetch a tenant-scoped row or raise 404. Use this in services that
    take a `school` from `request.auth.school` — never trust the caller-
    supplied id alone."""
    qs = queryset if isinstance(queryset, QuerySet) else queryset.objects.all()
    if pk is not None:
        filters["pk"] = pk
    obj = qs.filter(school=school, **filters).first()
    if obj is None:
        raise NotFound("Not found.")
    return obj
