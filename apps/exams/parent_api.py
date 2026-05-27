"""Parent app marks/test-results endpoints — mounted on parent_api.

Read-only published offline-test results for a single linked child, with the
class average / high / rank computed on the fly from the section's scores.
Online tests are served by a separate endpoint (Phase 2).
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from ninja import Router

from apps.accounts.parent_auth import get_parent_child, parent_jwt_auth
from apps.core.exceptions import NotFound
from apps.core.schemas import CamelSchema
from apps.exams.models import Test, TestMode, TestScore

router = Router(tags=["parent-marks"], auth=parent_jwt_auth, by_alias=True)


class TestResultOut(CamelSchema):
    id: int
    title: str
    subject: str
    date: str
    marks: int | None = None
    max_marks: int
    class_avg: int
    class_high: int
    rank: int | None = None
    total_students: int


class TestListOut(CamelSchema):
    tests: list[TestResultOut]


def _current_section(student: Any, school: Any) -> Any:
    year_id = school.current_academic_year_id if school else None
    qs = student.enrollments.filter(status="active").select_related("section")
    enroll = None
    if year_id is not None:
        enroll = qs.filter(academic_year_id=year_id).first()
    enroll = enroll or qs.first()
    return enroll.section if enroll else None


def _result(test: Test, student: Any) -> dict:
    scores = list(TestScore.objects.filter(test=test))
    marks_list = [
        float(s.marks_obtained)
        for s in scores
        if not s.is_absent and s.marks_obtained is not None
    ]
    class_avg = round(sum(marks_list) / len(marks_list)) if marks_list else 0
    class_high = round(max(marks_list)) if marks_list else 0

    mine = next((s for s in scores if s.student_id == student.id), None)
    my_marks = (
        float(mine.marks_obtained)
        if (mine and not mine.is_absent and mine.marks_obtained is not None)
        else None
    )
    rank = (sum(1 for m in marks_list if m > my_marks) + 1) if my_marks is not None else None

    return {
        "id": test.id,
        "title": test.name,
        "subject": test.subject.name,
        "date": test.test_date.isoformat(),
        "marks": round(my_marks) if my_marks is not None else None,
        "max_marks": test.max_marks or 0,
        "class_avg": class_avg,
        "class_high": class_high,
        "rank": rank,
        "total_students": len(scores),
    }


@router.get("/children/{child_id}/tests", response=TestListOut)
def list_tests(request: HttpRequest, child_id: int) -> dict:
    student = get_parent_child(request, child_id)
    school = request.auth.school  # type: ignore[attr-defined]
    section = _current_section(student, school)
    if section is None:
        return {"tests": []}
    tests = (
        Test.objects.filter(
            section=section, mode=TestMode.OFFLINE, published_at__isnull=False
        )
        .select_related("subject")
        .order_by("-test_date", "-id")
    )
    return {"tests": [_result(t, student) for t in tests]}


@router.get("/children/{child_id}/tests/{test_id}", response=TestResultOut)
def get_test(request: HttpRequest, child_id: int, test_id: int) -> dict:
    student = get_parent_child(request, child_id)
    school = request.auth.school  # type: ignore[attr-defined]
    section = _current_section(student, school)
    test = (
        Test.objects.filter(
            id=test_id,
            section=section,
            mode=TestMode.OFFLINE,
            published_at__isnull=False,
        )
        .select_related("subject")
        .first()
    )
    if test is None:
        raise NotFound("No such test for this child.")
    return _result(test, student)
