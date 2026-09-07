"""Reference data: airports, routes, lead-time buckets, sources and their reviews.

Nullability follows the build brief §5 literally where it is marked, and is
resolved by structural necessity where the brief is silent. The two columns
left nullable despite being unmarked are `source.base_url` and
`source_review.robots_decision`/`tos_note`: the brief's seed specification (§7)
supplies no URLs, and inventing them would breach hard rule 2.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from schemas.enums import ReviewVerdict, Transport
from schemas.models.base import Entity, enum_check


class Airport(Entity):
    """An Indian airport, keyed by IATA code."""

    __tablename__ = "airport"

    iata: Mapped[str] = mapped_column(sa.CHAR(3), nullable=False, unique=True)
    icao: Mapped[str | None] = mapped_column(sa.CHAR(4), nullable=True)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    city: Mapped[str] = mapped_column(sa.Text, nullable=False)
    state: Mapped[str] = mapped_column(sa.Text, nullable=False)
    tz: Mapped[str] = mapped_column(
        sa.Text, nullable=False, server_default=sa.text("'Asia/Kolkata'")
    )
    active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.text("true"))

    __table_args__ = (
        sa.CheckConstraint(r"iata ~ '^[A-Z]{3}$'", name="ck_airport_iata_format"),
    )


class Route(Entity):
    """A directional city pair. DEL-BOM and BOM-DEL are different routes (ADR-017).

    The undirected view over this table is `route_undirected`, created in
    migration 0001.
    """

    __tablename__ = "route"

    code: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    origin_id: Mapped[UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("airport.id", name="fk_route_origin_id"), nullable=False
    )
    destination_id: Mapped[UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("airport.id", name="fk_route_destination_id"), nullable=False
    )
    directional: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("true")
    )
    active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.text("true"))

    __table_args__ = (
        sa.CheckConstraint("origin_id <> destination_id", name="ck_route_origin_ne_destination"),
        sa.CheckConstraint(r"code ~ '^[A-Z]{3}-[A-Z]{3}$'", name="ck_route_code_format"),
    )


class LeadTimeBucket(Entity):
    """One of the six advance-purchase strata.

    T21 is the only bucket directly comparable to the official CPI: MoSPI's
    CPI 2024 collects domestic airfare at a 21-day advance-purchase window
    (Expert Group Report §3.9).

    `lambda` is the bucket's share in higher-level aggregation. The ORM
    attribute is `lambda_` because `lambda` is a reserved Python word; the
    database column name is `lambda`, exactly as specified.
    """

    __tablename__ = "lead_time_bucket"

    code: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    days: Mapped[int] = mapped_column(sa.Integer, nullable=False, unique=True)
    lambda_: Mapped[Decimal] = mapped_column("lambda", sa.Numeric(8, 6), nullable=False)
    cpi_comparable: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("false")
    )

    __table_args__ = (sa.CheckConstraint("days > 0", name="ck_lead_time_bucket_days_positive"),)


class Source(Entity):
    """A fare source. Disabled until someone deliberately enables it.

    `enabled` defaults to false because sources are opt-in, never opt-out. The
    Tier-4 OTAs are seeded so they are visible and auditable in the compliance
    register, and they stay disabled: their robots.txt disallows automated
    flight-search collection.
    """

    __tablename__ = "source"

    code: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    tier: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    transport: Mapped[str] = mapped_column(sa.Text, nullable=False)
    adapter_key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    base_url: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("false")
    )

    __table_args__ = (
        sa.CheckConstraint("tier BETWEEN 1 AND 5", name="ck_source_tier_range"),
        enum_check("source", "transport", Transport),
    )


class SourceReview(Entity):
    """Append-only record of a human compliance review of a source."""

    __tablename__ = "source_review"

    source_id: Mapped[UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("source.id", name="fk_source_review_source_id"), nullable=False
    )
    reviewer: Mapped[str] = mapped_column(sa.Text, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    robots_decision: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    tos_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    verdict: Mapped[str] = mapped_column(sa.Text, nullable=False)

    __table_args__ = (enum_check("source_review", "verdict", ReviewVerdict),)


__all__ = ["Airport", "LeadTimeBucket", "Route", "Source", "SourceReview"]
