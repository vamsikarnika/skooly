"""Bulk import tests — the highest-risk surface in Module 2."""

from __future__ import annotations

from datetime import date
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from apps.people.models import Student

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _make_xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


HEADERS = [
    "admission_number", "first_name", "last_name", "gender", "dob",
    "admission_date", "class_name", "section_name", "roll_number",
    "parent1_name", "parent1_phone", "parent1_relation", "parent1_whatsapp",
]


def _post(client, token, file_bytes, *, dry_run=True):  # type: ignore[no-untyped-def]
    upload = SimpleUploadedFile("students.xlsx", file_bytes, content_type=XLSX_MIME)
    return client.post(
        "/api/v1/students/bulk-import",
        data={"file": upload, "dryRun": "true" if dry_run else "false"},
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


@pytest.mark.django_db
def test_dry_run_valid_file(client, admin_token_a, world_a):
    rows = [
        HEADERS,
        ["VB001", "Aarav", "Reddy", "Male", date(2014, 5, 1), date(2025, 6, 15),
         "Class 6", "A", "01", "Rajesh Reddy", "+919800000001", "Father", "yes"],
        ["VB002", "Ananya", "Iyer", "Female", date(2014, 7, 12), date(2025, 6, 15),
         "Class 6", "A", "02", "Suresh Iyer", "+919800000002", "Father", "y"],
    ]
    res = _post(client, admin_token_a, _make_xlsx(rows), dry_run=True)
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["ok"] is True
    assert body["validRows"] == 2
    assert body["errorCount"] == 0
    assert body["imported"] == 0  # dry run, nothing written
    assert Student.objects.all_tenants().filter(admission_number__in=["VB001", "VB002"]).count() == 0


@pytest.mark.django_db
def test_dry_run_invalid_rows_reports_each(client, admin_token_a):
    rows = [
        HEADERS,
        ["", "NoAdm", "X", "Male", "", date(2025, 6, 15), "Class 6", "A", "", "P", "+9198", "Father", ""],
        ["VB003", "", "X", "Male", "", date(2025, 6, 15), "Class 6", "A", "", "P", "+9198", "Father", ""],
        ["VB004", "BadGender", "X", "Pirate", "", date(2025, 6, 15), "Class 6", "A", "", "P", "+9198", "Father", ""],
        ["VB005", "BadSection", "X", "Male", "", date(2025, 6, 15), "Class 99", "Z", "", "P", "+9198", "Father", ""],
    ]
    res = _post(client, admin_token_a, _make_xlsx(rows), dry_run=True)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    errors_by_field = {e["field"] for e in body["errors"]}
    assert "admission_number" in errors_by_field
    assert "first_name" in errors_by_field
    assert "gender" in errors_by_field
    assert "class_name" in errors_by_field


@pytest.mark.django_db
def test_commit_imports_all_or_nothing(client, admin_token_a, world_a):
    rows = [
        HEADERS,
        ["VB100", "Aarav", "R", "Male", "", date(2025, 6, 15),
         "Class 6", "A", "01", "P1", "+9198000001", "Father", "y"],
        ["VB101", "Ananya", "I", "Female", "", date(2025, 6, 15),
         "Class 6", "B", "02", "P2", "+9198000002", "Father", "y"],
    ]
    res = _post(client, admin_token_a, _make_xlsx(rows), dry_run=False)
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["imported"] == 2
    assert Student.objects.all_tenants().filter(admission_number__in=["VB100", "VB101"]).count() == 2


@pytest.mark.django_db
def test_commit_with_errors_does_not_partially_import(client, admin_token_a, world_a):
    rows = [
        HEADERS,
        ["VB200", "Valid", "X", "Male", "", date(2025, 6, 15),
         "Class 6", "A", "", "P", "+9198", "Father", "y"],
        ["VB201", "BadGender", "X", "Alien", "", date(2025, 6, 15),
         "Class 6", "A", "", "P", "+9198", "Father", "y"],
    ]
    res = _post(client, admin_token_a, _make_xlsx(rows), dry_run=False)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["imported"] == 0
    # The valid row should NOT have been committed.
    assert Student.objects.all_tenants().filter(admission_number="VB200").count() == 0


@pytest.mark.django_db
def test_missing_required_column_rejected(client, admin_token_a):
    bad_headers = ["first_name", "gender", "admission_date", "class_name", "section_name"]
    rows = [bad_headers, ["Aarav", "Male", date(2025, 6, 15), "Class 6", "A"]]
    res = _post(client, admin_token_a, _make_xlsx(rows), dry_run=True)
    assert res.status_code == 422
    assert "admission_number" in res.json()["error"]["message"]


@pytest.mark.django_db
def test_duplicate_admission_within_file_rejected(client, admin_token_a, world_a):
    rows = [
        HEADERS,
        ["DUP", "A", "X", "Male", "", date(2025, 6, 15),
         "Class 6", "A", "", "P", "+9198", "Father", "y"],
        ["DUP", "B", "X", "Male", "", date(2025, 6, 15),
         "Class 6", "A", "", "P", "+9198", "Father", "y"],
    ]
    res = _post(client, admin_token_a, _make_xlsx(rows), dry_run=True)
    body = res.json()
    fields = [e["field"] for e in body["errors"]]
    assert fields.count("admission_number") >= 1


@pytest.mark.django_db
def test_admission_existing_in_db_rejected(client, admin_token_a, world_a):
    from apps.people.tests.factories import StudentFactory

    StudentFactory(school=world_a["school"], admission_number="EXISTS")
    rows = [
        HEADERS,
        ["EXISTS", "Dup", "X", "Male", "", date(2025, 6, 15),
         "Class 6", "A", "", "P", "+9198", "Father", "y"],
    ]
    res = _post(client, admin_token_a, _make_xlsx(rows), dry_run=True)
    body = res.json()
    assert any(e["field"] == "admission_number" for e in body["errors"])


@pytest.mark.django_db
def test_teacher_cannot_bulk_import(client, teacher_token_a):
    rows = [HEADERS, ["X", "Y", "", "Male", "", date(2025, 6, 15), "Class 6", "A", "", "P", "+9198", "Father", "y"]]
    res = _post(client, teacher_token_a, _make_xlsx(rows), dry_run=True)
    assert res.status_code == 403


@pytest.mark.django_db
def test_blank_rows_skipped(client, admin_token_a, world_a):
    rows = [
        HEADERS,
        ["", "", "", "", "", "", "", "", "", "", "", "", ""],
        ["VB300", "Aarav", "R", "Male", "", date(2025, 6, 15),
         "Class 6", "A", "", "P", "+9198", "Father", "y"],
    ]
    res = _post(client, admin_token_a, _make_xlsx(rows), dry_run=True)
    body = res.json()
    assert body["validRows"] == 1
    assert body["errorCount"] == 0


@pytest.mark.django_db
def test_rejects_out_of_range_admission_date(client, admin_token_a, world_a):
    """A typo'd year like 1016 must be caught, not imported."""
    rows = [
        HEADERS,
        ["VB777", "Old", "Date", "Male", date(2014, 5, 1), "26/06/1016",
         "Class 6", "A", "07", "Parent", "+919800000077", "Father", "yes"],
    ]
    res = _post(client, admin_token_a, _make_xlsx(rows), dry_run=True)
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["ok"] is False
    assert any(
        e["field"] == "admission_date" and "out of range" in e["message"]
        for e in body["errors"]
    ), body["errors"]
