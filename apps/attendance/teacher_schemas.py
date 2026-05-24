"""Schemas for the teacher attendance endpoints."""

from __future__ import annotations

from datetime import date

from apps.core.schemas import CamelSchema


class AttendanceSummaryOut(CamelSchema):
    section_id: str
    class_name: str
    section: str
    subject: str
    total: int
    present: int
    absent: int
    rate: int
    marked: bool


class AttendanceRecordOut(CamelSchema):
    student_id: str
    roll_no: int | None = None
    name: str
    status: str  # present | absent | late | half_day


class AttendanceRecordIn(CamelSchema):
    student_id: str
    status: str


class BulkAttendanceIn(CamelSchema):
    date: date
    records: list[AttendanceRecordIn]


class BulkAttendanceSavedOut(CamelSchema):
    saved: int
