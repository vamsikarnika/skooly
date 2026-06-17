"""Bulk import tests for classes & sections."""

from __future__ import annotations

from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from apps.academics.models import Class, Section

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

HEADERS = ["class_name", "section_name", "room_number"]


def _make_xlsx(rows: list[list], *, sheet_name: str = "Classes & Sections") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _post(client, token, file_bytes, *, dry_run=True):  # type: ignore[no-untyped-def]
    upload = SimpleUploadedFile("classes.xlsx", file_bytes, content_type=XLSX_MIME)
    return client.post(
        "/api/v1/classes/bulk-import",
        data={"file": upload, "dryRun": "true" if dry_run else "false"},
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


@pytest.mark.django_db
def test_dry_run_valid_file(client, admin_token_a, world_a):
    rows = [
        HEADERS,
        ["Class 7", "A", "201"],
        ["Class 7", "B", "202"],
    ]
    res = _post(client, admin_token_a, _make_xlsx(rows), dry_run=True)
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["ok"] is True
    assert body["validRows"] == 2
    assert body["imported"] == 0
    assert not Section.objects.all_tenants().filter(
        school=world_a["school"], class_obj__name="Class 7"
    ).exists()


@pytest.mark.django_db
def test_commit_creates_class_and_sections(client, admin_token_a, world_a):
    rows = [
        HEADERS,
        ["Class 7", "A", "201"],
        ["Class 7", "B", "202"],
    ]
    res = _post(client, admin_token_a, _make_xlsx(rows), dry_run=False)
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["imported"] == 2
    # One class created (shared across both rows), two sections.
    assert Class.objects.all_tenants().filter(
        school=world_a["school"], name="Class 7"
    ).count() == 1
    assert Section.objects.all_tenants().filter(
        school=world_a["school"], class_obj__name="Class 7"
    ).count() == 2


@pytest.mark.django_db
def test_duplicate_within_file_and_existing_section_reported(client, admin_token_a, world_a):
    rows = [
        HEADERS,
        ["Class 8", "A", ""],
        ["Class 8", "A", ""],  # duplicate within file
        ["Class 6", "A", ""],  # already exists in world_a
    ]
    res = _post(client, admin_token_a, _make_xlsx(rows), dry_run=True)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert sum(1 for e in body["errors"] if e["field"] == "section_name") >= 2


@pytest.mark.django_db
def test_required_fields_reported(client, admin_token_a, world_a):
    rows = [HEADERS, ["", "A", ""], ["Class 9", "", ""]]
    res = _post(client, admin_token_a, _make_xlsx(rows), dry_run=True)
    body = res.json()
    fields = {e["field"] for e in body["errors"]}
    assert "class_name" in fields
    assert "section_name" in fields


@pytest.mark.django_db
def test_missing_required_column_rejected(client, admin_token_a, world_a):
    rows = [["room_number"], ["101"]]
    res = _post(client, admin_token_a, _make_xlsx(rows), dry_run=True)
    assert res.status_code == 422
    assert "class_name" in res.json()["error"]["message"]


@pytest.mark.django_db
def test_teacher_cannot_bulk_import(client, teacher_token_a):
    rows = [HEADERS, ["Class 7", "A", ""]]
    res = _post(client, teacher_token_a, _make_xlsx(rows), dry_run=True)
    assert res.status_code == 403
