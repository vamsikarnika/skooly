"""Unit tests for schools/services.py — update_school, create/update academic year."""

from __future__ import annotations

import pytest

from apps.core.context import use_school
from apps.schools.services import (
    create_academic_year,
    update_academic_year,
    update_school,
)
from apps.schools.tests.factories import AcademicYearFactory

# ---------------------------------------------------------------------------
# update_school
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_update_school_invalid_board_raises(world_a):
    from apps.core.exceptions import Conflict
    with pytest.raises(Conflict, match="Invalid board"):
        update_school(world_a["school"], fields={"board": "NONSENSE"})


@pytest.mark.django_db
def test_update_school_valid_field_persists(world_a):
    update_school(world_a["school"], fields={"name": "Renamed School"})
    world_a["school"].refresh_from_db()
    assert world_a["school"].name == "Renamed School"


@pytest.mark.django_db
def test_update_school_none_values_ignored(world_a):
    original_name = world_a["school"].name
    update_school(world_a["school"], fields={"name": None})
    world_a["school"].refresh_from_db()
    assert world_a["school"].name == original_name


# ---------------------------------------------------------------------------
# create_academic_year
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_academic_year_duplicate_label_raises(world_a):
    from apps.core.exceptions import Conflict
    with use_school(world_a["school"]):
        with pytest.raises(Conflict, match="already exists"):
            create_academic_year(
                world_a["school"],
                label="2025-26",
                start_date="2025-06-01",
                end_date="2026-04-30",
                is_current=False,
            )


@pytest.mark.django_db
def test_create_academic_year_makes_current_clears_old(world_a):
    assert world_a["year"].is_current is True

    with use_school(world_a["school"]):
        new_year = create_academic_year(
            world_a["school"],
            label="2026-27",
            start_date="2026-06-01",
            end_date="2027-04-30",
            is_current=True,
        )

    world_a["year"].refresh_from_db()
    assert world_a["year"].is_current is False
    assert new_year.is_current is True


# ---------------------------------------------------------------------------
# update_academic_year
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_update_academic_year_make_current(world_a):
    new_year = AcademicYearFactory(
        school=world_a["school"], label="2026-27", is_current=False
    )
    update_academic_year(world_a["school"], new_year.id, is_current=True)

    world_a["year"].refresh_from_db()
    new_year.refresh_from_db()
    assert world_a["year"].is_current is False
    assert new_year.is_current is True
    # school.current_academic_year also updated
    world_a["school"].refresh_from_db()
    assert world_a["school"].current_academic_year_id == new_year.id


@pytest.mark.django_db
def test_update_academic_year_remove_current(world_a):
    update_academic_year(world_a["school"], world_a["year"].id, is_current=False)
    world_a["year"].refresh_from_db()
    assert world_a["year"].is_current is False


@pytest.mark.django_db
def test_update_academic_year_not_found_raises(world_a):
    from apps.core.exceptions import NotFound
    with pytest.raises(NotFound):
        update_academic_year(world_a["school"], 99999, label="X")


@pytest.mark.django_db
def test_update_academic_year_updates_label(world_a):
    update_academic_year(world_a["school"], world_a["year"].id, label="2025-26 Updated")
    world_a["year"].refresh_from_db()
    assert world_a["year"].label == "2025-26 Updated"
