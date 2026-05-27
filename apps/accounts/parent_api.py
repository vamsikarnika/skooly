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
    ParentMeOut,
    RefreshResponse,
    SendOtpRequest,
    SendOtpResponse,
    SuccessResponse,
    VerifyOtpRequest,
    VerifyOtpResponse,
)

router = Router(tags=["parent-auth"], auth=parent_jwt_auth, by_alias=True)
profile_router = Router(tags=["parent-profile"], auth=parent_jwt_auth, by_alias=True)


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
