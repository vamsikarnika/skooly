"""Teacher app (skooly-guru) auth router — mounted on teacher_api at
/api/v1/teacher/auth/."""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router

from apps.accounts import services
from apps.accounts.teacher_auth import teacher_jwt_auth
from apps.accounts.teacher_schemas import (
    TeacherLoginRequest,
    TeacherLoginResponse,
    TeacherMessageResponse,
    TeacherOtpSendRequest,
    TeacherOtpVerifyRequest,
)

# Default-locked to teachers; public endpoints (login, otp) override with auth=None.
router = Router(tags=["teacher-auth"], auth=teacher_jwt_auth, by_alias=True)


@router.post("/login", response=TeacherLoginResponse, auth=None)
def login(request: HttpRequest, payload: TeacherLoginRequest) -> dict:
    _user, result = services.teacher_login(phone=payload.phone, password=payload.password)
    return result


@router.post("/otp/send", response=TeacherMessageResponse, auth=None)
def otp_send(request: HttpRequest, payload: TeacherOtpSendRequest) -> dict:
    services.send_teacher_otp(payload.phone)
    return {"message": "OTP sent"}


@router.post("/otp/verify", response=TeacherMessageResponse, auth=None)
def otp_verify(request: HttpRequest, payload: TeacherOtpVerifyRequest) -> dict:
    services.activate_or_reset_teacher(payload.phone, payload.otp, payload.new_password)
    return {"message": "Password reset successful"}
