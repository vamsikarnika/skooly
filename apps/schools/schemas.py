from __future__ import annotations

from datetime import date

from pydantic import Field

from apps.core.schemas import CamelSchema


class AcademicYearOut(CamelSchema):
    id: int
    label: str
    start_date: date
    end_date: date
    is_current: bool


class SchoolDetailOut(CamelSchema):
    id: int
    name: str
    board: str
    address: str
    logo_url: str
    whatsapp_number: str
    primary_color: str
    current_academic_year: AcademicYearOut | None


class SchoolUpdateRequest(CamelSchema):
    name: str | None = Field(default=None, max_length=200)
    board: str | None = None
    address: str | None = None
    logo_url: str | None = None
    whatsapp_number: str | None = None
    primary_color: str | None = None


class AcademicYearCreateRequest(CamelSchema):
    label: str
    start_date: date
    end_date: date
    is_current: bool = False


class AcademicYearUpdateRequest(CamelSchema):
    label: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None
