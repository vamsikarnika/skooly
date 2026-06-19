"""Write services for students and teachers. Tenant-safe; soft-deletes;
attendance & test scores follow the student naturally since they're FK'd
to ``Student``, not to a section.
"""

from __future__ import annotations

import secrets
from datetime import date
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.academics.models import Section, StudentEnrollment
from apps.accounts.models import Role, User
from apps.accounts.services import normalize_in_phone
from apps.core.audit import log_action
from apps.core.exceptions import Conflict, ValidationFailed
from apps.core.helpers import get_in_tenant
from apps.people.models import (
    Gender,
    Parent,
    ParentStudent,
    Relation,
    Student,
    StudentStatus,
    Teacher,
    TeacherStatus,
)
from apps.schools.models import School

# Ambiguous characters (0/O, 1/l/I) are left out so a handed-out password is
# easy to read off a screen and type on a phone.
_TEMP_PW_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def _generate_temp_password(length: int = 10) -> str:
    return "".join(secrets.choice(_TEMP_PW_ALPHABET) for _ in range(length))

# ----- Students --------------------------------------------------------------

def _ensure_unique_admission(school: School, admission_number: str, *, exclude_id: int | None = None) -> None:
    qs = Student.objects.all_tenants().filter(school=school, admission_number=admission_number)
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    if qs.exists():
        raise Conflict(
            "A student with that admission number already exists.",
            {"admissionNumber": ["duplicate"]},
        )


def _auto_admission_number(school: School, section: Section) -> str:
    """Generate <SCHOOL_PREFIX><yyyy><classOrder><sectionId><seq> matching
    the seed pattern."""
    prefix = "".join(c for c in school.name[:2].upper() if c.isalpha()) or "SK"
    today = timezone.now().date()
    year = today.year if today.month >= 6 else today.year - 1
    base = f"{prefix}{year}{section.class_obj.display_order:02d}{section.id:02d}"
    seq = Student.objects.all_tenants().filter(school=school, admission_number__startswith=base).count() + 1
    return f"{base}{seq:03d}"


def _apply_parents(student: Student, parents: list[dict[str, Any]]) -> None:
    """We use flat parent1_/parent2_ fields in DB to keep query semantics simple."""
    fields: list[str] = []
    primary = parents[0] if parents else {}
    secondary = parents[1] if len(parents) > 1 else {}

    for prefix, src in (("parent1", primary), ("parent2", secondary)):
        for key in ("name", "relation", "phone", "email"):
            field = f"{prefix}_{key}"
            setattr(student, field, src.get(key, ""))
            fields.append(field)
        wa_field = f"{prefix}_whatsapp"
        setattr(student, wa_field, bool(src.get("whatsapp", False)))
        fields.append(wa_field)
    student.save(update_fields=fields)


@transaction.atomic
def create_student(
    *,
    school: School,
    actor_id: int,
    data: dict[str, Any],
) -> Student:
    if data["gender"] not in Gender.values:
        raise ValidationFailed("Invalid gender.", {"gender": ["unsupported value"]})

    section = get_in_tenant(Section, school, pk=data["section_id"])
    year = section.class_obj.academic_year

    admission_number = data.get("admission_number") or _auto_admission_number(school, section)
    _ensure_unique_admission(school, admission_number)

    student = Student.objects.create(
        school=school,
        admission_number=admission_number,
        first_name=data["first_name"],
        last_name=data.get("last_name", ""),
        dob=data.get("dob"),
        gender=data["gender"],
        blood_group=data.get("blood_group", ""),
        address=data.get("address", ""),
        photo_url=data.get("photo_url", ""),
        admission_date=data["admission_date"],
        previous_school=data.get("previous_school", ""),
        primary_whatsapp_phone=data.get("primary_whatsapp_phone", ""),
        emergency_contact_name=data.get("emergency_contact_name", ""),
        emergency_contact_phone=data.get("emergency_contact_phone", ""),
        status=StudentStatus.ACTIVE,
    )
    parents = data.get("parents") or []
    if parents:
        _apply_parents(student, [p if isinstance(p, dict) else p.dict(by_alias=False) for p in parents])

    StudentEnrollment.objects.create(
        school=school,
        student=student,
        section=section,
        academic_year=year,
        roll_number=data.get("roll_number", ""),
        enrollment_date=data["admission_date"],
        status="active",
    )

    log_action(
        school_id=school.id, user_id=actor_id,
        action="student.create", model_name="Student", object_id=student.id,
    )
    return student


@transaction.atomic
def update_student(
    *, school: School, actor_id: int, student_id: int, data: dict[str, Any]
) -> Student:
    student = get_in_tenant(Student, school, pk=student_id)

    if data.get("admission_number"):
        _ensure_unique_admission(school, data["admission_number"], exclude_id=student.id)

    if data.get("status") and data["status"] not in StudentStatus.values:
        raise ValidationFailed("Invalid status.", {"status": ["unsupported value"]})
    if data.get("gender") and data["gender"] not in Gender.values:
        raise ValidationFailed("Invalid gender.", {"gender": ["unsupported value"]})

    plain_fields = {
        "admission_number", "first_name", "last_name", "dob", "gender",
        "blood_group", "address", "photo_url", "admission_date", "status",
        "previous_school", "primary_whatsapp_phone",
        "emergency_contact_name", "emergency_contact_phone",
    }
    changed: list[str] = []
    for field, value in data.items():
        if field in plain_fields and value is not None:
            setattr(student, field, value)
            changed.append(field)
    if changed:
        student.save(update_fields=[*changed, "updated_at"])

    if data.get("parents") is not None:
        parents = [p if isinstance(p, dict) else p.dict(by_alias=False) for p in data["parents"]]
        _apply_parents(student, parents)

    log_action(
        school_id=school.id, user_id=actor_id,
        action="student.update", model_name="Student", object_id=student.id,
        changes={"fields": changed},
    )
    return student


@transaction.atomic
def soft_delete_student(*, school: School, actor_id: int, student_id: int) -> None:
    # Withdrawing is an operational state change — the row stays queryable
    # under status=withdrawn. We never set deleted_at here; that's reserved
    # for true admin-driven deletion (GDPR purges, etc.) which has no UI.
    student = get_in_tenant(Student, school, pk=student_id)
    student.status = StudentStatus.WITHDRAWN
    student.withdrawal_date = timezone.now().date()
    student.save(update_fields=["status", "withdrawal_date", "updated_at"])
    # Mark active enrollment withdrawn so the student stops appearing in section rosters.
    StudentEnrollment.objects.filter(school=school, student=student, status="active").update(
        status="withdrawn"
    )
    log_action(
        school_id=school.id, user_id=actor_id,
        action="student.delete", model_name="Student", object_id=student.id,
    )


@transaction.atomic
def transfer_student(
    *,
    school: School,
    actor_id: int,
    student_id: int,
    target_section_id: int,
    roll_number: str = "",
    effective_date: date | None = None,
) -> Student:
    student = get_in_tenant(Student, school, pk=student_id)
    target = get_in_tenant(Section, school, pk=target_section_id)

    effective = effective_date or timezone.now().date()
    year = target.class_obj.academic_year

    active = (
        StudentEnrollment.objects.filter(
            school=school, student=student, status="active"
        )
        .select_related("section")
        .first()
    )
    if active and active.section_id == target.id:
        raise Conflict("Student is already enrolled in that section.")

    if active:
        active.status = "transferred"
        active.save(update_fields=["status", "updated_at"])

    StudentEnrollment.objects.create(
        school=school,
        student=student,
        section=target,
        academic_year=year,
        roll_number=roll_number,
        enrollment_date=effective,
        status="active",
    )
    log_action(
        school_id=school.id, user_id=actor_id,
        action="student.transfer", model_name="Student", object_id=student.id,
        changes={
            "from_section_id": active.section_id if active else None,
            "to_section_id": target.id,
            "effective_date": str(effective),
        },
    )
    return student


# ----- Teachers --------------------------------------------------------------

@transaction.atomic
def create_teacher(*, school: School, actor_id: int, data: dict[str, Any]) -> Teacher:
    if Teacher.objects.filter(school=school, phone=data["phone"]).exists():
        raise Conflict("A teacher with that phone already exists.", {"phone": ["duplicate"]})
    teacher = Teacher.objects.create(
        school=school,
        first_name=data["first_name"],
        last_name=data.get("last_name", ""),
        phone=data["phone"],
        email=data.get("email", ""),
        qualification=data.get("qualification", ""),
        joining_date=data.get("joining_date"),
        photo_url=data.get("photo_url", ""),
        status=TeacherStatus.ACTIVE,
    )
    log_action(
        school_id=school.id, user_id=actor_id,
        action="teacher.create", model_name="Teacher", object_id=teacher.id,
    )
    return teacher


@transaction.atomic
def update_teacher(*, school: School, actor_id: int, teacher_id: int, data: dict[str, Any]) -> Teacher:
    teacher = get_in_tenant(Teacher, school, pk=teacher_id)
    if data.get("status") and data["status"] not in TeacherStatus.values:
        raise ValidationFailed("Invalid status.", {"status": ["unsupported value"]})
    if data.get("phone") and data["phone"] != teacher.phone:
        if Teacher.objects.filter(school=school, phone=data["phone"]).exclude(id=teacher.id).exists():
            raise Conflict("A teacher with that phone already exists.", {"phone": ["duplicate"]})

    plain = {
        "first_name", "last_name", "phone", "email",
        "qualification", "joining_date", "photo_url", "status",
    }
    changed = []
    for field, value in data.items():
        if field in plain and value is not None:
            setattr(teacher, field, value)
            changed.append(field)
    if changed:
        teacher.save(update_fields=[*changed, "updated_at"])

    log_action(
        school_id=school.id, user_id=actor_id,
        action="teacher.update", model_name="Teacher", object_id=teacher.id,
        changes={"fields": changed},
    )
    return teacher


@transaction.atomic
def soft_delete_teacher(*, school: School, actor_id: int, teacher_id: int) -> None:
    # Same semantics as student withdrawal — operational state, not row removal.
    teacher = get_in_tenant(Teacher, school, pk=teacher_id)
    teacher.status = TeacherStatus.INACTIVE
    teacher.save(update_fields=["status", "updated_at"])
    log_action(
        school_id=school.id, user_id=actor_id,
        action="teacher.delete", model_name="Teacher", object_id=teacher.id,
    )


@transaction.atomic
def reset_teacher_login_password(*, school: School, actor_id: int, teacher_id: int) -> str:
    """Generate a fresh login password for a teacher and return it once.

    Admins hand this to the teacher for their first sign-in. The login ``User``
    is created on demand (teachers otherwise self-activate via OTP). Only the
    hash is stored — the plaintext is returned to the caller and never persisted.
    """
    teacher = get_in_tenant(Teacher, school, pk=teacher_id)
    normalized = normalize_in_phone(teacher.phone)
    password = _generate_temp_password()

    user = teacher.user
    if user is None:
        existing = User.objects.filter(phone=normalized).first()
        if existing is not None and existing.role != Role.TEACHER:
            raise Conflict("That phone is already in use by another account.")
        user = existing or User(
            phone=normalized,
            role=Role.TEACHER,
            school=school,
            first_name=teacher.first_name,
            last_name=teacher.last_name,
            email=teacher.email,
            is_active=True,
        )
    user.set_password(password)
    user.save()
    if teacher.user_id != user.id:
        teacher.user = user
        teacher.save(update_fields=["user"])

    log_action(
        school_id=school.id, user_id=actor_id,
        action="teacher.reset_password", model_name="Teacher", object_id=teacher.id,
    )
    return password


# ----- Parent app login (temporary admin-set password) -----------------------

def _primary_parent_contact(student: Student) -> dict[str, str] | None:
    """The student's parent contact that owns the app login: parent1 if it has
    a phone, else parent2. None if neither has a phone."""
    for prefix in ("parent1", "parent2"):
        phone = getattr(student, f"{prefix}_phone", "")
        if phone:
            return {
                "name": getattr(student, f"{prefix}_name", "") or "Parent",
                "phone": phone,
                "email": getattr(student, f"{prefix}_email", ""),
                "relation": getattr(student, f"{prefix}_relation", ""),
            }
    return None


@transaction.atomic
def reset_parent_login_password(*, school: School, actor_id: int, student_id: int) -> str:
    """Generate the parent-app login password for a student's primary parent.

    One login per family (keyed by phone): provisions the Parent + login User on
    demand, links this child, and stores the plaintext on the Parent so the admin
    can read it back. Returns the password.
    """
    student = get_in_tenant(Student, school, pk=student_id)
    contact = _primary_parent_contact(student)
    if contact is None:
        raise ValidationFailed("Add a parent phone number for this student first.")

    if len([ch for ch in contact["phone"] if ch.isdigit()]) < 10:
        raise ValidationFailed("The parent phone isn't a valid 10-digit number — fix it first.")
    normalized = normalize_in_phone(contact["phone"])
    password = _generate_temp_password()

    user = User.objects.filter(phone=normalized).first()
    if user is not None and user.role != Role.PARENT:
        raise Conflict("That phone is already in use by another account.")
    if user is None:
        first, _, last = contact["name"].partition(" ")
        user = User(
            phone=normalized, role=Role.PARENT, school=school,
            first_name=first, last_name=last, email=contact["email"], is_active=True,
        )
    user.set_password(password)
    user.save()

    parent = Parent.objects.filter(school=school, phone=normalized).first()
    if parent is None:
        parent = Parent(school=school, name=contact["name"], phone=normalized, email=contact["email"])
    parent.user = user
    parent.app_password = password
    parent.save()

    relation = contact["relation"] if contact["relation"] in Relation.values else Relation.GUARDIAN
    ParentStudent.objects.get_or_create(
        school=school, parent=parent, student=student, defaults={"relation": relation}
    )

    log_action(school_id=school.id, user_id=actor_id, action="parent.reset_password",
               model_name="Parent", object_id=parent.id)
    return password
