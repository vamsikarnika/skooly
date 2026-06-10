"""Custom exceptions + a Ninja exception handler that emits the
``{ error: { code, message, details } }`` shape from CLAUDE.md."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpRequest
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, HttpError, ValidationError


class APIError(Exception):
    """Base class for application-level errors that should be returned to the API."""

    status_code: int = 400
    code: str = "BAD_REQUEST"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFound(APIError):
    status_code = 404
    code = "NOT_FOUND"


class Forbidden(APIError):
    status_code = 403
    code = "FORBIDDEN"


class Unauthorized(APIError):
    status_code = 401
    code = "UNAUTHORIZED"


class Conflict(APIError):
    status_code = 409
    code = "CONFLICT"


class ValidationFailed(APIError):
    status_code = 422
    code = "VALIDATION_ERROR"


class InvalidOTP(APIError):
    status_code = 400
    code = "INVALID_OTP"


class InvalidCredentials(APIError):
    """Generic auth failure — wrong phone/password combo. Deliberately does
    NOT distinguish 'unknown phone' from 'wrong password' to avoid leaking
    which half failed."""

    status_code = 400
    code = "INVALID_CREDENTIALS"


def _error_response(
    request: HttpRequest,
    api: NinjaAPI,
    *,
    code: str,
    message: str,
    status: int,
    details: dict[str, Any] | None = None,
) -> Any:
    return api.create_response(
        request,
        {"error": {"code": code, "message": message, "details": details or {}}},
        status=status,
    )


def register_exception_handlers(api: NinjaAPI) -> None:
    @api.exception_handler(APIError)
    def _handle_api_error(request: HttpRequest, exc: APIError) -> Any:
        return _error_response(
            request, api, code=exc.code, message=exc.message, status=exc.status_code, details=exc.details
        )

    @api.exception_handler(ValidationError)
    def _handle_pydantic_validation(request: HttpRequest, exc: ValidationError) -> Any:
        return _error_response(
            request,
            api,
            code="VALIDATION_ERROR",
            message="Request validation failed.",
            status=422,
            details={"errors": exc.errors},
        )

    @api.exception_handler(DjangoValidationError)
    def _handle_django_validation(request: HttpRequest, exc: DjangoValidationError) -> Any:
        return _error_response(
            request,
            api,
            code="VALIDATION_ERROR",
            message="Validation failed.",
            status=422,
            details={"errors": exc.message_dict if hasattr(exc, "message_dict") else exc.messages},
        )

    @api.exception_handler(AuthenticationError)
    def _handle_auth(request: HttpRequest, exc: AuthenticationError) -> Any:
        return _error_response(
            request, api, code="UNAUTHORIZED", message="Authentication required.", status=401
        )

    @api.exception_handler(HttpError)
    def _handle_http(request: HttpRequest, exc: HttpError) -> Any:
        code_map = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
        }
        return _error_response(
            request,
            api,
            code=code_map.get(exc.status_code, "ERROR"),
            message=str(getattr(exc, "message", exc)),
            status=exc.status_code,
        )
