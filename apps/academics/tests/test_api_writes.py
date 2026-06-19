"""Write endpoints for academics: classes, sections, subjects, assignments."""

from __future__ import annotations

import pytest

from apps.academics.tests.factories import SubjectFactory
from apps.people.tests.factories import TeacherFactory


@pytest.mark.django_db
def test_create_class(client, admin_token_a, world_a):
    res = client.post(
        "/api/v1/classes",
        data={"academicYearId": world_a["year"].id, "name": "Class 7", "displayOrder": 7},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    assert res.json()["name"] == "Class 7"


@pytest.mark.django_db
def test_create_class_cross_tenant_year_404(client, admin_token_a, world_b):
    res = client.post(
        "/api/v1/classes",
        data={"academicYearId": world_b["year"].id, "name": "Class 99"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_delete_class_with_sections_rejected(client, admin_token_a, world_a):
    res = client.delete(
        f"/api/v1/classes/{world_a['class'].id}",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 409
    assert "sections" in res.json()["error"]["message"].lower()


@pytest.mark.django_db
def test_create_section_with_class_teacher(client, admin_token_a, world_a):
    teacher = TeacherFactory(school=world_a["school"], phone="+918888000001")
    res = client.post(
        "/api/v1/sections",
        data={
            "classId": world_a["class"].id,
            "name": "C",
            "classTeacherId": teacher.id,
            "roomNumber": "6C",
            "capacity": 35,
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["name"] == "C"
    assert body["classTeacherId"] == teacher.id


@pytest.mark.django_db
def test_create_section_cross_tenant_teacher_404(client, admin_token_a, world_a, world_b):
    foreign_teacher = TeacherFactory(school=world_b["school"], phone="+918888000099")
    res = client.post(
        "/api/v1/sections",
        data={
            "classId": world_a["class"].id, "name": "Z",
            "classTeacherId": foreign_teacher.id,
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_delete_section_with_active_enrollments_rejected(client, admin_token_a, world_a):
    """Create a student in section A then try to delete the section."""
    payload = {
        "firstName": "Test", "gender": "Male", "admissionDate": "2025-06-15",
        "sectionId": world_a["section_a"].id,
    }
    client.post(
        "/api/v1/students", data=payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    res = client.delete(
        f"/api/v1/sections/{world_a['section_a'].id}",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 409


@pytest.mark.django_db
def test_subject_crud(client, admin_token_a, world_a):
    res = client.post(
        "/api/v1/subjects",
        data={"name": "Mathematics", "code": "MAT"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200
    subject_id = res.json()["id"]

    res = client.patch(
        f"/api/v1/subjects/{subject_id}",
        data={"code": "MATH"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200
    assert res.json()["code"] == "MATH"

    res = client.delete(
        f"/api/v1/subjects/{subject_id}",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200


@pytest.mark.django_db
def test_teacher_assignment_create_and_delete(client, admin_token_a, world_a):
    teacher = TeacherFactory(school=world_a["school"], phone="+918888001000")
    subject = SubjectFactory(school=world_a["school"], name="English")
    res = client.post(
        "/api/v1/teacher-assignments",
        data={
            "teacherId": teacher.id,
            "subjectId": subject.id,
            "sectionId": world_a["section_a"].id,
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    assignment_id = res.json()["data"]["id"]

    # Duplicate should fail
    res2 = client.post(
        "/api/v1/teacher-assignments",
        data={
            "teacherId": teacher.id,
            "subjectId": subject.id,
            "sectionId": world_a["section_a"].id,
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res2.status_code == 409

    res3 = client.delete(
        f"/api/v1/teacher-assignments/{assignment_id}",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res3.status_code == 200


@pytest.mark.django_db
def test_list_section_teacher_assignments(client, admin_token_a, world_a):
    """Read endpoint returns one row per class subject, with the assigned
    teacher filled in where an assignment exists."""
    from apps.academics.models import SubjectClassMapping, TeacherAssignment

    school = world_a["school"]
    cls = world_a["class"]
    section = world_a["section_a"]
    math = SubjectFactory(school=school, name="Math")
    science = SubjectFactory(school=school, name="Science")
    SubjectClassMapping.objects.create(school=school, subject=math, class_obj=cls)
    SubjectClassMapping.objects.create(school=school, subject=science, class_obj=cls)
    teacher = TeacherFactory(school=school, phone="+918888003000")
    TeacherAssignment.objects.create(
        school=school,
        teacher=teacher,
        subject=math,
        section=section,
        academic_year=world_a["year"],
    )

    res = client.get(
        f"/api/v1/sections/{section.id}/teacher-assignments",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    rows = res.json()
    # Ordered by subject name.
    assert [r["subjectName"] for r in rows] == ["Math", "Science"]
    math_row = next(r for r in rows if r["subjectName"] == "Math")
    assert math_row["teacherId"] == teacher.id
    assert math_row["assignmentId"] is not None
    science_row = next(r for r in rows if r["subjectName"] == "Science")
    assert science_row["teacherId"] is None
    assert science_row["assignmentId"] is None


@pytest.mark.django_db
def test_teacher_assignment_cross_tenant_404(
    client, admin_token_a, world_a, world_b
):
    """Admin A tries to assign A's teacher to B's section → 404 on section lookup."""
    teacher = TeacherFactory(school=world_a["school"], phone="+918888002000")
    subject = SubjectFactory(school=world_a["school"], name="Hindi")
    res = client.post(
        "/api/v1/teacher-assignments",
        data={
            "teacherId": teacher.id,
            "subjectId": subject.id,
            "sectionId": world_b["section_a"].id,
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_class_subject_attach_list_detach(client, admin_token_a, world_a):
    """Attach a subject to a class, see it in the class-subjects list, detach it."""
    school = world_a["school"]
    cls = world_a["class"]
    subject = SubjectFactory(school=school, name="Geography")

    # Initially the class has no subjects.
    res = client.get(
        f"/api/v1/classes/{cls.id}/subjects",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200
    assert res.json() == []

    # Attach.
    res = client.post(
        f"/api/v1/classes/{cls.id}/subjects",
        data={"subjectId": subject.id},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content

    # Now listed.
    res = client.get(
        f"/api/v1/classes/{cls.id}/subjects",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert [s["name"] for s in res.json()] == ["Geography"]

    # Duplicate attach → 409.
    res = client.post(
        f"/api/v1/classes/{cls.id}/subjects",
        data={"subjectId": subject.id},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 409

    # Detach.
    res = client.delete(
        f"/api/v1/classes/{cls.id}/subjects/{subject.id}",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200

    # Re-attach works (proves we didn't leave a soft-deleted row blocking it).
    res = client.post(
        f"/api/v1/classes/{cls.id}/subjects",
        data={"subjectId": subject.id},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content


@pytest.mark.django_db
def test_class_subject_cross_tenant_404(client, admin_token_a, world_a, world_b):
    """Admin A cannot attach a subject to B's class."""
    subject = SubjectFactory(school=world_a["school"], name="Civics")
    res = client.post(
        f"/api/v1/classes/{world_b['class'].id}/subjects",
        data={"subjectId": subject.id},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_teacher_cannot_attach_class_subject(client, teacher_token_a, world_a):
    subject = SubjectFactory(school=world_a["school"], name="Art")
    res = client.post(
        f"/api/v1/classes/{world_a['class'].id}/subjects",
        data={"subjectId": subject.id},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {teacher_token_a}",
    )
    assert res.status_code == 403


@pytest.mark.django_db
def test_teacher_cannot_create_class(client, teacher_token_a, world_a):
    res = client.post(
        "/api/v1/classes",
        data={"academicYearId": world_a["year"].id, "name": "Class 99"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {teacher_token_a}",
    )
    assert res.status_code == 403


@pytest.mark.django_db
def test_section_timetable_save_and_read(client, admin_token_a, world_a):
    """Save a weekly timetable; teacher is auto-derived from the subject's
    assignment so the teacher app's schedule is populated."""
    from apps.academics.models import TeacherAssignment, TimetablePeriod
    from apps.people.tests.factories import TeacherFactory

    school = world_a["school"]
    section = world_a["section_a"]
    maths = SubjectFactory(school=school, name="Maths")
    teacher = TeacherFactory(school=school, phone="+918888777000")
    TeacherAssignment.objects.create(
        school=school, teacher=teacher, subject=maths, section=section,
        academic_year=world_a["year"],
    )

    payload = {
        "slots": [{"periodNumber": 1, "startTime": "09:00", "endTime": "09:45"}],
        "entries": [{"dayOfWeek": 1, "periodNumber": 1, "subjectId": maths.id}],
    }
    res = client.put(
        f"/api/v1/sections/{section.id}/timetable",
        data=payload,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["slots"][0]["startTime"] == "09:00"
    assert body["entries"][0]["subjectName"] == "Maths"
    # Teacher auto-derived from the assignment → drives the teacher app.
    assert body["entries"][0]["teacherId"] == teacher.id

    period = TimetablePeriod.objects.all_tenants().get(section=section, day_of_week=1, period_number=1)
    assert period.teacher_id == teacher.id


@pytest.mark.django_db
def test_section_timetable_replaces(client, admin_token_a, world_a):
    """A second save fully replaces the prior timetable."""
    from apps.academics.models import TimetablePeriod

    school = world_a["school"]
    section = world_a["section_a"]
    sci = SubjectFactory(school=school, name="Science")
    tel = SubjectFactory(school=school, name="Telugu")

    def _save(subject_id):
        return client.put(
            f"/api/v1/sections/{section.id}/timetable",
            data={
                "slots": [{"periodNumber": 1, "startTime": "10:00", "endTime": "10:45"}],
                "entries": [{"dayOfWeek": 2, "periodNumber": 1, "subjectId": subject_id}],
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
        )

    assert _save(sci.id).status_code == 200
    assert _save(tel.id).status_code == 200
    rows = TimetablePeriod.objects.all_tenants().filter(section=section)
    assert rows.count() == 1
    assert rows.first().subject_id == tel.id


@pytest.mark.django_db
def test_section_timetable_rejects_duplicate_cell(client, admin_token_a, world_a):
    school = world_a["school"]
    section = world_a["section_a"]
    s = SubjectFactory(school=school, name="Hindi")
    res = client.put(
        f"/api/v1/sections/{section.id}/timetable",
        data={
            "slots": [{"periodNumber": 1, "startTime": "09:00", "endTime": "09:45"}],
            "entries": [
                {"dayOfWeek": 1, "periodNumber": 1, "subjectId": s.id},
                {"dayOfWeek": 1, "periodNumber": 1, "subjectId": s.id},
            ],
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 422


@pytest.mark.django_db
def test_changing_subject_teacher_resyncs_timetable(client, admin_token_a, world_a):
    """Assigning a teacher to a subject updates existing timetable periods."""
    from apps.academics.models import TimetablePeriod
    from apps.people.tests.factories import TeacherFactory

    school = world_a["school"]
    section = world_a["section_a"]
    music = SubjectFactory(school=school, name="Music")
    # Timetable saved while the subject has no teacher → period.teacher is null.
    client.put(
        f"/api/v1/sections/{section.id}/timetable",
        data={
            "slots": [{"periodNumber": 1, "startTime": "09:00", "endTime": "09:45"}],
            "entries": [{"dayOfWeek": 3, "periodNumber": 1, "subjectId": music.id}],
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert TimetablePeriod.objects.all_tenants().get(section=section).teacher_id is None

    teacher = TeacherFactory(school=school, phone="+918888777111")
    res = client.post(
        "/api/v1/teacher-assignments",
        data={"teacherId": teacher.id, "subjectId": music.id, "sectionId": section.id},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )
    assert res.status_code == 200, res.content
    assert TimetablePeriod.objects.all_tenants().get(section=section).teacher_id == teacher.id
