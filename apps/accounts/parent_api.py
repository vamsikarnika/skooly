"""Parent app (skooly-parent) auth + profile router — mounted on parent_api.

Auth router lives at /api/v1/parent/auth/…; the profile router is mounted at /
so GET /api/v1/parent/parent/me has a clean URL separate from auth.
"""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router

from apps.accounts import parent_services
from apps.accounts.parent_auth import parent_jwt_auth
from apps.accounts.parent_schemas import (
    ChangePasswordRequest,
    ParentMeOut,
    PasswordLoginRequest,
    PasswordLoginResponse,
    RefreshResponse,
    SendOtpRequest,
    SendOtpResponse,
    SuccessResponse,
    UpdateProfileRequest,
    VerifyOtpRequest,
    VerifyOtpResponse,
)

router = Router(tags=["parent-auth"], auth=parent_jwt_auth, by_alias=True)
profile_router = Router(tags=["parent-profile"], auth=parent_jwt_auth, by_alias=True)


@router.post("/login", response=PasswordLoginResponse, auth=None)
def login(request: HttpRequest, payload: PasswordLoginRequest) -> dict:
    """Phone + password login — the active parent auth path while real OTP
    delivery is deferred (ClickUp 86d39qahj). The OTP endpoints below are
    intentionally kept in place for easy revival."""
    return parent_services.parent_password_login(payload.phone, payload.password)


# ---- Dormant OTP endpoints ------------------------------------------------
# Kept wired so reviving real SMS-based OTP later is a frontend-only change.
# Not currently called by the parent app.

@router.post("/send-otp", response=SendOtpResponse, auth=None)
def send_otp(request: HttpRequest, payload: SendOtpRequest) -> dict:
    parent_services.send_parent_otp(payload.phone)
    return {"success": True, "expires_in": 60}


@router.post("/verify-otp", response=VerifyOtpResponse, auth=None)
def verify_otp(request: HttpRequest, payload: VerifyOtpRequest) -> dict:
    return parent_services.verify_parent_otp(payload.phone, payload.otp)


@router.post("/refresh", response=RefreshResponse)
def refresh(request: HttpRequest) -> dict:
    return parent_services.parent_refresh(user=request.auth)  # type: ignore[attr-defined]


@router.post("/logout", response=SuccessResponse, auth=None)
def logout(request: HttpRequest) -> dict:
    # Stateless JWT — the client just drops the token, so this needs no auth.
    # (Requiring auth here caused a 401→unauthorized→logout loop on a stale
    # token.) A real server-side deny-list lands with Module 5.
    return {"success": True}


@profile_router.get("/parent/me", response=ParentMeOut)
def parent_me(request: HttpRequest) -> dict:
    return parent_services.get_parent_me(user=request.auth)  # type: ignore[attr-defined]


@profile_router.patch("/parent/me", response=ParentMeOut)
def update_parent_me(request: HttpRequest, payload: UpdateProfileRequest) -> dict:
    """Update the parent's display name and/or email. Phone is read-only —
    it's the login credential. Returns the full refreshed profile so the
    client can drop it straight into local state."""
    return parent_services.update_parent_profile(
        user=request.auth,  # type: ignore[attr-defined]
        name=payload.name,
        email=payload.email,
    )


@profile_router.patch("/parent/me/password", response=SuccessResponse)
def change_password(request: HttpRequest, payload: ChangePasswordRequest) -> dict:
    """Change the authenticated parent's password. The existing session token
    keeps working (we don't rotate it), so the client just stays signed in
    with the new password live for the next login."""
    parent_services.change_parent_password(
        user=request.auth,  # type: ignore[attr-defined]
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    return {"success": True}
