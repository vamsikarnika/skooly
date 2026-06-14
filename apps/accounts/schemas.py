"""Pydantic schemas for auth endpoints. CamelCase at the API boundary."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from apps.core.schemas import CamelSchema

# ---------- Outputs ----------

class UserOut(CamelSchema):
    id: int
    school_id: int | None
    first_name: str
    last_name: str
    phone: str
    email: str
    role: str
    is_active: bool
    last_login_at: datetime | None


class SchoolOut(CamelSchema):
    id: int
    name: str
    board: str
    address: str
    logo_url: str
    whatsapp_number: str
    primary_color: str
    current_academic_year_id: int | None


class TokenPair(CamelSchema):
    access_token: str
    refresh_token: str


class AuthResponse(CamelSchema):
    user: UserOut
    school: SchoolOut | None
    access_token: str
    refresh_token: str


class MeResponse(CamelSchema):
    user: UserOut
    school: SchoolOut | None
    permissions: list[str] = Field(default_factory=list)


# ---------- Inputs ----------

class SignupRequest(CamelSchema):
    school_name: str = Field(min_length=2, max_length=200)
    board: str = Field(default="AP_STATE")
    address: str = ""
    academic_year_label: str
    academic_year_start: date
    academic_year_end: date
    admin_first_name: str = Field(min_length=1, max_length=100)
    admin_last_name: str = ""
    admin_phone: str = Field(min_length=8, max_length=20)
    admin_email: str = ""
    admin_password: str = Field(min_length=8, max_length=128)


class LoginRequest(CamelSchema):
    phone: str = Field(min_length=8, max_length=20)
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(CamelSchema):
    refresh_token: str


class ForgotPasswordRequest(CamelSchema):
    phone: str = Field(min_length=8, max_length=20)


class VerifyOtpRequest(CamelSchema):
    phone: str
    otp: str = Field(min_length=4, max_length=8)


class VerifyOtpResponse(CamelSchema):
    reset_token: str
    expires_at: datetime


class ResetPasswordRequest(CamelSchema):
    reset_token: str
    new_password: str = Field(min_length=8, max_length=128)


class GenericMessageResponse(CamelSchema):
    success: bool = True
    message: str


# ---------- Admin user management ----------


class AdminUserOut(CamelSchema):
    id: int
    first_name: str
    last_name: str
    full_name: str
    phone: str
    email: str
    is_active: bool
    last_login_at: datetime | None = None
    is_current: bool = False


class CreateAdminRequest(CamelSchema):
    first_name: str
    last_name: str = ""
    phone: str
    email: str = ""


class CreateAdminResult(CamelSchema):
    user: AdminUserOut
    # Plaintext one-time password to share with the new admin (no email infra).
    generated_password: str


class UpdateAdminRequest(CamelSchema):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    is_active: bool | None = None
