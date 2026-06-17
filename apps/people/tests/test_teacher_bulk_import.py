"""Bulk import tests for teachers."""

from __future__ import annotations

from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from apps.people.models import Teacher

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

HEADERS = ["first_name", "last_name", "phone", "email", "qualification", "joining_date"]


def _make_xlsx(rows: list[list], *, sheet_name: str = "Teachers") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _post(client, token, file_bytes, *, dry_run=True):  # type: ignore[no-untyped-def]
    upload = SimpleUploadedFile("teachers.xlsx", file_bytes, content_type=XLSX_MIME)
    return client.post(
        "/api/v1/teachers/bulk-import",
        data={"file": upload, "dryRun": "true" if dry_run else "false"},
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


@pytest.mark.django_db
def test_dry_run_valid_file(client, admin_token_a, world_a):
    rows = [
        HEADERS,
        ["Meera", "Nair", "+919810000001", "meera@vb.school", "M.Sc B.Ed", "2025-06-01"],
        ["Arjun", "Rao", "+919810000002", "", "", ""],
    ]
    res = _post(client, admin_token_a, _make_xlsx(rows), dry_run=True)
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["ok"] is True
    assert body["validRows"] == 2
    assert body["errorCount"] == 0
    assert body["imported"] == 0
    assert Teacher.objects.all_tenants().filter(school=world_a["school"]).count() == 0


@pytest.mark.django_db
def test_commit_imports_all(client, admin_token_a, world_a):
    rows = [
        HEADERS,
        ["Meera", "Nair", "+919810000001", "meera@vb.school", "M.Sc", "2025-06-01"],
        ["Arjun", "Rao", "+919810000002", "", "", ""],
    ]
    res = _post(client, admin_token_a, _make_xlsx(rows), dry_run=False)
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["imported"] == 2
    assert (
        Teacher.objects.all_tenants()
        .filter(school=world_a["school"], phone__in=["+919810000001", "+919810000002"])
        .count()
        == 2
    )


@pytest.mark.django_db
def test_required_fields_and_duplicate_reported(client, admin_token_a, world_a):
    rows = [
        HEADERS,
        ["", "X", "+919810000010", "", "", ""],  # missing first_name
        ["NoPhone", "Y", "", "", "", ""],  # missing phone
        ["Dup", "A", "+919810000011", "", "", ""],
        ["Dup", "B", "+919810000011", "", "", ""],  # duplicate phone within file
    ]
    res = _post(client, admin_token_a, _make_xlsx(rows), dry_run=True)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    fields = [e["field"] for e in body["errors"]]
    assert "first_name" in fields
    assert "phone" in fields


@pytest.mark.django_db
def test_existing_phone_in_db_rejected(client, admin_token_a, world_a):
    from apps.people.tests.factories import TeacherFactory

    TeacherFactory(school=world_a["school"], phone="+919899999999")
    rows = [HEADERS, ["Dup", "Teacher", "+919899999999", "", "", ""]]
    res = _post(client, admin_token_a, _make_xlsx(rows), dry_run=True)
    body = res.json()
    assert any(e["field"] == "phone" for e in body["errors"])


@pytest.mark.django_db
def test_missing_required_column_rejected(client, admin_token_a, world_a):
    rows = [["last_name", "email"], ["Nair", "x@y.z"]]
    res = _post(client, admin_token_a, _make_xlsx(rows), dry_run=True)
    assert res.status_code == 422
    assert "first_name" in res.json()["error"]["message"]


@pytest.mark.django_db
def test_teacher_cannot_bulk_import(client, teacher_token_a):
    rows = [HEADERS, ["Meera", "Nair", "+919810000001", "", "", ""]]
    res = _post(client, teacher_token_a, _make_xlsx(rows), dry_run=True)
    assert res.status_code == 403
