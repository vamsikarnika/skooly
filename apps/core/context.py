"""Tenant context — stored in contextvars for async safety.

The TenantMiddleware sets the current school's id on every request (decoded from
the JWT). TenantManager reads it to scope every queryset. Always fail closed:
if no school is set, the manager returns an empty queryset.

Use ``with use_school(school)`` in non-request code paths (Celery tasks,
management commands) to set the context explicitly.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.schools.models import School

_current_school_id: ContextVar[int | None] = ContextVar("current_school_id", default=None)


def set_current_school_id(school_id: int | None) -> None:
    _current_school_id.set(school_id)


def get_current_school_id() -> int | None:
    return _current_school_id.get()


def get_current_school() -> School | None:
    school_id = get_current_school_id()
    if school_id is None:
        return None
    from apps.schools.models import School

    return School.all_tenants.filter(id=school_id).first()


@contextmanager
def use_school(school: School | int | None) -> Iterator[None]:
    """Set the current school for a block of code. Restores prior value on exit."""
    school_id = school.id if hasattr(school, "id") else school
    token = _current_school_id.set(school_id)
    try:
        yield
    finally:
        _current_school_id.reset(token)
