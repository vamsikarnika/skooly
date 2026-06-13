"""Teacher tests & scores endpoints — mounted on teacher_api."""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Query, Router

from apps.accounts.teacher_auth import get_teacher, teacher_jwt_auth
from apps.exams import teacher_services
from apps.exams.teacher_schemas import (
    CreateTestIn,
    MarksRosterItemOut,
    QuestionOut,
    ReportCardRosterOut,
    ReportCardSectionOut,
    ReportSummaryOut,
    SaveMarksIn,
    SaveMarksOut,
    SaveQuestionsIn,
    SaveQuestionsOut,
    SaveReportCardsIn,
    SaveReportCardsOut,
    TestOut,
    TestReportOut,
)

router = Router(tags=["teacher-tests"], auth=teacher_jwt_auth, by_alias=True)


@router.get("/tests", response=list[TestOut])
def list_tests(
    request: HttpRequest,
    status: str = Query(default=None),  # type: ignore[assignment]
) -> list[dict]:
    school = request.auth.school  # type: ignore[attr-defined]
    return teacher_services.list_tests(
        teacher=get_teacher(request),
        academic_year_id=school.current_academic_year_id if school else None,
        status_filter=status,
    )


@router.post("/tests", response=TestOut)
def create_test(request: HttpRequest, payload: CreateTestIn) -> dict:
    school = request.auth.school  # type: ignore[attr-defined]
    return teacher_services.create_test(
        teacher=get_teacher(request),
        academic_year_id=school.current_academic_year_id if school else None,
        **payload.model_dump(by_alias=False),
    )


@router.get("/tests/{test_id}", response=TestOut)
def get_test(request: HttpRequest, test_id: int) -> dict:
    school = request.auth.school  # type: ignore[attr-defined]
    return teacher_services.get_test(
        teacher=get_teacher(request),
        test_id=test_id,
        academic_year_id=school.current_academic_year_id if school else None,
    )


@router.get("/tests/{test_id}/marks", response=list[MarksRosterItemOut])
def get_marks(request: HttpRequest, test_id: int) -> list[dict]:
    school = request.auth.school  # type: ignore[attr-defined]
    return teacher_services.get_marks_roster(
        teacher=get_teacher(request),
        test_id=test_id,
        academic_year_id=school.current_academic_year_id if school else None,
    )


@router.post("/tests/{test_id}/marks", response=SaveMarksOut)
def save_marks(request: HttpRequest, test_id: int, payload: SaveMarksIn) -> dict:
    school = request.auth.school  # type: ignore[attr-defined]
    return teacher_services.save_marks(
        teacher=get_teacher(request),
        test_id=test_id,
        academic_year_id=school.current_academic_year_id if school else None,
        records=[r.model_dump(by_alias=False) for r in payload.records],
        publish=payload.publish,
    )


@router.get("/tests/{test_id}/report", response=TestReportOut)
def get_report(request: HttpRequest, test_id: int) -> dict:
    school = request.auth.school  # type: ignore[attr-defined]
    return teacher_services.get_report(
        teacher=get_teacher(request),
        test_id=test_id,
        academic_year_id=school.current_academic_year_id if school else None,
    )


@router.get("/tests/{test_id}/questions", response=list[QuestionOut])
def get_questions(request: HttpRequest, test_id: int) -> list[dict]:
    school = request.auth.school  # type: ignore[attr-defined]
    return teacher_services.get_questions(
        teacher=get_teacher(request),
        test_id=test_id,
        academic_year_id=school.current_academic_year_id if school else None,
    )


@router.post("/tests/{test_id}/questions", response=SaveQuestionsOut)
def save_questions(
    request: HttpRequest, test_id: int, payload: SaveQuestionsIn
) -> dict:
    school = request.auth.school  # type: ignore[attr-defined]
    return teacher_services.save_questions(
        teacher=get_teacher(request),
        test_id=test_id,
        academic_year_id=school.current_academic_year_id if school else None,
        questions=[q.model_dump(by_alias=False) for q in payload.questions],
        publish=payload.publish,
    )


# ---------------------------------------------------------------------------
# Report cards (class-teacher generate + publish)
# ---------------------------------------------------------------------------


@router.get("/report-cards/sections", response=list[ReportCardSectionOut])
def list_report_card_sections(request: HttpRequest) -> list[dict]:
    school = request.auth.school  # type: ignore[attr-defined]
    return teacher_services.list_report_card_sections(
        teacher=get_teacher(request),
        academic_year_id=school.current_academic_year_id if school else None,
    )


@router.get("/report-cards/{section_id}/reports", response=list[ReportSummaryOut])
def list_report_card_reports(request: HttpRequest, section_id: int) -> list[dict]:
    school = request.auth.school  # type: ignore[attr-defined]
    return teacher_services.list_report_card_reports(
        teacher=get_teacher(request),
        section_id=section_id,
        academic_year_id=school.current_academic_year_id if school else None,
    )


@router.get("/report-cards/{section_id}/roster", response=ReportCardRosterOut)
def report_card_roster(
    request: HttpRequest, section_id: int, name: str = Query(default="")  # type: ignore[assignment]
) -> dict:
    school = request.auth.school  # type: ignore[attr-defined]
    return teacher_services.report_card_roster(
        teacher=get_teacher(request),
        section_id=section_id,
        academic_year_id=school.current_academic_year_id if school else None,
        name=name,
    )


@router.post("/report-cards/{section_id}/publish", response=SaveReportCardsOut)
def save_report_cards(
    request: HttpRequest, section_id: int, payload: SaveReportCardsIn
) -> dict:
    school = request.auth.school  # type: ignore[attr-defined]
    return teacher_services.save_report_cards(
        teacher=get_teacher(request),
        section_id=section_id,
        academic_year_id=school.current_academic_year_id if school else None,
        name=payload.name,
        subjects=[s.model_dump(by_alias=False) for s in payload.subjects],
        publish=payload.publish,
        records=[r.model_dump(by_alias=False) for r in payload.records],
    )
