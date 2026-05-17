"""Cross-cutting helpers used by service layers.

`get_in_tenant` is the defence-in-depth guard for write endpoints: even if a
caller is authenticated, we never let them mutate a row that doesn't belong
to their school. Always 404 (not 403) to avoid leaking existence.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Model, QuerySet

from apps.core.exceptions import NotFound
from apps.schools.models import School


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
