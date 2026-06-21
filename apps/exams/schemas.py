"""Pydantic schemas for the read-side tests endpoints."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from apps.core.schemas import CamelSchema, Paginated


class ExamNameOut(CamelSchema):
    id: int
    label: str
    is_series: bool
    display_order: int


class ExamNameCreateRequest(CamelSchema):
    label: str
    is_series: bool = False


class ExamNameUpdateRequest(CamelSchema):
    label: str | None = None
    is_series: bool | None = None
    display_order: int | None = None


class TestStats(CamelSchema):
    """Per-test summary. Absents are excluded from average/max/min."""

    student_count: int
    scored_count: int
    absent_count: int
    average: float | None  # null when nobody scored
    max_marks_scored: Decimal | None
    min_marks_scored: Decimal | None


class TestSummaryOut(CamelSchema):
    """List-view row — lightweight, no per-student scores."""

    id: int
    name: str
    test_type: str
    test_date: date
    max_marks: int
    section_id: int
    section_name: str
    class_id: int
    class_name: str
    subject_id: int
    subject_name: str
    created_by_name: str | None
    published_at: datetime
    stats: TestStats


class TestListOut(Paginated[TestSummaryOut]):
    pass


class ScoreRowOut(CamelSchema):
    student_id: int
    student_name: str
    admission_number: str
    roll_number: str
    marks: Decimal | None
    is_absent: bool


class TestDetailOut(CamelSchema):
    id: int
    name: str
    test_type: str
    test_date: date
    max_marks: int
    section_id: int
    section_name: str
    class_id: int
    class_name: str
    subject_id: int
    subject_name: str
    created_by_name: str | None
    published_at: datetime
    stats: TestStats
    scores: list[ScoreRowOut]


class StudentScoreOut(CamelSchema):
    test_id: int
    test_name: str
    test_type: str
    test_date: date
    subject_id: int
    subject_name: str
    max_marks: int
    marks: Decimal | None
    is_absent: bool
    percent: float | None  # null when absent or no marks recorded


class SubjectScoresOut(CamelSchema):
    subject_id: int
    subject_name: str
    tests: list[StudentScoreOut]
    average_percent: float | None


class StudentScoresHistoryOut(CamelSchema):
    student_id: int
    student_name: str
    from_date: date
    to_date: date
    by_subject: list[SubjectScoresOut]


# ----- Admin report cards ----------------------------------------------------


class ReportTermOut(CamelSchema):
    term: str
    card_count: int
    pdf_published_count: int


class AdminReportSubjectOut(CamelSchema):
    name: str
    max_marks: int
    marks: int | None = None
    grade: str


class AdminReportCardOut(CamelSchema):
    card_id: int
    student_id: str
    roll_no: int | None = None
    name: str
    subjects: list[AdminReportSubjectOut]
    overall_pct: int
    overall_grade: str
    rank: int | None = None
    total_students: int
    attendance_pct: int
    teacher_remark: str
    principal_remark: str
    pdf_url: str | None = None
    pdf_published: bool


class GenerateRemarkIn(CamelSchema):
    student_id: str
    principal_remark: str = ""


class GenerateReportCardsIn(CamelSchema):
    term: str
    remarks: list[GenerateRemarkIn] = []


class PublishReportCardsIn(CamelSchema):
    term: str


class GenerateReportCardsOut(CamelSchema):
    generated: int


class PublishReportCardsOut(CamelSchema):
    published: int
