"""Read-only services for Module 2 lite. Full CRUD comes in Module 2 proper."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet

from apps.people.models import Student, Teacher


def list_students(
    *,
    section_id: int | None = None,
    class_id: int | None = None,
    status: str | None = None,
    search: str | None = None,
) -> QuerySet[Student]:
    qs = (
        Student.objects.select_related()
        .prefetch_related("enrollments__section__class_obj")
    )
    if status:
        qs = qs.filter(status=status)
    if section_id:
        qs = qs.filter(enrollments__section_id=section_id, enrollments__status="active")
    if class_id:
        qs = qs.filter(enrollments__section__class_obj_id=class_id, enrollments__status="active")
    if search:
        qs = qs.filter(
            first_name__icontains=search,
        ) | qs.filter(last_name__icontains=search) | qs.filter(admission_number__icontains=search)
    return qs.distinct()


def list_teachers(*, status: str | None = None) -> QuerySet[Teacher]:
    qs = Teacher.objects.all()
    if status:
        qs = qs.filter(status=status)
    return qs


def student_to_dict(student: Student) -> dict[str, Any]:
    enrollment = next(
        (e for e in student.enrollments.all() if e.status == "active"),
        None,
    )
    parents: list[dict[str, Any]] = []
    if student.parent1_name:
        parents.append({
            "name": student.parent1_name,
            "relation": student.parent1_relation or "Father",
            "phone": student.parent1_phone,
            "email": student.parent1_email,
            "whatsapp": student.parent1_whatsapp,
        })
    if student.parent2_name:
        parents.append({
            "name": student.parent2_name,
            "relation": student.parent2_relation or "Mother",
            "phone": student.parent2_phone,
            "email": student.parent2_email,
            "whatsapp": student.parent2_whatsapp,
        })

    return {
        "id": student.id,
        "admission_number": student.admission_number,
        "first_name": student.first_name,
        "last_name": student.last_name,
        "full_name": student.full_name,
        "dob": student.dob,
        "gender": student.gender,
        "blood_group": student.blood_group,
        "address": student.address,
        "photo_url": student.photo_url,
        "admission_date": student.admission_date,
        "status": student.status,
        "class_name": enrollment.section.class_obj.name if enrollment else None,
        "section_name": enrollment.section.name if enrollment else None,
        "roll_number": enrollment.roll_number if enrollment else "",
        "parents": parents,
    }
