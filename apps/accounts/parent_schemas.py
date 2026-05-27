"""Pydantic schemas for the parent app (skooly-parent) auth + bootstrap."""

from __future__ import annotations

from apps.core.schemas import CamelSchema


class ChildOut(CamelSchema):
    id: int
    name: str
    # `class_` serializes to the JSON key "class" via the camel alias generator.
    class_: str
    section: str
    roll_no: int | None = None
    admission_no: str
    school: str
    photo_initials: str
    photo_color: str


class ParentOut(CamelSchema):
    id: int
    name: str
    phone: str
    email: str


class ParentMeOut(ParentOut):
    children: list[ChildOut]


class SendOtpRequest(CamelSchema):
    phone: str


class SendOtpResponse(CamelSchema):
    success: bool
    expires_in: int


class VerifyOtpRequest(CamelSchema):
    phone: str
    otp: str


class VerifyOtpResponse(CamelSchema):
    token: str
    parent: ParentOut
    children: list[ChildOut]


class RefreshResponse(CamelSchema):
    token: str


class SuccessResponse(CamelSchema):
    success: bool
