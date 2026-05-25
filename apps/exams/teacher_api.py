"""Teacher tests & scores endpoints — mounted on teacher_api."""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Query, Router

from apps.accounts.teacher_auth import get_teacher, teacher_jwt_auth
from apps.exams import teacher_services
from apps.exams.teacher_schemas import (
    CreateTestIn,
    MarksRosterItemOut,
    SaveMarksIn,
    SaveMarksOut,
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
