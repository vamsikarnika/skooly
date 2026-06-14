"""HTTP tests for the admin report-card endpoints (read / generate / publish).

Scores are seeded via the shared publish service (as the teacher app would).
PDF rendering is patched so these tests don't depend on WeasyPrint's system
libs — the renderer itself is exercised by test_report_card_pdf.py.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.utils import timezone

from apps.academics.models import StudentEnrollment
from apps.exams import admin_report_services
from apps.exams.models import ReportCard
from apps.people.tests.factories import StudentFactory


def _seed_published(world: dict, section, term: str, n: int) -> list[int]:
    """Enroll n students and create published teacher reports (scores) for the
    term — created directly since the seed runs outside a tenant-scoped request."""
    school, year = world["school"], world["year"]
    school.current_academic_year = year
    school.save(update_fields=["current_academic_year"])
    ids = []
    for i in range(n):
        student = StudentFactory(school=school)
        StudentEnrollment.objects.create(
            school=school, student=student, section=section, academic_year=year,
            roll_number=str(i + 1), enrollment_date=student.admission_date, status="active",
        )
        ReportCard.objects.create(
            school=school, student=student, academic_year=year, term=term,
            published_at=timezone.now(),
            data_snapshot={
                "term": term,
                "academicYear": year.label,
                "issueDate": "2026-02-28",
                "subjects": [
                    {"name": "Math", "maxMarks": 100, "marks": 70 + i, "grade": "A2"},
                    {"name": "English", "maxMarks": 100, "marks": 60 + i, "grade": "B1"},
                ],
                "attendancePct": 90,
                "teacherRemark": "Steady.",
                "principalRemark": None,
                "overallGrade": "A2",
                "overallPct": 75,
                "rank": i + 1,
                "totalStudents": n,
            },
        )
        ids.append(student.id)
    return ids


@pytest.mark.django_db
def test_terms_and_cards_read(client: Client, admin_token_a, world_a):
    section = world_a["section_a"]
    _seed_published(world_a, section, "Term 1", 3)
    auth = {"HTTP_AUTHORIZATION": f"Bearer {admin_token_a}"}

    res = client.get(f"/api/v1/report-cards/{section.id}/terms", **auth)
    assert res.status_code == 200, res.content
    terms = res.json()
    assert terms == [{"term": "Term 1", "cardCount": 3, "pdfPublishedCount": 0}]

    res = client.get(f"/api/v1/report-cards/{section.id}/cards?term=Term%201", **auth)
    assert res.status_code == 200, res.content
    cards = res.json()
    assert len(cards) == 3
    first = cards[0]
    assert first["subjects"][0]["name"] == "Math"
    assert first["pdfUrl"] is None
    assert first["pdfPublished"] is False


@pytest.mark.django_db
def test_generate_then_publish(client: Client, admin_token_a, world_a, monkeypatch):
    section = world_a["section_a"]
    ids = _seed_published(world_a, section, "Term 1", 2)
    auth = {"HTTP_AUTHORIZATION": f"Bearer {admin_token_a}"}

    monkeypatch.setattr(
        admin_report_services,
        "generate_and_store_report_card",
        lambda card, **kw: f"http://media.test/report-cards/{card.id}.pdf",
    )

    # Generate with a principal remark for the first student.
    res = client.post(
        f"/api/v1/report-cards/{section.id}/generate",
        data={"term": "Term 1", "remarks": [{"studentId": str(ids[0]), "principalRemark": "Excellent"}]},
        content_type="application/json",
        **auth,
    )
    assert res.status_code == 200, res.content
    assert res.json() == {"generated": 2}

    res = client.get(f"/api/v1/report-cards/{section.id}/cards?term=Term%201", **auth)
    cards = {c["studentId"]: c for c in res.json()}
    assert cards[str(ids[0])]["pdfUrl"].endswith(".pdf")
    assert cards[str(ids[0])]["principalRemark"] == "Excellent"
    assert cards[str(ids[0])]["pdfPublished"] is False  # not yet published

    # Publish the PDFs.
    res = client.post(
        f"/api/v1/report-cards/{section.id}/publish",
        data={"term": "Term 1"},
        content_type="application/json",
        **auth,
    )
    assert res.status_code == 200, res.content
    assert res.json() == {"published": 2}

    res = client.get(f"/api/v1/report-cards/{section.id}/cards?term=Term%201", **auth)
    assert all(c["pdfPublished"] for c in res.json())


@pytest.mark.django_db
def test_teacher_cannot_generate_or_publish(client: Client, teacher_token_a, world_a):
    section = world_a["section_a"]
    auth = {"HTTP_AUTHORIZATION": f"Bearer {teacher_token_a}"}
    for path in ("generate", "publish"):
        res = client.post(
            f"/api/v1/report-cards/{section.id}/{path}",
            data={"term": "Term 1"},
            content_type="application/json",
            **auth,
        )
        assert res.status_code == 403, (path, res.content)
