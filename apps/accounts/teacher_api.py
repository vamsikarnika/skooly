"""Teacher app (skooly-guru) auth router — mounted on teacher_api at
/api/v1/teacher/auth/."""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router

from apps.accounts import services
from apps.accounts.teacher_auth import teacher_jwt_auth
from apps.accounts.teacher_schemas import TeacherLoginRequest, TeacherLoginResponse

# Default-locked to teachers; public endpoints (login) override with auth=None.
router = Router(tags=["teacher-auth"], auth=teacher_jwt_auth, by_alias=True)


@router.post("/login", response=TeacherLoginResponse, auth=None)
def login(request: HttpRequest, payload: TeacherLoginRequest) -> dict:
    _user, result = services.teacher_login(phone=payload.phone, password=payload.password)
    return result
