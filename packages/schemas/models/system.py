"""Operational logging."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from schemas.models.base import Entity


class SystemEvent(Entity):
    """A structured operational event.

    payload is nullable because many events carry no structured detail beyond
    their level, component and message, and the brief specifies no default.
    """

    __tablename__ = "system_event"

    level: Mapped[str] = mapped_column(sa.Text, nullable=False)
    component: Mapped[str] = mapped_column(sa.Text, nullable=False)
    event: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (sa.Index("ix_system_event_created_at", sa.text("created_at DESC")),)


__all__ = ["SystemEvent"]
