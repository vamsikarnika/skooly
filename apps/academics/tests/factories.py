from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from apps.academics.models import Class, Section, Subject
from apps.schools.tests.factories import AcademicYearFactory, SchoolFactory


class SubjectFactory(DjangoModelFactory):
    class Meta:
        model = Subject

    school = factory.SubFactory(SchoolFactory)
    name = factory.Sequence(lambda n: f"Subject {n}")


class ClassFactory(DjangoModelFactory):
    class Meta:
        model = Class

    school = factory.SubFactory(SchoolFactory)
    academic_year = factory.SubFactory(AcademicYearFactory)
    name = factory.Sequence(lambda n: f"Class {n + 1}")
    display_order = factory.Sequence(lambda n: n + 1)

    @factory.post_generation
    def link_school(self, create, extracted, **kwargs):
        if create and self.academic_year.school_id != self.school_id:
            self.academic_year.school = self.school
            self.academic_year.save(update_fields=["school"])


class SectionFactory(DjangoModelFactory):
    class Meta:
        model = Section

    school = factory.SubFactory(SchoolFactory)
    class_obj = factory.SubFactory(ClassFactory)
    name = factory.Sequence(lambda n: chr(ord("A") + (n % 26)))
    capacity = 40

    @factory.post_generation
    def link_school(self, create, extracted, **kwargs):
        if create and self.class_obj.school_id != self.school_id:
            self.class_obj.school = self.school
            self.class_obj.save(update_fields=["school"])
