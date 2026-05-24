"""Schemas for the teacher app's single-student detail view."""

from __future__ import annotations

from apps.core.schemas import CamelSchema


class StudentAttendanceRollup(CamelSchema):
    total_days: int
    present: int
    absent: int
    rate: int


class StudentTestScoreOut(CamelSchema):
    test_id: str
    test_title: str
    date: str
    marks: float | None = None
    max_marks: int
    percentage: int | None = None


class TeacherStudentDetailOut(CamelSchema):
    id: str
    roll_no: int | None = None
    name: str
    gender: str
    parent_phone: str = ""
    class_id: str
    class_name: str
    section: str
    attendance: StudentAttendanceRollup
    test_scores: list[StudentTestScoreOut]
