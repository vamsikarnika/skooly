"""Read-only test endpoints. POST/score-entry/publish lives in the
teacher-app build, not in Module 4."""

from __future__ import annotations

from datetime import date as date_type
from datetime import timedelta

from django.http import HttpRequest
from ninja import Query, Router

from apps.academics.models import Section
from apps.accounts.auth import jwt_auth
from apps.accounts.models import Role
from apps.core.exceptions import Forbidden, NotFound
from apps.core.helpers import get_in_tenant
from apps.core.pagination import paginate
from apps.core.schemas import ActionResponse
from apps.exams import (
    admin_report_services,
    exam_name_services,
    radar_services,
    services,
    teacher_services,
)
from apps.exams.models import Test
from apps.exams.schemas import (
    AdminReportCardOut,
    ExamNameCreateRequest,
    ExamNameOut,
    ExamNameUpdateRequest,
    GenerateReportCardsIn,
    GenerateReportCardsOut,
    PublishReportCardsIn,
    PublishReportCardsOut,
    ReportTermOut,
    StrengthProfileOut,
    StudentScoresHistoryOut,
    TestDetailOut,
    TestListOut,
    TestSummaryOut,
)
from apps.exams.teacher_schemas import ReportCardSectionOut
from apps.people.models import Student

router = Router(tags=["exams"], auth=jwt_auth, by_alias=True)


def _school(request: HttpRequest):  # type: ignore[no-untyped-def]
    school = request.auth.school  # type: ignore[attr-defined]
    if school is None:
        raise NotFound("Current user has no school.")
    return school


def _require_admin(request: HttpRequest) -> None:
    if request.auth.role != Role.ADMIN:  # type: ignore[attr-defined]
        raise Forbidden("Admin role required.")


@router.get("/tests", response=TestListOut)
def list_tests(
    request: HttpRequest,
    section_id: int | None = Query(default=None, alias="sectionId"),
    class_id: int | None = Query(default=None, alias="classId"),
    subject_id: int | None = Query(default=None, alias="subjectId"),
    test_type: str | None = Query(default=None, alias="testType"),
    from_date: date_type | None = Query(default=None, alias="from"),
    to_date: date_type | None = Query(default=None, alias="to"),
    page: int = Query(default=1),
    page_size: int = Query(default=50, alias="pageSize"),
) -> dict:
    qs = services.list_published_tests(
        school=_school(request),
        section_id=section_id,
        class_id=class_id,
        subject_id=subject_id,
        test_type=test_type,
        from_date=from_date,
        to_date=to_date,
    )
    payload = paginate(qs, page=page, page_size=page_size)
    payload["items"] = [services.test_summary_dict(t) for t in payload["items"]]
    return payload


@router.get("/tests/{test_id}", response=TestDetailOut)
def get_test(request: HttpRequest, test_id: int) -> dict:
    school = _school(request)
    test = (
        Test.objects.filter(school=school, id=test_id, published_at__isnull=False)
        .select_related("section__class_obj", "subject", "created_by")
        .prefetch_related("scores")
        .first()
    )
    if test is None:
        raise NotFound("Test not found.")
    return services.test_detail_dict(test)


@router.get("/sections/{section_id}/tests", response=list[TestSummaryOut])
def list_section_tests(
    request: HttpRequest,
    section_id: int,
    from_date: date_type | None = Query(default=None, alias="from"),
    to_date: date_type | None = Query(default=None, alias="to"),
) -> list[dict]:
    school = _school(request)
    get_in_tenant(Section, school, pk=section_id)
    qs = services.list_published_tests(
        school=school, section_id=section_id, from_date=from_date, to_date=to_date
    )
    return [services.test_summary_dict(t) for t in qs]


@router.get("/students/{student_id}/scores", response=StudentScoresHistoryOut)
def student_scores(
    request: HttpRequest,
    student_id: int,
    from_date: date_type | None = Query(default=None, alias="from"),
    to_date: date_type | None = Query(default=None, alias="to"),
) -> dict:
    school = _school(request)
    student = get_in_tenant(Student, school, pk=student_id)
    fd = from_date or (date_type.today() - timedelta(days=365))
    td = to_date or date_type.today()
    return services.student_scores_history(
        school=school, student=student, from_date=fd, to_date=td
    )


@router.get("/students/{student_id}/strengths", response=StrengthProfileOut)
def student_strengths(request: HttpRequest, student_id: int) -> dict:
    """Per-subject percentile radar — relative grading across the grade's
    common tests. Admin/internal read; any student in the school."""
    school = _school(request)
    student = get_in_tenant(Student, school, pk=student_id)
    return radar_services.build_strength_profile(
        school=school, student=student, academic_year_id=school.current_academic_year_id
    )


# ---------------------------------------------------------------------------
# Exam names — school-defined, reusable test names managed by the admin.
# Teachers pick from these when creating offline tests (see teacher_api
# /exam-names). Reads are open to any authed school user; writes are admin-only.
# ---------------------------------------------------------------------------


@router.get("/exam-names", response=list[ExamNameOut])
def list_exam_names(request: HttpRequest) -> list[ExamNameOut]:
    school = _school(request)
    return [ExamNameOut.from_orm(e) for e in exam_name_services.list_exam_names(school)]


@router.post("/exam-names", response=ExamNameOut)
def create_exam_name(request: HttpRequest, payload: ExamNameCreateRequest) -> ExamNameOut:
    _require_admin(request)
    school = _school(request)
    exam_name = exam_name_services.create_exam_name(
        school, label=payload.label, is_series=payload.is_series
    )
    return ExamNameOut.from_orm(exam_name)


@router.patch("/exam-names/{exam_name_id}", response=ExamNameOut)
def update_exam_name(
    request: HttpRequest, exam_name_id: int, payload: ExamNameUpdateRequest
) -> ExamNameOut:
    _require_admin(request)
    school = _school(request)
    exam_name = exam_name_services.update_exam_name(
        school, exam_name_id, **payload.model_dump(by_alias=False, exclude_unset=True)
    )
    return ExamNameOut.from_orm(exam_name)


@router.delete("/exam-names/{exam_name_id}", response=ActionResponse)
def delete_exam_name(request: HttpRequest, exam_name_id: int) -> ActionResponse:
    _require_admin(request)
    school = _school(request)
    exam_name_services.delete_exam_name(school, exam_name_id)
    return ActionResponse(success=True)


# ---------------------------------------------------------------------------
# Report cards (admin). Scores come from the teacher's publish; the admin reads
# them across every section, renders a branded PDF (optionally with a per-
# student principal remark), and publishes that PDF to parents. The PDF is
# additive — parents already see the raw scores once the teacher publishes.
# ---------------------------------------------------------------------------


@router.get("/report-cards/sections", response=list[ReportCardSectionOut])
def report_card_sections(request: HttpRequest) -> list[dict]:
    school = _school(request)
    year_id = school.current_academic_year_id
    sections = (
        Section.objects.filter(school=school, class_obj__academic_year_id=year_id)
        .select_related("class_obj")
        .order_by("class_obj__display_order", "name")
    )
    return [teacher_services.section_report_summary(s, year_id) for s in sections]


@router.get("/report-cards/{section_id}/terms", response=list[ReportTermOut])
def report_card_terms(request: HttpRequest, section_id: int) -> list[dict]:
    school = _school(request)
    section = get_in_tenant(Section, school, pk=section_id)
    return admin_report_services.list_terms(section)


@router.get("/report-cards/{section_id}/cards", response=list[AdminReportCardOut])
def report_card_cards(
    request: HttpRequest,
    section_id: int,
    term: str = Query(...),  # type: ignore[assignment]
) -> list[dict]:
    school = _school(request)
    section = get_in_tenant(Section, school, pk=section_id)
    return admin_report_services.cards_for_section(section, term)


@router.post("/report-cards/{section_id}/generate", response=GenerateReportCardsOut)
def generate_report_cards(
    request: HttpRequest, section_id: int, payload: GenerateReportCardsIn
) -> dict:
    _require_admin(request)
    school = _school(request)
    section = get_in_tenant(Section, school, pk=section_id)
    remarks = {r.student_id: r.principal_remark for r in payload.remarks}
    return admin_report_services.generate_pdfs(section, payload.term, remarks)


@router.post("/report-cards/{section_id}/publish", response=PublishReportCardsOut)
def publish_report_cards(
    request: HttpRequest, section_id: int, payload: PublishReportCardsIn
) -> dict:
    _require_admin(request)
    school = _school(request)
    section = get_in_tenant(Section, school, pk=section_id)
    return admin_report_services.publish_pdfs(section, payload.term)
