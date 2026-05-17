"""Write-side schemas for students & teachers."""

from __future__ import annotations

from datetime import date

from pydantic import Field, field_validator

from apps.core.schemas import CamelSchema, is_valid_in_phone


class ParentInput(CamelSchema):
    name: str = ""
    relation: str = ""
    phone: str = ""
    email: str = ""
    whatsapp: bool = True

    @field_validator("phone")
    @classmethod
    def _phone_format(cls, v: str) -> str:
        if v and not is_valid_in_phone(v):
            raise ValueError("must be +91 followed by 10 digits, no spaces")
        return v


class StudentCreateRequest(CamelSchema):
    admission_number: str | None = Field(default=None, max_length=40)  # auto if blank
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = ""
    dob: date | None = None
    gender: str
    blood_group: str = ""
    address: str = ""
    photo_url: str = ""
    admission_date: date
    section_id: int  # placement at creation time
    roll_number: str = ""
    previous_school: str = ""
    primary_whatsapp_phone: str = ""
    emergency_contact_name: str = ""
    emergency_contact_phone: str = ""
    parents: list[ParentInput] = Field(default_factory=list, max_length=2)

    @field_validator("primary_whatsapp_phone", "emergency_contact_phone")
    @classmethod
    def _optional_phone(cls, v: str) -> str:
        if v and not is_valid_in_phone(v):
            raise ValueError("must be +91 followed by 10 digits, no spaces")
        return v


class StudentUpdateRequest(CamelSchema):
    admission_number: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    dob: date | None = None
    gender: str | None = None
    blood_group: str | None = None
    address: str | None = None
    photo_url: str | None = None
    admission_date: date | None = None
    status: str | None = None
    previous_school: str | None = None
    primary_whatsapp_phone: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    parents: list[ParentInput] | None = None


class StudentTransferRequest(CamelSchema):
    section_id: int
    roll_number: str = ""
    effective_date: date | None = None


class TeacherCreateRequest(CamelSchema):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = ""
    phone: str
    email: str = ""
    qualification: str = ""
    joining_date: date | None = None
    photo_url: str = ""

    @field_validator("phone")
    @classmethod
    def _phone_format(cls, v: str) -> str:
        if not is_valid_in_phone(v):
            raise ValueError("must be +91 followed by 10 digits, no spaces")
        return v


class TeacherUpdateRequest(CamelSchema):
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    email: str | None = None
    qualification: str | None = None
    joining_date: date | None = None
    photo_url: str | None = None
    status: str | None = None

    @field_validator("phone")
    @classmethod
    def _phone_format(cls, v: str | None) -> str | None:
        if v and not is_valid_in_phone(v):
            raise ValueError("must be +91 followed by 10 digits, no spaces")
        return v
