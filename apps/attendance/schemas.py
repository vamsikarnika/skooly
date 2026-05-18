"""Pydantic schemas for the attendance read endpoints."""

from __future__ import annotations

from datetime import date, datetime

from apps.core.schemas import CamelSchema


class AttendanceSummary(CamelSchema):
    present: int = 0
    absent: int = 0
    late: int = 0
    half_day: int = 0
    not_marked: int = 0


class StudentHistorySummary(CamelSchema):
    present: int = 0
    absent: int = 0
    late: int = 0
    half_day: int = 0


class AttendanceMarkOut(CamelSchema):
    student_id: int
    student_name: str
    admission_number: str
    roll_number: str
    status: str | None  # null = not marked yet
    notes: str = ""
    marked_at: datetime | None = None
    marked_by_name: str | None = None


class SectionAttendanceOut(CamelSchema):
    section_id: int
    section_name: str
    class_name: str
    date: date
    marks: list[AttendanceMarkOut]
    summary: AttendanceSummary


class StudentAttendanceDayOut(CamelSchema):
    date: date
    status: str
    notes: str = ""
    marked_at: datetime | None = None


class StudentAttendanceHistoryOut(CamelSchema):
    student_id: int
    student_name: str
    from_date: date
    to_date: date
    days: list[StudentAttendanceDayOut]
    summary: StudentHistorySummary
    attendance_pct: float  # 0-100, half_day counts as 0.5


class StudentSummaryRowOut(CamelSchema):
    student_id: int
    student_name: str
    admission_number: str
    roll_number: str
    present: int
    absent: int
    late: int
    half_day: int
    total_marked: int
    attendance_pct: float


class SectionSummaryOut(CamelSchema):
    section_id: int
    section_name: str
    class_name: str
    from_date: date
    to_date: date
    students: list[StudentSummaryRowOut]
    school_days: int  # number of distinct dates with any attendance recorded in range


class SectionDailyRollupOut(CamelSchema):
    """One row per section, returned in bulk by /attendance/sections so the
    dashboard avoids an N+1 of per-section queries."""

    section_id: int
    section_name: str
    class_id: int
    class_name: str
    display_order: int
    class_teacher_id: int | None
    class_teacher_name: str | None
    active_student_count: int
    summary: AttendanceSummary


class SectionsDailyRollupOut(CamelSchema):
    date: date
    sections: list[SectionDailyRollupOut]
    totals: AttendanceSummary
    marked_section_count: int
    total_section_count: int
