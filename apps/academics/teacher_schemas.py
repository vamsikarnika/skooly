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
