from __future__ import annotations

from datetime import date

import factory
from factory.django import DjangoModelFactory

from apps.fees.models import FeeComponent, FeeStructure


class FeeStructureFactory(DjangoModelFactory):
    class Meta:
        model = FeeStructure

    name = factory.Sequence(lambda n: f"Structure {n}")


class FeeComponentFactory(DjangoModelFactory):
    class Meta:
        model = FeeComponent

    name = factory.Sequence(lambda n: f"Component {n}")
    amount_paise = 1000_00  # ₹1,000 default
    due_date = date(2025, 6, 1)
    is_optional = False
