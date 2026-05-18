from __future__ import annotations

from datetime import date

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.exams.models import Test, TestScore, TestType


class TestFactory(DjangoModelFactory):
    class Meta:
        model = Test

    name = factory.Sequence(lambda n: f"Test {n}")
    test_type = TestType.FA1
    test_date = date(2026, 5, 1)
    max_marks = 50
    published_at = factory.LazyFunction(timezone.now)


class TestScoreFactory(DjangoModelFactory):
    class Meta:
        model = TestScore

    marks_obtained = 40
    is_absent = False
