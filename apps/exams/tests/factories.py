from __future__ import annotations

from datetime import date

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.exams.models import Test, TestScore, TestType


class TestFactory(DjangoModelFactory):
    class Meta:
        model = Test
        exclude = ["_now"]

    _now = factory.LazyFunction(timezone.now)

    name = factory.Sequence(lambda n: f"Test {n}")
    test_type = TestType.FA1
    mode = "offline"
    test_date = date(2026, 5, 1)
    max_marks = 50
    duration_min = 0
    available_from = None
    available_until = None
    published_at = factory.LazyFunction(timezone.now)


class TestScoreFactory(DjangoModelFactory):
    class Meta:
        model = TestScore

    marks_obtained = 40
    is_absent = False
