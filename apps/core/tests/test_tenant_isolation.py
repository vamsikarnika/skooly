"""Unit tests for the tenant context primitives.

Module 1 doesn't have any TenantScopedModel models yet — the manager will be
exercised end-to-end starting Module 2 (Students, Teachers, etc.). For now we
test the contextvar + ``use_school`` helper directly, and rely on the HTTP
tests in ``apps/schools/tests/test_api.py`` for the full request flow.
"""

from __future__ import annotations

import pytest

from apps.core.context import get_current_school_id, set_current_school_id, use_school
from apps.schools.tests.factories import SchoolFactory


def test_default_school_id_is_none() -> None:
    assert get_current_school_id() is None


def test_set_and_get_school_id() -> None:
    set_current_school_id(42)
    try:
        assert get_current_school_id() == 42
    finally:
        set_current_school_id(None)


@pytest.mark.django_db
def test_use_school_sets_and_restores_context() -> None:
    school_a = SchoolFactory()
    assert get_current_school_id() is None
    with use_school(school_a):
        assert get_current_school_id() == school_a.id
    assert get_current_school_id() is None


@pytest.mark.django_db
def test_use_school_nested_restores_outer() -> None:
    a = SchoolFactory()
    b = SchoolFactory()
    with use_school(a):
        assert get_current_school_id() == a.id
        with use_school(b):
            assert get_current_school_id() == b.id
        assert get_current_school_id() == a.id
    assert get_current_school_id() is None


@pytest.mark.django_db
def test_use_school_accepts_id() -> None:
    school = SchoolFactory()
    with use_school(school.id):
        assert get_current_school_id() == school.id
