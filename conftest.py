"""Shared fixtures for Module 2 tests."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.academics.tests.factories import ClassFactory, SectionFactory
from apps.accounts.models import Role
from apps.accounts.tests.factories import UserFactory
from apps.schools.tests.factories import AcademicYearFactory, SchoolFactory


@pytest.fixture
def client() -> Client:
    return Client()


def _make_school_world(school_name: str, admin_phone: str, teacher_phone: str):  # type: ignore[no-untyped-def]
    school = SchoolFactory(name=school_name)
    year = AcademicYearFactory(school=school, label="2025-26", is_current=True)
    cls = ClassFactory(school=school, academic_year=year, name="Class 6", display_order=6)
    section_a = SectionFactory(school=school, class_obj=cls, name="A")
    section_b = SectionFactory(school=school, class_obj=cls, name="B")
    admin = UserFactory(school=school, phone=admin_phone, role=Role.ADMIN)
    teacher_user = UserFactory(school=school, phone=teacher_phone, role=Role.TEACHER)
    return {
        "school": school,
        "year": year,
        "class": cls,
        "section_a": section_a,
        "section_b": section_b,
        "admin": admin,
        "teacher_user": teacher_user,
    }


@pytest.fixture
def world_a(db) -> dict:
    return _make_school_world("School A", "+911111111101", "+911111111102")


@pytest.fixture
def world_b(db) -> dict:
    return _make_school_world("School B", "+912222222201", "+912222222202")


def auth_token(client: Client, user) -> str:  # type: ignore[no-untyped-def]
    res = client.post(
        "/api/v1/auth/login",
        data={"phone": user.phone, "password": "testpass123"},
        content_type="application/json",
    )
    assert res.status_code == 200, res.content
    return res.json()["accessToken"]


@pytest.fixture
def admin_token_a(client, world_a) -> str:
    return auth_token(client, world_a["admin"])


@pytest.fixture
def teacher_token_a(client, world_a) -> str:
    return auth_token(client, world_a["teacher_user"])


@pytest.fixture
def admin_token_b(client, world_b) -> str:
    return auth_token(client, world_b["admin"])
