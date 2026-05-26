"""Teacher app (skooly-guru) auth router — mounted on teacher_api at
/api/v1/teacher/auth/.

A second router (profile_router) is mounted at / so that
PATCH /api/v1/teacher/profile has a clean URL separate from auth.
"""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router

from apps.accounts import services
from apps.accounts.teacher_auth import teacher_jwt_auth
from apps.accounts.teacher_schemas import (
    ChangePasswordRequest,
    TeacherLoginRequest,
    TeacherLoginResponse,
    TeacherMessageResponse,
    TeacherOtpSendRequest,
    TeacherOtpVerifyRequest,
    TeacherOut,
    UpdateProfileRequest,
)

# Default-locked to teachers; public endpoints (login, otp) override with auth=None.
router = Router(tags=["teacher-auth"], auth=teacher_jwt_auth, by_alias=True)

# Mounted at "/" so PATCH /api/v1/teacher/profile is a clean top-level URL.
profile_router = Router(tags=["teacher-profile"], auth=teacher_jwt_auth, by_alias=True)


# ---------------------------------------------------------------------------
# Auth router  (/api/v1/teacher/auth/…)
# ---------------------------------------------------------------------------

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


@router.post("/refresh", response=TeacherLoginResponse)
def refresh(request: HttpRequest) -> dict:
    """Re-issue a fresh access token for the currently authenticated teacher.

    The client should call this on every app open so the teacher stays logged in
    without re-entering credentials. The existing token must still be valid at
    the time of the call (i.e., not yet expired).
    """
    return services.teacher_refresh(user=request.auth)  # type: ignore[attr-defined]


@router.post("/change-password", response=TeacherMessageResponse)
def change_password(request: HttpRequest, payload: ChangePasswordRequest) -> dict:
    """Verify the current password and set a new one.

    Returns 401 when the current password is wrong (credentials problem, not a
    payload validation error).
    """
    services.change_teacher_password(
        user=request.auth,  # type: ignore[attr-defined]
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    return {"message": "Password changed successfully"}


# ---------------------------------------------------------------------------
# Profile router  (/api/v1/teacher/…)
# ---------------------------------------------------------------------------

@profile_router.patch("/profile", response=TeacherOut)
def update_profile(request: HttpRequest, payload: UpdateProfileRequest) -> dict:
    """Update the teacher's display name and email.

    Phone is read-only — it is the login credential and can only be changed
    by a school admin.  Returns the updated teacher object so the client can
    refresh its local cache in one round-trip.
    """
    return services.update_teacher_profile(
        user=request.auth,  # type: ignore[attr-defined]
        name=payload.name,
        email=payload.email,
    )
