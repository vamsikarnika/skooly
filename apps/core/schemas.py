"""Shared Pydantic base classes for API schemas.

CamelCase at the API boundary, snake_case in Python. The frontend sees
``admissionNo`` while Django sees ``admission_no``.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from ninja import Schema
from pydantic import ConfigDict


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
