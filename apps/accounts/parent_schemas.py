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


class PasswordLoginRequest(CamelSchema):
    """Phone + password login. Used in place of OTP until real SMS delivery
    ships (tracked in ClickUp 86d39qahj)."""

    phone: str
    password: str


# Identical shape to VerifyOtpResponse so the frontend's auth context can
# reuse the same VerifyOtpResponse type and react no differently. Kept as a
# separate symbol for documentation + so the OpenAPI schema makes the
# alternate flow explicit.
class PasswordLoginResponse(VerifyOtpResponse):
    pass


class RefreshResponse(CamelSchema):
    token: str


class SuccessResponse(CamelSchema):
    success: bool


class UpdateProfileRequest(CamelSchema):
    """Editable parent profile fields. Phone is deliberately not here — it's
    the login credential and can only be changed by a school admin. Either
    field may be omitted (None) to leave it unchanged; ``email=""`` clears it."""

    name: str | None = None
    email: str | None = None
