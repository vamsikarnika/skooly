"""School + academic year business logic."""

from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.core.exceptions import Conflict, NotFound
from apps.schools.models import AcademicYear, Board, School


def update_school(school: School, *, fields: dict[str, Any]) -> School:
    if "board" in fields and fields["board"] is not None and fields["board"] not in Board.values:
        raise Conflict("Invalid board.")

    allowed = {"name", "board", "address", "logo_url", "whatsapp_number", "primary_color"}
    changed = []
    for field, value in fields.items():
        if value is None or field not in allowed:
            continue
        setattr(school, field, value)
        changed.append(field)
    if changed:
        school.save(update_fields=[*changed, "updated_at"])
    return school


@transaction.atomic
def create_academic_year(
    school: School,
    *,
    label: str,
    start_date: Any,
    end_date: Any,
    is_current: bool,
) -> AcademicYear:
    if AcademicYear.objects.filter(school=school, label=label).exists():
        raise Conflict(f"Academic year '{label}' already exists for this school.")
    if is_current:
        AcademicYear.objects.filter(school=school, is_current=True).update(is_current=False)
    year = AcademicYear.objects.create(
        school=school,
        label=label,
        start_date=start_date,
        end_date=end_date,
        is_current=is_current,
    )
    if is_current:
        school.current_academic_year = year
        school.save(update_fields=["current_academic_year"])
    return year


@transaction.atomic
def update_academic_year(school: School, year_id: int, **fields: Any) -> AcademicYear:
    year = AcademicYear.objects.filter(school=school, id=year_id).first()
    if year is None:
        raise NotFound("Academic year not found.")

    make_current = fields.pop("is_current", None)
    changed = []
    for f, v in fields.items():
        if v is None:
            continue
        setattr(year, f, v)
        changed.append(f)
    if changed:
        year.save(update_fields=[*changed, "updated_at"])

    if make_current is True and not year.is_current:
        AcademicYear.objects.filter(school=school, is_current=True).update(is_current=False)
        year.is_current = True
        year.save(update_fields=["is_current"])
        school.current_academic_year = year
        school.save(update_fields=["current_academic_year"])
    elif make_current is False and year.is_current:
        year.is_current = False
        year.save(update_fields=["is_current"])
    return year


def list_academic_years(school: School) -> list[AcademicYear]:
    return list(AcademicYear.objects.filter(school=school).order_by("-start_date"))
