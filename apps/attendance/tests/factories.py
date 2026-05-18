from __future__ import annotations

from datetime import date

import factory
from factory.django import DjangoModelFactory

from apps.attendance.models import Attendance, AttendanceStatus
from apps.people.tests.factories import StudentFactory


class AttendanceFactory(DjangoModelFactory):
    class Meta:
        model = Attendance

    student = factory.SubFactory(StudentFactory)
    date = date(2026, 5, 1)
    status = AttendanceStatus.PRESENT
