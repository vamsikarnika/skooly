"""Pydantic schemas for the teacher tests & scores endpoints."""

from __future__ import annotations

from datetime import date, datetime
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
    class_id: str           # section pk as string — matches frontend "classId"
    date: str               # ISO-8601 date string
    duration_min: int
    questions: int
    max_marks: int
    status: str             # draft | scheduled | live | grading | published
    mode: str               # offline | online
    available_from: str | None = None   # ISO-8601 datetime, online only
    available_until: str | None = None  # ISO-8601 datetime, online only
    avg_score: int | None = None
    submissions: int | None = None
    total_students: int


class CreateTestIn(CamelSchema):
    section_id: int
    name: str
    test_type: str = "OTHER"
    # Offline: test_date required; max_marks required
    test_date: date
    max_marks: int | None = None
    # Online: mode + scheduling
    mode: str = "offline"
    available_from: datetime | None = None
    available_until: datetime | None = None
    duration_min: int = 0


# ---------------------------------------------------------------------------
# Question builder (online tests)
# ---------------------------------------------------------------------------


class MCQOptionIn(CamelSchema):
    text: str
    is_correct: bool
    display_order: int


class MCQOptionOut(CamelSchema):
    id: str
    text: str
    is_correct: bool
    display_order: int


class QuestionIn(CamelSchema):
    question_type: str      # mcq | short_answer
    text: str
    marks: int
    display_order: int
    difficulty: str | None = None
    topic: str = ""
    # MCQ — exactly 4 options required when question_type == "mcq"
    options: list[MCQOptionIn] | None = None
    # Short answer
    correct_answer: str = ""


class QuestionOut(CamelSchema):
    id: str
    question_type: str
    text: str
    marks: int
    display_order: int
    difficulty: str | None = None
    topic: str
    options: list[MCQOptionOut]
    correct_answer: str


class SaveQuestionsIn(CamelSchema):
    publish: bool = False
    questions: list[QuestionIn]


class SaveQuestionsOut(CamelSchema):
    saved: int
    total_marks: int
    published: bool


# ---------------------------------------------------------------------------
# Marks roster (offline tests)
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
