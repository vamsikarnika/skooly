from __future__ import annotations

from datetime import date

import factory
from factory.django import DjangoModelFactory

from apps.people.models import Gender, Student, StudentStatus, Teacher, TeacherStatus
from apps.schools.tests.factories import SchoolFactory


class StudentFactory(DjangoModelFactory):
    class Meta:
        model = Student

    school = factory.SubFactory(SchoolFactory)
    admission_number = factory.Sequence(lambda n: f"ADM{n:05d}")
    first_name = factory.Sequence(lambda n: f"First{n}")
    last_name = "Test"
    gender = Gender.MALE
    admission_date = date(2025, 6, 1)
    status = StudentStatus.ACTIVE


class TeacherFactory(DjangoModelFactory):
    class Meta:
        model = Teacher

    school = factory.SubFactory(SchoolFactory)
    first_name = factory.Sequence(lambda n: f"Teacher{n}")
    last_name = "Test"
    phone = factory.Sequence(lambda n: f"+9197{n:08d}")
    status = TeacherStatus.ACTIVE
