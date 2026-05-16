"""Audit log helpers — Module 1 stub.

Module 10 (Polish) will introduce the AuditLog model + signals. For now,
``log_action`` only writes to the standard logger so callers can wire up
audit calls during earlier modules without depending on a DB table that
doesn't exist yet.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("apps.audit")


def log_action(
    *,
    school_id: int | None,
    user_id: int | None,
    action: str,
    model_name: str,
    object_id: str | int = "",
    changes: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str = "",
) -> None:
    logger.info(
        "audit action=%s model=%s id=%s school=%s user=%s ip=%s",
        action,
        model_name,
        object_id,
        school_id,
        user_id,
        ip_address,
    )
