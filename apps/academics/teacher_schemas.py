"""Schemas for the teacher app's classes & roster endpoints."""

from __future__ import annotations

from apps.core.schemas import CamelSchema


class TeacherClassOut(CamelSchema):
    id: str
    name: str
    section: str
    subject: str
    schedule: str = ""  # today's period time range; empty when no timetable row exists
    enrollment: int
    attendance_marked: bool
    attendance_time: str | None = None
    # True for the class where this teacher is expected to take attendance today.
    # Currently: the first class by display_order. Schools can override this later
    # (e.g. homeroom, configurable per-section flag) without frontend changes.
    is_attendance_class: bool = False


class ClassStudentOut(CamelSchema):
    id: str
    roll_no: int | None = None
    name: str
    gender: str
    parent_phone: str = ""


class TeacherPeriodOut(CamelSchema):
    period: int
    start_time: str  # "HH:MM"
    end_time: str  # "HH:MM"
    subject: str
    section_id: str
    section_label: str  # e.g. "Class 8 - A" — a teacher works across sections


class TeacherTimetableDayOut(CamelSchema):
    day: str  # "Mon" | "Tue" | "Wed" | "Thu" | "Fri" | "Sat"
    periods: list[TeacherPeriodOut]
