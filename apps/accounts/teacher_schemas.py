"""Schemas for the teacher app (skooly-guru) auth endpoints.

The teacher login response shape is the contract from skooly-guru's
``src/lib/auth.tsx`` Teacher type — distinct from the admin AuthResponse.
"""

from __future__ import annotations

from pydantic import Field

from apps.core.schemas import CamelSchema


class TeacherLoginRequest(CamelSchema):
    phone: str = Field(min_length=8, max_length=20)
    password: str = Field(min_length=1, max_length=128)


class TeacherOut(CamelSchema):
    id: str
    name: str
    phone: str
    email: str
    subject: str
    school: str
    photo_url: str = ""  # serialized as photoUrl


class TeacherLoginResponse(CamelSchema):
    token: str
    teacher: TeacherOut


class UpdateProfileRequest(CamelSchema):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(max_length=254)


class ChangePasswordRequest(CamelSchema):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class TeacherOtpSendRequest(CamelSchema):
    phone: str = Field(min_length=8, max_length=20)


class TeacherOtpVerifyRequest(CamelSchema):
    phone: str = Field(min_length=8, max_length=20)
    otp: str = Field(min_length=4, max_length=8)
    new_password: str = Field(min_length=6, max_length=128)


class TeacherMessageResponse(CamelSchema):
    message: str
