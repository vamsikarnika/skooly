"""Write-side schemas for academics."""

from __future__ import annotations

from pydantic import Field

from apps.core.schemas import CamelSchema


class ClassCreateRequest(CamelSchema):
    academic_year_id: int
    name: str = Field(min_length=1, max_length=40)
    display_order: int = 0


class ClassUpdateRequest(CamelSchema):
    name: str | None = None
    display_order: int | None = None


class SectionCreateRequest(CamelSchema):
    class_id: int
    name: str = Field(min_length=1, max_length=10)
    class_teacher_id: int | None = None
    room_number: str = ""
    capacity: int = 40


class SectionUpdateRequest(CamelSchema):
    name: str | None = None
    class_teacher_id: int | None = None
    room_number: str | None = None
    capacity: int | None = None


class SubjectCreateRequest(CamelSchema):
    name: str = Field(min_length=1, max_length=80)
    code: str = ""


class SubjectUpdateRequest(CamelSchema):
    name: str | None = None
    code: str | None = None


class ClassSubjectRequest(CamelSchema):
    subject_id: int


class TeacherAssignmentRequest(CamelSchema):
    teacher_id: int
    subject_id: int
    section_id: int


class TimetableSlotIn(CamelSchema):
    period_number: int
    start_time: str  # "HH:MM"
    end_time: str  # "HH:MM"


class TimetableEntryIn(CamelSchema):
    day_of_week: int  # 1=Mon … 6=Sat
    period_number: int
    subject_id: int


class SectionTimetableIn(CamelSchema):
    slots: list[TimetableSlotIn] = []
    entries: list[TimetableEntryIn] = []
