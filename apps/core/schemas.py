"""Shared Pydantic base classes for API schemas.

CamelCase at the API boundary, snake_case in Python. The frontend sees
``admissionNo`` while Django sees ``admission_no``.
"""

from __future__ import annotations

import re
from typing import Annotated, Generic, TypeVar

from ninja import Schema
from pydantic import ConfigDict, StringConstraints

# Indian phone numbers in our system: +91 + 10 digits, no spaces.
# Use as: ``phone: PhoneIN`` in schemas.
PhoneIN = Annotated[str, StringConstraints(pattern=r"^\+91[0-9]{10}$")]
PhoneINOptional = Annotated[str, StringConstraints(pattern=r"^(\+91[0-9]{10})?$")]

_PHONE_RE = re.compile(r"^\+91[0-9]{10}$")


def is_valid_in_phone(value: str) -> bool:
    return bool(_PHONE_RE.match(value))


def _to_camel(s: str) -> str:
    head, *tail = s.split("_")
    return head + "".join(p.title() for p in tail)


class CamelSchema(Schema):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        from_attributes=True,
        # Pydantic 2.11+: emit aliases on serialization too.
        serialize_by_alias=True,
    )


T = TypeVar("T")


class Paginated(CamelSchema, Generic[T]):
    items: list[T]
    count: int
    page: int
    page_size: int
    total_pages: int


class ActionResponse(CamelSchema):
    success: bool
    message: str | None = None
    data: dict | None = None
