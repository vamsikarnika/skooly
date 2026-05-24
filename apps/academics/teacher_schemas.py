"""Schemas for the teacher app's classes & roster endpoints."""

from __future__ import annotations

from apps.core.schemas import CamelSchema


class TeacherClassOut(CamelSchema):
    id: str
    name: str
    section: str
    subject: str
    schedule: str = ""  # stubbed until a Timetable model exists
    enrollment: int
    attendance_marked: bool
    attendance_time: str | None = None


class ClassStudentOut(CamelSchema):
    id: str
    roll_no: int | None = None
    name: str
    gender: str
    parent_phone: str = ""
