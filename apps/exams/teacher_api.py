"""Teacher tests & scores endpoints — mounted on teacher_api."""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Query, Router

from apps.accounts.teacher_auth import get_teacher, teacher_jwt_auth
from apps.exams import question_bank_services, teacher_services
from apps.exams.teacher_schemas import (
    BankFacetsOut,
    BankQuestionIn,
    BankQuestionListOut,
    BankQuestionOut,
    CreateTestIn,
    MarksRosterItemOut,
    MessageOut,
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


@router.delete("/tests/{test_id}", response=MessageOut)
def delete_test(request: HttpRequest, test_id: int) -> dict:
    return teacher_services.delete_test(teacher=get_teacher(request), test_id=test_id)


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
# Question bank
# ---------------------------------------------------------------------------


@router.get("/question-bank/facets", response=BankFacetsOut)
def question_bank_facets(
    request: HttpRequest,
    subject: str = Query(default=None),  # type: ignore[assignment]
) -> dict:
    return question_bank_services.facets(
        teacher=get_teacher(request), subject=subject
    )


@router.get("/question-bank", response=BankQuestionListOut)
def list_bank_questions(
    request: HttpRequest,
    subject: str = Query(default=None),  # type: ignore[assignment]
    chapter: str = Query(default=None),  # type: ignore[assignment]
    topic: str = Query(default=None),  # type: ignore[assignment]
    difficulty: str = Query(default=None),  # type: ignore[assignment]
    q: str = Query(default=None),  # type: ignore[assignment]
    scope: str = Query(default="all"),
    limit: int = Query(default=30),
    offset: int = Query(default=0),
) -> dict:
    return question_bank_services.list_questions(
        teacher=get_teacher(request),
        subject=subject,
        chapter=chapter,
        topic=topic,
        difficulty=difficulty,
        q=q,
        scope=scope,
        limit=limit,
        offset=offset,
    )


@router.post("/question-bank", response=BankQuestionOut)
def create_bank_question(request: HttpRequest, payload: BankQuestionIn) -> dict:
    return question_bank_services.create_question(
        teacher=get_teacher(request), **payload.model_dump(by_alias=False)
    )


@router.patch("/question-bank/{question_id}", response=BankQuestionOut)
def update_bank_question(
    request: HttpRequest, question_id: int, payload: BankQuestionIn
) -> dict:
    return question_bank_services.update_question(
        teacher=get_teacher(request),
        question_id=question_id,
        **payload.model_dump(by_alias=False),
    )


@router.delete("/question-bank/{question_id}", response=MessageOut)
def delete_bank_question(request: HttpRequest, question_id: int) -> dict:
    return question_bank_services.delete_question(
        teacher=get_teacher(request), question_id=question_id
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
