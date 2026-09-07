"""Declarative base, shared column defaults, and the immutable-table register.

Two things every APIx table gets: a UUIDv7 primary key and a UTC creation
timestamp. Both have a server-side default as well as a client-side one, so a
row inserted by raw SQL (a test, psql, a future maintenance script) is shaped
exactly like a row inserted through the ORM.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from schemas.enums import values as enum_values
from schemas.uuid7 import uuid7

# Deterministic constraint names. Alembic autogenerate and the schema-shape
# tests both depend on the database and the models agreeing on names, so the
# convention is declared once and never overridden except where a generated
# name would exceed PostgreSQL's 63-character identifier limit (those
# constraints carry an explicit short `name=`).
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    # CHECK constraints carry explicit, self-describing names in the models
    # (ck_<table>_<what>), so the convention is the identity - without this the
    # table prefix would be applied twice.
    "ck": "%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Root of the APIx declarative hierarchy."""

    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


class Entity(Base):
    """Abstract base carrying the two universal columns."""

    __abstract__ = True

    # `eager_defaults` makes SQLAlchemy fetch server-generated values with
    # RETURNING on INSERT, so `created_at` is readable without a second query.
    # Not annotated ClassVar: SQLAlchemy's DeclarativeBase already declares
    # __mapper_args__ as an instance attribute, and re-declaring it as a class
    # variable is an override error under mypy --strict.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        primary_key=True,
        default=uuid7,
        server_default=sa.text("uuidv7()"),
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def enum_check(
    table: str,
    column: str,
    enum_cls: type[StrEnum],
    *,
    name: str | None = None,
) -> sa.CheckConstraint:
    """Build the PostgreSQL CHECK that mirrors a Python StrEnum.

    Generating the SQL from the enum members means the database domain cannot
    silently drift away from the Python domain: add a member, regenerate, and
    the migration diff shows up.
    """
    allowed = ", ".join(f"'{value}'" for value in enum_values(enum_cls))
    constraint_name = name or f"ck_{table}_{column}"
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=constraint_name)


# The append-only (IMM) tables. `apix_app` holds SELECT and INSERT on these and
# nothing else: UPDATE and DELETE are revoked in migration 0003. Corrections are
# made by inserting a new row under a new version, never by editing.
IMMUTABLE_TABLES: tuple[str, ...] = (
    "backtest_run",
    "benchmark_observation",
    "cleaning_event",
    "collection_request",
    "compliance_decision",
    "index_contribution",
    "index_observation",
    "methodology_version",
    "raw_quote",
    "raw_response",
    "route_weight",
    "source_review",
    "weight_set_version",
)

# Tables that ordinary application code may UPDATE and DELETE.
MUTABLE_TABLES: tuple[str, ...] = (
    "airport",
    "base_period",
    "collection_job",
    "fare_component",
    "lead_time_bucket",
    "normalised_quote",
    "route",
    "source",
    "system_event",
)

ALL_TABLES: tuple[str, ...] = tuple(sorted(IMMUTABLE_TABLES + MUTABLE_TABLES))

__all__ = [
    "ALL_TABLES",
    "IMMUTABLE_TABLES",
    "MUTABLE_TABLES",
    "NAMING_CONVENTION",
    "Base",
    "Entity",
    "enum_check",
]
