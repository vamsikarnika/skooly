"""Pydantic schemas for the teacher tests & scores endpoints."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.core.schemas import CamelSchema

# ---------------------------------------------------------------------------
# Test list / detail
# ---------------------------------------------------------------------------


class TestOut(CamelSchema):
    id: str
    title: str
    subject: str
    class_label: str
    class_id: str        # section pk as string — matches frontend "classId"
    date: str            # ISO-8601 date string
    duration_min: int
    questions: int
    max_marks: int
    status: str          # draft | scheduled | grading | published
    avg_score: int | None = None
    submissions: int | None = None
    total_students: int


class CreateTestIn(CamelSchema):
    section_id: int
    name: str
    test_type: str = "OTHER"
    test_date: date
    max_marks: int


# ---------------------------------------------------------------------------
# Marks roster
# ---------------------------------------------------------------------------


class MarksRosterItemOut(CamelSchema):
    student_id: str
    roll_no: int | None = None
    name: str
    marks_obtained: Decimal | None = None
    is_absent: bool


class SaveMarkRecordIn(CamelSchema):
    student_id: str
    marks_obtained: Decimal | None = None
    is_absent: bool = False


class SaveMarksIn(CamelSchema):
    publish: bool = False
    records: list[SaveMarkRecordIn]


class SaveMarksOut(CamelSchema):
    saved: int
    published: bool


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class ReportBandOut(CamelSchema):
    label: str
    range: str
    count: int


class ReportStudentOut(CamelSchema):
    student_id: str
    roll_no: int | None = None
    name: str
    marks: Decimal | None = None
    pct: int | None = None
    is_absent: bool


class TestReportOut(CamelSchema):
    test: TestOut
    students: list[ReportStudentOut]
    avg: int
    top_score: Decimal | None = None
    top_student: str | None = None
    passed: int
    pass_rate: int
    total: int
    bands: list[ReportBandOut]
