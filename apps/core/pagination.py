"""Pagination helpers for list endpoints."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from django.db.models import QuerySet


def paginate(
    queryset: QuerySet | Sequence[Any],
    *,
    page: int = 1,
    page_size: int = 50,
    max_page_size: int = 200,
) -> dict[str, Any]:
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 50
    if page_size > max_page_size:
        page_size = max_page_size

    count = queryset.count() if isinstance(queryset, QuerySet) else len(queryset)
    total_pages = math.ceil(count / page_size) if count else 0
    start = (page - 1) * page_size
    end = start + page_size
    items = list(queryset[start:end])
    return {
        "items": items,
        "count": count,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }
