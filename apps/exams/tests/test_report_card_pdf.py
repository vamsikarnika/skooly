"""The report-card HTML template renders with the expected content.

Exercises _render_html only (pure string) — WeasyPrint's write_pdf needs
system libs and is covered implicitly when the API runs in the container.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.exams.models import ReportCard
from apps.exams.report_card_pdf import _render_html
from apps.people.tests.factories import StudentFactory


@pytest.mark.django_db
def test_render_html_contains_key_fields(world_a):
    school = world_a["school"]
    school.name = "Vidya Bharati High School"
    school.address = "Tirupati, AP"
    school.save(update_fields=["name", "address"])
    student = StudentFactory(school=school, first_name="Aarav", last_name="Reddy")
    card = ReportCard.objects.create(
        school=school,
        student=student,
        academic_year=world_a["year"],
        term="Term 1",
        published_at=timezone.now(),
        data_snapshot={
            "term": "Term 1",
            "academicYear": world_a["year"].label,
            "issueDate": "2026-02-28",
            "subjects": [{"name": "Mathematics", "maxMarks": 100, "marks": 88, "grade": "A1"}],
            "attendancePct": 95,
            "teacherRemark": "Excellent term.",
            "principalRemark": "Keep it up.",
            "overallGrade": "A1",
            "overallPct": 88,
            "rank": 2,
            "totalStudents": 30,
        },
    )
    html = _render_html(card, class_name="Class 6", section_name="A")
    assert "Vidya Bharati High School" in html
    assert "Aarav" in html
    assert "REPORT CARD" in html
    assert "Term 1" in html
    assert "Mathematics" in html
    assert "Keep it up." in html  # principal remark
    assert "A1" in html  # overall grade badge
