from __future__ import annotations

from datetime import date

import factory
from factory.django import DjangoModelFactory

from apps.schools.models import AcademicYear, Board, School


class SchoolFactory(DjangoModelFactory):
    class Meta:
        model = School

    name = factory.Sequence(lambda n: f"Test School {n}")
    board = Board.AP_STATE
    address = "Test address"


class AcademicYearFactory(DjangoModelFactory):
    class Meta:
        model = AcademicYear

    school = factory.SubFactory(SchoolFactory)
    label = factory.Sequence(lambda n: f"20{25 + n}-{26 + n}")
    start_date = date(2025, 6, 1)
    end_date = date(2026, 4, 30)
    is_current = True

    @factory.post_generation
    def link_current(self, create, extracted, **kwargs):
        if create and self.is_current:
            self.school.current_academic_year = self
            self.school.save(update_fields=["current_academic_year"])
