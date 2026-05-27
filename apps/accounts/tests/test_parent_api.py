"""HTTP tests for the parent app (skooly-parent) API.

Covers OTP auth, the bootstrap payload, per-parent child scoping (the critical
isolation surface), role-locking, and the read endpoints (attendance/marks/fees).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from apps.academics.models import StudentEnrollment
from apps.academics.tests.factories import SubjectFactory
from apps.accounts import parent_services
from apps.accounts.models import Role, User
from apps.accounts.services import issue_tokens_for_user
from apps.attendance.models import Attendance, AttendanceStatus
from apps.exams.models import Test, TestMode, TestScore, TestType
from apps.fees.models import (
    FeeComponent,
    FeePayment,
    FeePaymentComponent,
    FeeStructure,
    StudentFee,
    StudentFeeComponent,
)
from apps.people.models import Parent, ParentStudent
from apps.people.tests.factories import StudentFactory

PHONE_A = "+919876512345"
PHONE_B = "+919876599999"


def _auth(user: User) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_tokens_for_user(user)['access_token']}"}


def _make_parent(world: dict, phone: str, *, enroll: bool = True):
    """Create a parent + one enrolled child in the given world's school."""
    school, year, section = world["school"], world["year"], world["section_a"]
    student = StudentFactory(school=school, first_name="Aarav", last_name="Reddy")
    if enroll:
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
    return parent, user, student


# --- Auth -------------------------------------------------------------------

@pytest.mark.django_db
def test_send_otp_unknown_phone_404(client: Client, world_a) -> None:
    res = client.post(
        "/api/v1/parent/auth/send-otp",
        data={"phone": "9999999999"},
        content_type="application/json",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_otp_login_returns_token_and_children(client: Client, world_a) -> None:
    _make_parent(world_a, PHONE_A)
    code = parent_services.send_parent_otp(PHONE_A)

    res = client.post(
        "/api/v1/parent/auth/verify-otp",
        data={"phone": PHONE_A, "otp": code},
        content_type="application/json",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["token"]
    assert body["parent"]["name"] == "Suresh Reddy"
    assert len(body["children"]) == 1
    child = body["children"][0]
    assert child["class"] == "Class 6"
    assert child["section"] == "A"
    assert child["rollNo"] == 14
    assert child["photoColor"].startswith("bg-")


@pytest.mark.django_db
def test_verify_otp_wrong_code_rejected(client: Client, world_a) -> None:
    _make_parent(world_a, PHONE_A)
    parent_services.send_parent_otp(PHONE_A)
    res = client.post(
        "/api/v1/parent/auth/verify-otp",
        data={"phone": PHONE_A, "otp": "000000"},
        content_type="application/json",
    )
    # InvalidOTP → 400, consistent with the teacher OTP flow.
    assert res.status_code == 400


@pytest.mark.django_db
def test_parent_me_returns_children(client: Client, world_a) -> None:
    _parent, user, _student = _make_parent(world_a, PHONE_A)
    res = client.get("/api/v1/parent/parent/me", **_auth(user))
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["phone"] == "+91 98765 12345"
    assert len(body["children"]) == 1


# --- Role lock + isolation --------------------------------------------------

@pytest.mark.django_db
def test_teacher_token_rejected(client: Client, world_a) -> None:
    res = client.get("/api/v1/parent/parent/me", **_auth(world_a["teacher_user"]))
    assert res.status_code == 401


@pytest.mark.django_db
def test_cross_tenant_child_404(client: Client, world_a, world_b) -> None:
    """A parent in School A cannot read a child that lives in School B."""
    _pa, user_a, _ca = _make_parent(world_a, PHONE_A)
    _pb, _ub, child_b = _make_parent(world_b, PHONE_B)
    res = client.get(
        f"/api/v1/parent/children/{child_b.id}/feed", **_auth(user_a)
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_unlinked_child_same_school_404(client: Client, world_a) -> None:
    """A student in the same school but not linked to this parent is invisible."""
    _pa, user_a, _ca = _make_parent(world_a, PHONE_A)
    stranger = StudentFactory(school=world_a["school"], first_name="Stranger")
    res = client.get(
        f"/api/v1/parent/children/{stranger.id}/fees", **_auth(user_a)
    )
    assert res.status_code == 404


# --- Read endpoints ---------------------------------------------------------

@pytest.mark.django_db
def test_monthly_attendance(client: Client, world_a) -> None:
    _pa, user_a, student = _make_parent(world_a, PHONE_A)
    Attendance.objects.create(
        school=world_a["school"], student=student, section=world_a["section_a"],
        date=date(2026, 5, 12), status=AttendanceStatus.ABSENT, notes="Unwell",
    )
    res = client.get(
        f"/api/v1/parent/children/{student.id}/attendance?year=2026&month=5",
        **_auth(user_a),
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["days"][0]["status"] == "absent"
    assert body["days"][0]["note"] == "Unwell"


@pytest.mark.django_db
def test_marks_list(client: Client, world_a) -> None:
    _pa, user_a, student = _make_parent(world_a, PHONE_A)
    school, section = world_a["school"], world_a["section_a"]
    subject = SubjectFactory(school=school, name="Mathematics")
    test = Test.objects.create(
        school=school, section=section, subject=subject, name="Unit Test 2",
        test_type=TestType.OTHER, mode=TestMode.OFFLINE, test_date=date(2026, 5, 20),
        max_marks=25, published_at=timezone.now(),
    )
    TestScore.objects.create(
        school=school, test=test, student=student, marks_obtained=Decimal("18"),
    )
    res = client.get(f"/api/v1/parent/children/{student.id}/tests", **_auth(user_a))
    assert res.status_code == 200, res.content
    tests = res.json()["tests"]
    assert len(tests) == 1
    assert tests[0]["marks"] == 18
    assert tests[0]["maxMarks"] == 25
    assert tests[0]["subject"] == "Mathematics"
    assert tests[0]["rank"] == 1


def _make_test_with_score(world: dict, student, *, name="Unit Test 2", marks="18", max_marks=25):
    school, section = world["school"], world["section_a"]
    subject = SubjectFactory(school=school, name="Mathematics")
    test = Test.objects.create(
        school=school, section=section, subject=subject, name=name,
        test_type=TestType.OTHER, mode=TestMode.OFFLINE, test_date=date(2026, 4, 20),
        max_marks=max_marks, published_at=timezone.now(),
    )
    TestScore.objects.create(
        school=school, test=test, student=student, marks_obtained=Decimal(marks)
    )
    return test


@pytest.mark.django_db
def test_marks_detail(client: Client, world_a) -> None:
    _pa, user_a, student = _make_parent(world_a, PHONE_A)
    test = _make_test_with_score(world_a, student)
    res = client.get(
        f"/api/v1/parent/children/{student.id}/tests/{test.id}", **_auth(user_a)
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["id"] == test.id
    assert body["marks"] == 18
    assert body["maxMarks"] == 25


@pytest.mark.django_db
def test_marks_detail_unknown_test_404(client: Client, world_a) -> None:
    _pa, user_a, student = _make_parent(world_a, PHONE_A)
    res = client.get(
        f"/api/v1/parent/children/{student.id}/tests/999999", **_auth(user_a)
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_yearly_attendance(client: Client, world_a) -> None:
    _pa, user_a, student = _make_parent(world_a, PHONE_A)
    school, section = world_a["school"], world_a["section_a"]
    # Inside the AY range (2025-06-01 .. 2026-04-30).
    rows = [
        (date(2026, 3, 10), AttendanceStatus.PRESENT),
        (date(2026, 3, 11), AttendanceStatus.ABSENT),
        (date(2026, 4, 5), AttendanceStatus.PRESENT),
    ]
    for d, status in rows:
        Attendance.objects.create(
            school=school, student=student, section=section, date=d, status=status
        )
    res = client.get(
        f"/api/v1/parent/children/{student.id}/attendance/yearly", **_auth(user_a)
    )
    assert res.status_code == 200, res.content
    months = {m["shortMonth"]: m for m in res.json()["months"]}
    assert months["Mar"]["present"] == 1 and months["Mar"]["schoolDays"] == 2
    assert months["Mar"]["pct"] == 50
    assert months["Apr"]["present"] == 1 and months["Apr"]["pct"] == 100


@pytest.mark.django_db
def test_feed_includes_recent_attendance(client: Client, world_a) -> None:
    _pa, user_a, student = _make_parent(world_a, PHONE_A)
    Attendance.objects.create(
        school=world_a["school"], student=student, section=world_a["section_a"],
        date=date(2026, 4, 20), status=AttendanceStatus.ABSENT,
    )
    res = client.get(f"/api/v1/parent/children/{student.id}/feed", **_auth(user_a))
    assert res.status_code == 200, res.content
    items = res.json()["items"]
    att = [i for i in items if i["type"] == "attendance"]
    assert att and att[0]["message"].endswith("was absent")
    assert att[0]["linkTo"] == "/attendance"


@pytest.mark.django_db
def test_feed_includes_marks_and_overdue_fees(client: Client, world_a) -> None:
    _pa, user_a, student = _make_parent(world_a, PHONE_A)
    school, year = world_a["school"], world_a["year"]
    _make_test_with_score(world_a, student, name="Mathematics Unit Test", marks="18")

    structure = FeeStructure.objects.create(
        school=school, academic_year=year, class_obj=world_a["class"], name="Std"
    )
    comp = FeeComponent.objects.create(
        school=school, fee_structure=structure, name="Transport",
        amount_paise=5_000_00, due_date=date(2025, 6, 1),
    )
    sf = StudentFee.objects.create(
        school=school, student=student, fee_structure=structure, academic_year=year,
        total_paise=5_000_00, final_paise=5_000_00, paid_paise=0, status="overdue",
    )
    StudentFeeComponent.objects.create(
        school=school, student_fee=sf, fee_component=comp,
        applied_paise=5_000_00, paid_paise=0, is_applicable=True, status="overdue",
    )

    res = client.get(f"/api/v1/parent/children/{student.id}/feed", **_auth(user_a))
    assert res.status_code == 200, res.content
    by_type = {i["type"] for i in res.json()["items"]}
    assert "marks" in by_type
    assert "fee" in by_type


@pytest.mark.django_db
def test_fee_status(client: Client, world_a) -> None:
    _pa, user_a, student = _make_parent(world_a, PHONE_A)
    school, year = world_a["school"], world_a["year"]
    structure = FeeStructure.objects.create(
        school=school, academic_year=year, class_obj=world_a["class"], name="Std"
    )
    comp = FeeComponent.objects.create(
        school=school, fee_structure=structure, name="Tuition",
        amount_paise=30_000_00, due_date=date(2025, 6, 1),
    )
    sf = StudentFee.objects.create(
        school=school, student=student, fee_structure=structure, academic_year=year,
        total_paise=30_000_00, final_paise=30_000_00, paid_paise=10_000_00, status="partial",
    )
    sfc = StudentFeeComponent.objects.create(
        school=school, student_fee=sf, fee_component=comp,
        applied_paise=30_000_00, paid_paise=10_000_00, is_applicable=True, status="partial",
    )
    payment = FeePayment.objects.create(
        school=school, student_fee=sf, total_paise=10_000_00, payment_mode="cash",
        paid_on=date(2026, 4, 1), receipt_number="T/2025-26/0001",
    )
    FeePaymentComponent.objects.create(
        school=school, payment=payment, student_fee_component=sfc, amount_paise=10_000_00
    )

    res = client.get(f"/api/v1/parent/children/{student.id}/fees", **_auth(user_a))
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["academicYear"] == "2025-26"
    assert body["components"][0]["name"] == "Tuition"
    assert body["components"][0]["paid"] == 10_000  # rupees, not paise
    assert body["components"][0]["due"] == 20_000
    assert body["components"][0]["status"] == "due"
    assert body["payments"][0]["amount"] == 10_000
    assert body["payments"][0]["receiptNo"] == "T/2025-26/0001"
    assert body["payments"][0]["components"] == ["Tuition"]


# --- Session lifecycle ------------------------------------------------------

@pytest.mark.django_db
def test_logout_requires_no_auth(client: Client) -> None:
    """Logout is stateless — must succeed without a token (else it loops)."""
    res = client.post("/api/v1/parent/auth/logout", content_type="application/json")
    assert res.status_code == 200
    assert res.json() == {"success": True}


@pytest.mark.django_db
def test_refresh_reissues_token(client: Client, world_a) -> None:
    _pa, user_a, _student = _make_parent(world_a, PHONE_A)
    res = client.post("/api/v1/parent/auth/refresh", **_auth(user_a))
    assert res.status_code == 200, res.content
    assert res.json()["token"]


@pytest.mark.django_db
def test_dev_master_otp_logs_in(client: Client, world_a) -> None:
    """With the mock provider, the fixed dev code works without a sent OTP."""
    _make_parent(world_a, PHONE_A)
    res = client.post(
        "/api/v1/parent/auth/verify-otp",
        data={"phone": PHONE_A, "otp": "123456"},
        content_type="application/json",
    )
    assert res.status_code == 200, res.content
    assert res.json()["token"]
    assert len(res.json()["children"]) == 1
