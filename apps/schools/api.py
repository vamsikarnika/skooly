"""School + academic year endpoints. All require auth (admin role for writes)."""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router

from apps.accounts.auth import jwt_auth
from apps.accounts.models import Role
from apps.core.exceptions import Forbidden, NotFound
from apps.schools import services
from apps.schools.models import School
from apps.schools.schemas import (
    AcademicYearCreateRequest,
    AcademicYearOut,
    AcademicYearUpdateRequest,
    SchoolDetailOut,
    SchoolUpdateRequest,
)

router = Router(tags=["schools"], auth=jwt_auth, by_alias=True)


def _require_admin(request: HttpRequest) -> None:
    user = request.auth  # type: ignore[attr-defined]
    if user.role != Role.ADMIN:
        raise Forbidden("Admin role required.")


def _current_school(request: HttpRequest) -> School:
    user = request.auth  # type: ignore[attr-defined]
    school = user.school
    if school is None:
        raise NotFound("Current user has no school.")
    return school


@router.get("/current", response=SchoolDetailOut)
def get_current_school(request: HttpRequest) -> SchoolDetailOut:
    return SchoolDetailOut.from_orm(_current_school(request))


@router.patch("/current", response=SchoolDetailOut)
def update_current_school(request: HttpRequest, payload: SchoolUpdateRequest) -> SchoolDetailOut:
    _require_admin(request)
    school = _current_school(request)
    school = services.update_school(school, fields=payload.model_dump(by_alias=False, exclude_unset=True))
    return SchoolDetailOut.from_orm(school)


@router.get("/academic-years", response=list[AcademicYearOut])
def list_years(request: HttpRequest) -> list[AcademicYearOut]:
    school = _current_school(request)
    return [AcademicYearOut.from_orm(y) for y in services.list_academic_years(school)]


@router.post("/academic-years", response=AcademicYearOut)
def create_year(request: HttpRequest, payload: AcademicYearCreateRequest) -> AcademicYearOut:
    _require_admin(request)
    school = _current_school(request)
    year = services.create_academic_year(
        school,
        label=payload.label,
        start_date=payload.start_date,
        end_date=payload.end_date,
        is_current=payload.is_current,
    )
    return AcademicYearOut.from_orm(year)


@router.patch("/academic-years/{year_id}", response=AcademicYearOut)
def update_year(request: HttpRequest, year_id: int, payload: AcademicYearUpdateRequest) -> AcademicYearOut:
    _require_admin(request)
    school = _current_school(request)
    year = services.update_academic_year(
        school, year_id, **payload.model_dump(by_alias=False, exclude_unset=True)
    )
    return AcademicYearOut.from_orm(year)
