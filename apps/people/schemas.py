"""Pydantic schemas for student/teacher endpoints. CamelCase boundary."""

from __future__ import annotations

from datetime import date

from apps.core.schemas import CamelSchema, Paginated


class ParentContactOut(CamelSchema):
    name: str
    relation: str
    phone: str
    email: str
    whatsapp: bool


class StudentOut(CamelSchema):
    id: int
    admission_number: str
    first_name: str
    last_name: str
    full_name: str
    dob: date | None
    gender: str
    blood_group: str
    address: str
    photo_url: str
    admission_date: date
    status: str

    # Denormalised from the active enrollment, easier for UI consumption.
    class_name: str | None = None
    section_name: str | None = None
    roll_number: str = ""

    parents: list[ParentContactOut] = []


class StudentListOut(Paginated[StudentOut]):
    pass


class TeacherOut(CamelSchema):
    id: int
    first_name: str
    last_name: str
    full_name: str
    phone: str
    email: str
    photo_url: str
    qualification: str
    joining_date: date | None
    status: str


class TeacherListOut(Paginated[TeacherOut]):
    pass


class BulkImportRowError(CamelSchema):
    row: int
    field: str
    message: str


class BulkImportResponse(CamelSchema):
    ok: bool
    dry_run: bool
    row_count: int
    valid_rows: int
    error_count: int
    errors: list[BulkImportRowError]
    imported: int
