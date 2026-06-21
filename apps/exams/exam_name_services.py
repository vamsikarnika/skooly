"""Admin CRUD for school-defined exam names.

Exam names are reusable test titles an admin sets up once (e.g. "Quarterly
Exam", or the "Weekly Test" series). Teachers pick from them when creating an
offline test. See apps/exams/api.py (admin) and teacher_api.py (read-only).
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import Max

from apps.core.exceptions import Conflict, NotFound
from apps.exams.models import ExamName
from apps.schools.models import School


def list_exam_names(school: School) -> list[ExamName]:
    return list(ExamName.objects.filter(school=school).order_by("display_order", "id"))


@transaction.atomic
def create_exam_name(school: School, *, label: str, is_series: bool) -> ExamName:
    label = label.strip()
    if not label:
        raise Conflict("Exam name cannot be empty.")
    if ExamName.objects.filter(school=school, label__iexact=label).exists():
        raise Conflict(f"Exam name '{label}' already exists.")
    # New names land at the bottom of the list.
    next_order = (
        ExamName.objects.filter(school=school).aggregate(m=Max("display_order"))["m"] or 0
    ) + 1
    return ExamName.objects.create(
        school=school, label=label, is_series=is_series, display_order=next_order
    )


@transaction.atomic
def update_exam_name(school: School, exam_name_id: int, **fields: Any) -> ExamName:
    exam_name = ExamName.objects.filter(school=school, id=exam_name_id).first()
    if exam_name is None:
        raise NotFound("Exam name not found.")

    changed = []
    if (label := fields.get("label")) is not None:
        label = label.strip()
        if not label:
            raise Conflict("Exam name cannot be empty.")
        if (
            ExamName.objects.filter(school=school, label__iexact=label)
            .exclude(id=exam_name_id)
            .exists()
        ):
            raise Conflict(f"Exam name '{label}' already exists.")
        exam_name.label = label
        changed.append("label")
    if (is_series := fields.get("is_series")) is not None:
        exam_name.is_series = is_series
        changed.append("is_series")
    if (display_order := fields.get("display_order")) is not None:
        exam_name.display_order = display_order
        changed.append("display_order")
    if changed:
        exam_name.save(update_fields=[*changed, "updated_at"])
    return exam_name


def delete_exam_name(school: School, exam_name_id: int) -> None:
    """Soft-delete so tests already linked via Test.exam_name keep the row."""
    exam_name = ExamName.objects.filter(school=school, id=exam_name_id).first()
    if exam_name is None:
        raise NotFound("Exam name not found.")
    exam_name.soft_delete()
