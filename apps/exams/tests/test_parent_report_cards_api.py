"""HTTP tests for the parent app report-card endpoints."""

from __future__ import annotations

from datetime import date

import pytest
from django.test import Client
from django.utils import timezone

from apps.academics.models import StudentEnrollment
from apps.accounts.models import Role, User
from apps.accounts.services import issue_tokens_for_user
from apps.exams.models import ReportCard, ReportCardTerm
from apps.people.models import Parent, ParentStudent
from apps.people.tests.factories import StudentFactory


def _auth(user: User) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_tokens_for_user(user)['access_token']}"}


def _parent_with_child(world: dict, phone: str = "+919876512345"):
    school, year, section = world["school"], world["year"], world["section_a"]
    student = StudentFactory(school=school, first_name="Aarav", last_name="Reddy")
    StudentEnrollment.objects.create(
        school=school, student=student, section=section, academic_year=year,
        roll_number="14", enrollment_date=date(2025, 6, 1), status="active",
    )
    school.current_academic_year = year
    school.save(update_fields=["current_academic_year"])
    user = User.objects.create(
        phone=phone, role=Role.PARENT, school=school, first_name="Suresh", last_name="Reddy"
    )
    user.set_unusable_password()
    user.save()
    parent = Parent.objects.create(school=school, user=user, name="Suresh Reddy", phone=phone)
    ParentStudent.objects.create(school=school, parent=parent, student=student)
    return user, student


def _card(school, student, year, *, term, published=True, overall_pct=80):
    snapshot = {
        "term": "Term 1" if term == ReportCardTerm.TERM_1 else "Term 2",
        "academicYear": year.label,
        "issueDate": "2026-02-28",
        "subjects": [
            {"name": "Mathematics", "maxMarks": 100, "marks": 85, "grade": "A2"},
            {"name": "Science", "maxMarks": 100, "marks": 78, "grade": "B1"},
        ],
        "attendancePct": 92,
        "teacherRemark": "Steady improvement.",
        "overallGrade": "A2",
        "overallPct": overall_pct,
        "totalStudents": 30,
    }
    return ReportCard.objects.create(
        school=school, student=student, academic_year=year, term=term,
        published_at=timezone.now() if published else None,
        data_snapshot=snapshot,
    )


@pytest.mark.django_db
def test_list_returns_only_published_cards(client: Client, world_a) -> None:
    user, student = _parent_with_child(world_a)
    school, year = world_a["school"], world_a["year"]
    _card(school, student, year, term=ReportCardTerm.TERM_2)
    _card(school, student, year, term=ReportCardTerm.TERM_1, published=False)

    res = client.get(f"/api/v1/parent/children/{student.id}/report-cards", **_auth(user))
    assert res.status_code == 200, res.content
    body = res.json()
    assert len(body) == 1
    assert body[0]["term"] == "Term 2"
    # The full snapshot rides through — including subjects + rank.
    assert body[0]["subjects"][0]["name"] == "Mathematics"


@pytest.mark.django_db
def test_list_orders_newest_first(client: Client, world_a) -> None:
    user, student = _parent_with_child(world_a)
    school, year = world_a["school"], world_a["year"]
    c1 = _card(school, student, year, term=ReportCardTerm.TERM_1)
    # Push Term 2 forward in time so it's the newest.
    c2 = _card(school, student, year, term=ReportCardTerm.TERM_2)
    c2.published_at = timezone.now() + timezone.timedelta(hours=1)
    c2.save(update_fields=["published_at"])
    res = client.get(f"/api/v1/parent/children/{student.id}/report-cards", **_auth(user))
    ids = [c["id"] for c in res.json()]
    assert ids == [c2.id, c1.id]


@pytest.mark.django_db
def test_detail_returns_snapshot(client: Client, world_a) -> None:
    user, student = _parent_with_child(world_a)
    card = _card(world_a["school"], student, world_a["year"], term=ReportCardTerm.TERM_2)
    res = client.get(
        f"/api/v1/parent/children/{student.id}/report-cards/{card.id}", **_auth(user)
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["id"] == card.id
    assert body["overallGrade"] == "A2"
    assert len(body["subjects"]) == 2


@pytest.mark.django_db
def test_detail_404_for_draft(client: Client, world_a) -> None:
    user, student = _parent_with_child(world_a)
    draft = _card(world_a["school"], student, world_a["year"],
                  term=ReportCardTerm.TERM_2, published=False)
    res = client.get(
        f"/api/v1/parent/children/{student.id}/report-cards/{draft.id}", **_auth(user)
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_cross_tenant_detail_404(client: Client, world_a, world_b) -> None:
    user_a, _ = _parent_with_child(world_a, phone="+919876512345")
    _, student_b = _parent_with_child(world_b, phone="+919876599999")
    other = _card(world_b["school"], student_b, world_b["year"], term=ReportCardTerm.TERM_2)
    res = client.get(
        f"/api/v1/parent/children/{student_b.id}/report-cards/{other.id}", **_auth(user_a)
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_unlinked_child_list_404(client: Client, world_a) -> None:
    user, _ = _parent_with_child(world_a)
    stranger = StudentFactory(school=world_a["school"], first_name="Stranger")
    res = client.get(f"/api/v1/parent/children/{stranger.id}/report-cards", **_auth(user))
    assert res.status_code == 404
