"""Schemas for academics (classes, sections, subjects)."""

from __future__ import annotations

from apps.core.schemas import CamelSchema


class SubjectOut(CamelSchema):
    id: int
    name: str
    code: str


class SectionOut(CamelSchema):
    id: int
    name: str
    class_id: int
    class_teacher_id: int | None = None
    class_teacher_name: str | None = None
    room_number: str
    capacity: int
    active_student_count: int = 0


class ClassOut(CamelSchema):
    id: int
    name: str
    academic_year_id: int
    display_order: int
    sections: list[SectionOut] = []
    student_count: int = 0
