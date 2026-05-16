from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from apps.accounts.models import Role, User
from apps.schools.tests.factories import SchoolFactory


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    school = factory.SubFactory(SchoolFactory)
    phone = factory.Sequence(lambda n: f"+91900000{n:04d}")
    email = factory.Sequence(lambda n: f"user{n}@example.com")
    first_name = factory.Sequence(lambda n: f"First{n}")
    last_name = "Tester"
    role = Role.ADMIN
    is_active = True

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        raw = extracted or "testpass123"
        self.set_password(raw)
        if create:
            self.save()
