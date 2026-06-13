"""HTTP tests for the teacher report-card endpoints (v2: named, custom subjects)."""

from __future__ import annotations

from datetime import date

import pytest
from django.test import Client

from apps.academics.models import StudentEnrollment, TeacherAssignment
from apps.academics.tests.factories import SubjectFactory
from apps.accounts.services import issue_tokens_for_user
from apps.exams.models import ReportCard
from apps.people.tests.factories import StudentFactory, TeacherFactory


def _auth(user) -> dict:  # type: ignore[no-untyped-def]
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_tokens_for_user(user)['access_token']}"}


def _setup(world: dict, *, as_class_teacher: bool = True):  # type: ignore[no-untyped-def]
    school, year, section = world["school"], world["year"], world["section_a"]
    teacher = TeacherFactory(school=school, user=world["teacher_user"])
    subject = SubjectFactory(school=school, name="Science")
    TeacherAssignment.objects.create(
        school=school, teacher=teacher, subject=subject, section=section, academic_year=year
    )
    if as_class_teacher:
        section.class_teacher = teacher
        section.save(update_fields=["class_teacher"])
    school.current_academic_year = year
    school.save(update_fields=["current_academic_year"])
    return teacher, section


def _enroll(world: dict, section, roll: int = 1, name: str = "Aarav Reddy"):  # type: ignore[no-untyped-def]
    school, year = world["school"], world["year"]
    first, _, last = name.partition(" ")
    student = StudentFactory(school=school, first_name=first, last_name=last)
    StudentEnrollment.objects.create(
        school=school, student=student, section=section, academic_year=year,
        roll_number=str(roll), enrollment_date=date(2025, 6, 1), status="active",
    )
    return student


def _publish(client, section, world, *, name, subjects, records, publish=True):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/v1/teacher/report-cards/{section.id}/publish",
        data={"name": name, "subjects": subjects, "publish": publish, "records": records},
        content_type="application/json",
        **_auth(world["teacher_user"]),
    )


@pytest.mark.django_db
def test_sections_lists_only_class_teacher_sections(client: Client, world_a) -> None:
    _setup(world_a)
    res = client.get("/api/v1/teacher/report-cards/sections", **_auth(world_a["teacher_user"]))
    assert res.status_code == 200, res.content
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["section"] == "A"
    assert rows[0]["reportCount"] == 0


@pytest.mark.django_db
def test_publish_computes_overall_from_custom_max(client: Client, world_a) -> None:
    _teacher, section = _setup(world_a)
    s1 = _enroll(world_a, section, roll=1, name="Aarav Reddy")
    # Maths /50 = 45 (90%), English /100 = 90 (90%) → overall = 135/150 = 90%.
    subjects = [{"name": "Maths", "maxMarks": 50}, {"name": "English", "maxMarks": 100}]
    res = _publish(
        client, section, world_a, name="Unit Test 1", subjects=subjects,
        records=[{"studentId": str(s1.id), "remark": "Good", "marks": {"Maths": 45, "English": 90}}],
    )
    assert res.status_code == 200, res.content
    assert res.json() == {"saved": 1, "published": 1}
    card = ReportCard.objects.all_tenants().get(student=s1, term="Unit Test 1")
    snap = card.data_snapshot
    assert snap["overallPct"] == 90
    assert snap["overallGrade"] == "A2"
    assert snap["subjects"][0] == {"name": "Maths", "maxMarks": 50, "marks": 45, "grade": "A2"}
    assert card.published_at is not None


@pytest.mark.django_db
def test_reports_history_groups_by_name(client: Client, world_a) -> None:
    _teacher, section = _setup(world_a)
    s1 = _enroll(world_a, section, roll=1)
    subjects = [{"name": "Maths", "maxMarks": 100}]
    _publish(client, section, world_a, name="Term 1", subjects=subjects,
             records=[{"studentId": str(s1.id), "marks": {"Maths": 80}}], publish=True)
    _publish(client, section, world_a, name="Unit Test 1", subjects=subjects,
             records=[{"studentId": str(s1.id), "marks": {"Maths": 70}}], publish=False)

    res = client.get(
        f"/api/v1/teacher/report-cards/{section.id}/reports", **_auth(world_a["teacher_user"])
    )
    assert res.status_code == 200, res.content
    by_name = {r["name"]: r for r in res.json()}
    assert by_name["Term 1"]["publishedCount"] == 1
    assert by_name["Term 1"]["draftCount"] == 0
    assert by_name["Unit Test 1"]["publishedCount"] == 0
    assert by_name["Unit Test 1"]["draftCount"] == 1


@pytest.mark.django_db
def test_roster_prefills_subjects_from_latest_report(client: Client, world_a) -> None:
    _teacher, section = _setup(world_a)
    s1 = _enroll(world_a, section, roll=1)
    subjects = [{"name": "Maths", "maxMarks": 50}, {"name": "Telugu", "maxMarks": 25}]
    _publish(client, section, world_a, name="Term 1", subjects=subjects,
             records=[{"studentId": str(s1.id), "marks": {"Maths": 40, "Telugu": 20}}])

    # New report (no name) → subjects templated from the latest report, marks blank.
    res = client.get(
        f"/api/v1/teacher/report-cards/{section.id}/roster", **_auth(world_a["teacher_user"])
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["subjects"] == [
        {"name": "Maths", "maxMarks": 50},
        {"name": "Telugu", "maxMarks": 25},
    ]
    assert body["students"][0]["marks"] == {"Maths": None, "Telugu": None}


@pytest.mark.django_db
def test_roster_hydrates_existing_named_report(client: Client, world_a) -> None:
    _teacher, section = _setup(world_a)
    s1 = _enroll(world_a, section, roll=1)
    subjects = [{"name": "Maths", "maxMarks": 50}]
    _publish(client, section, world_a, name="Term 1", subjects=subjects,
             records=[{"studentId": str(s1.id), "remark": "Nice", "marks": {"Maths": 40}}])

    res = client.get(
        f"/api/v1/teacher/report-cards/{section.id}/roster?name=Term 1",
        **_auth(world_a["teacher_user"]),
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["students"][0]["marks"] == {"Maths": 40}
    assert body["students"][0]["remark"] == "Nice"
    assert body["students"][0]["alreadyPublished"] is True


@pytest.mark.django_db
def test_save_is_idempotent_on_same_name(client: Client, world_a) -> None:
    _teacher, section = _setup(world_a)
    s1 = _enroll(world_a, section, roll=1)
    subjects = [{"name": "Maths", "maxMarks": 100}]
    rec = [{"studentId": str(s1.id), "marks": {"Maths": 80}}]
    _publish(client, section, world_a, name="Term 1", subjects=subjects, records=rec)
    _publish(client, section, world_a, name="Term 1", subjects=subjects, records=rec)
    assert ReportCard.objects.all_tenants().filter(student=s1, term="Term 1").count() == 1


@pytest.mark.django_db
def test_draft_leaves_published_null(client: Client, world_a) -> None:
    _teacher, section = _setup(world_a)
    s1 = _enroll(world_a, section, roll=1)
    res = _publish(
        client, section, world_a, name="Term 1",
        subjects=[{"name": "Maths", "maxMarks": 100}],
        records=[{"studentId": str(s1.id), "marks": {"Maths": 55}}], publish=False,
    )
    assert res.json() == {"saved": 1, "published": 0}
    assert ReportCard.objects.all_tenants().get(student=s1, term="Term 1").published_at is None


@pytest.mark.django_db
def test_publish_single_student_only(client: Client, world_a) -> None:
    _teacher, section = _setup(world_a)
    s1 = _enroll(world_a, section, roll=1, name="Aarav Reddy")
    s2 = _enroll(world_a, section, roll=2, name="Diya Nair")
    subjects = [{"name": "Maths", "maxMarks": 100}]
    # Batch publish off; only s1 flagged publish=true.
    res = _publish(
        client, section, world_a, name="Term 1", subjects=subjects, publish=False,
        records=[
            {"studentId": str(s1.id), "marks": {"Maths": 80}, "publish": True},
            {"studentId": str(s2.id), "marks": {"Maths": 70}},
        ],
    )
    assert res.status_code == 200, res.content
    assert res.json() == {"saved": 2, "published": 1}
    assert ReportCard.objects.all_tenants().get(student=s1, term="Term 1").published_at is not None
    assert ReportCard.objects.all_tenants().get(student=s2, term="Term 1").published_at is None


@pytest.mark.django_db
def test_draft_save_preserves_already_published(client: Client, world_a) -> None:
    _teacher, section = _setup(world_a)
    s1 = _enroll(world_a, section, roll=1)
    subjects = [{"name": "Maths", "maxMarks": 100}]
    # Publish first.
    _publish(client, section, world_a, name="Term 1", subjects=subjects,
             records=[{"studentId": str(s1.id), "marks": {"Maths": 80}}], publish=True)
    # Re-save as draft → must NOT un-publish.
    _publish(client, section, world_a, name="Term 1", subjects=subjects,
             records=[{"studentId": str(s1.id), "marks": {"Maths": 85}}], publish=False)
    card = ReportCard.objects.all_tenants().get(student=s1, term="Term 1")
    assert card.published_at is not None
    assert card.data_snapshot["subjects"][0]["marks"] == 85  # edit still saved


@pytest.mark.django_db
def test_publish_requires_name_and_subjects(client: Client, world_a) -> None:
    _teacher, section = _setup(world_a)
    s1 = _enroll(world_a, section, roll=1)
    # Missing subjects.
    res = _publish(client, section, world_a, name="Term 1", subjects=[],
                   records=[{"studentId": str(s1.id), "marks": {}}])
    assert res.status_code == 422 or res.status_code == 400


@pytest.mark.django_db
def test_non_class_teacher_gets_404(client: Client, world_a) -> None:
    school, year, section_b = world_a["school"], world_a["year"], world_a["section_b"]
    teacher = TeacherFactory(school=school, user=world_a["teacher_user"])
    subject = SubjectFactory(school=school, name="Maths")
    TeacherAssignment.objects.create(
        school=school, teacher=teacher, subject=subject, section=section_b, academic_year=year
    )
    school.current_academic_year = year
    school.save(update_fields=["current_academic_year"])
    res = client.get(
        f"/api/v1/teacher/report-cards/{section_b.id}/roster", **_auth(world_a["teacher_user"])
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_publish_cross_tenant_404(client: Client, world_a, world_b) -> None:
    _setup(world_a)
    other_section = world_b["section_a"]
    res = _publish(
        client, other_section, world_a, name="Term 1",
        subjects=[{"name": "Maths", "maxMarks": 100}], records=[],
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_requires_auth(client: Client, world_a) -> None:
    res = client.get("/api/v1/teacher/report-cards/sections")
    assert res.status_code == 401
