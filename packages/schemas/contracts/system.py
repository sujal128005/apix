"""Contract for operational logging."""

from __future__ import annotations

from typing import Any

from schemas.contracts.base import ApixContract, NonEmptyText


class SystemEvent(ApixContract):
    """system_event"""

    level: NonEmptyText
    component: NonEmptyText
    event: NonEmptyText
    payload: dict[str, Any] | None = None


__all__ = ["SystemEvent"]
