"""Auth endpoints — signup, login, refresh, password reset, me."""

from __future__ import annotations

import hmac
from typing import Any

from django.conf import settings
from django.http import HttpRequest
from ninja import Router

from apps.accounts import services
from apps.accounts.auth import jwt_auth
from apps.accounts.schemas import (
    AuthResponse,
    ForgotPasswordRequest,
    GenericMessageResponse,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    ResetPasswordRequest,
    SchoolOut,
    SignupRequest,
    TokenPair,
    UserOut,
    VerifyOtpRequest,
    VerifyOtpResponse,
)
from apps.core.exceptions import Forbidden

router = Router(tags=["auth"], by_alias=True)


def _build_auth_response(user: Any, school: Any, tokens: dict[str, str]) -> AuthResponse:
    return AuthResponse(
        user=UserOut.from_orm(user),
        school=SchoolOut.from_orm(school) if school else None,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
    )


def _require_signup_allowed(request: HttpRequest) -> None:
    """Gate public signup behind SIGNUP_SECRET. When the secret is set (prod),
    only requests carrying a matching X-Signup-Token header may create a school;
    when unset (dev/test/local), signup is open. Constant-time compare avoids
    leaking the secret via timing."""
    secret = settings.SIGNUP_SECRET
    if not secret:
        return
    provided = request.headers.get("X-Signup-Token", "")
    if not hmac.compare_digest(provided, secret):
        raise Forbidden("Public signup is disabled.")


@router.post("/signup", response=AuthResponse)
def signup(request: HttpRequest, payload: SignupRequest) -> AuthResponse:
    _require_signup_allowed(request)
    user, school, tokens = services.signup_school(
        school_name=payload.school_name,
        board=payload.board,
        address=payload.address,
        academic_year_label=payload.academic_year_label,
        academic_year_start=payload.academic_year_start,
        academic_year_end=payload.academic_year_end,
        admin_first_name=payload.admin_first_name,
        admin_last_name=payload.admin_last_name,
        admin_phone=payload.admin_phone,
        admin_email=payload.admin_email,
        admin_password=payload.admin_password,
    )
    return _build_auth_response(user, school, tokens)


@router.post("/login", response=AuthResponse)
def login(request: HttpRequest, payload: LoginRequest) -> AuthResponse:
    user, school, tokens = services.login(phone=payload.phone, password=payload.password)
    return _build_auth_response(user, school, tokens)


@router.post("/refresh", response=TokenPair)
def refresh(request: HttpRequest, payload: RefreshRequest) -> TokenPair:
    tokens = services.refresh_tokens(payload.refresh_token)
    return TokenPair(access_token=tokens["access_token"], refresh_token=tokens["refresh_token"])


@router.post("/forgot-password", response=GenericMessageResponse)
def forgot_password(request: HttpRequest, payload: ForgotPasswordRequest) -> GenericMessageResponse:
    services.request_password_reset_otp(payload.phone)
    return GenericMessageResponse(message="If an account exists, an OTP has been sent.")


@router.post("/verify-otp", response=VerifyOtpResponse)
def verify_otp(request: HttpRequest, payload: VerifyOtpRequest) -> VerifyOtpResponse:
    token, expires_at = services.verify_password_reset_otp(payload.phone, payload.otp)
    return VerifyOtpResponse(reset_token=token, expires_at=expires_at)


@router.post("/reset-password", response=GenericMessageResponse)
def reset_password(request: HttpRequest, payload: ResetPasswordRequest) -> GenericMessageResponse:
    services.reset_password(payload.reset_token, payload.new_password)
    return GenericMessageResponse(message="Password updated.")


@router.get("/me", response=MeResponse, auth=jwt_auth)
def me(request: HttpRequest) -> MeResponse:
    user = request.auth  # type: ignore[attr-defined]
    school = user.school
    return MeResponse(
        user=UserOut.from_orm(user),
        school=SchoolOut.from_orm(school) if school else None,
        permissions=services.get_permissions(user),
    )
