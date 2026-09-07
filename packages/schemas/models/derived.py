"""Derived observations: normalised quotes, their fare components, cleaning events.

normalised_quote is the join between the evidence trail and the index. Every
row carries a non-null provenance, and a row without a raw_quote is only legal
when it is explicitly flagged as imputed.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from schemas.enums import (
    Confidence,
    FareComponentKind,
    ImputationCode,
    MissingReason,
    Provenance,
    QualityStatus,
)
from schemas.models.base import Entity, enum_check


class NormalisedQuote(Entity):
    """One cleaned, comparable fare observation.

    total_fare is NUMERIC(12,2) and is read back as a Decimal. There is no float
    anywhere on this path.

    quality_score is nullable: it is assigned by the Phase 8 cleaning pipeline,
    and a quote that has only been normalised has not been scored yet.
    """

    __tablename__ = "normalised_quote"

    raw_quote_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("raw_quote.id", name="fk_normalised_quote_raw_quote_id"),
        nullable=True,
    )
    route_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("route.id", name="fk_normalised_quote_route_id"),
        nullable=False,
    )
    bucket_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("lead_time_bucket.id", name="fk_normalised_quote_bucket_id"),
        nullable=False,
    )
    source_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("source.id", name="fk_normalised_quote_source_id"),
        nullable=False,
    )
    carrier: Mapped[str] = mapped_column(sa.CHAR(2), nullable=False)
    flight_no: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    departure_ts: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    arrival_ts: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    lead_time_days: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    fare_brand: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    total_fare: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        sa.CHAR(3), nullable=False, server_default=sa.text("'INR'")
    )
    collected_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    collected_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    provenance: Mapped[str] = mapped_column(sa.Text, nullable=False)
    quality_status: Mapped[str] = mapped_column(sa.Text, nullable=False)
    quality_score: Mapped[Decimal | None] = mapped_column(sa.Numeric(4, 3), nullable=True)
    imputation_code: Mapped[str] = mapped_column(
        sa.CHAR(1), nullable=False, server_default=sa.text("'N'")
    )
    missing_reason: Mapped[str] = mapped_column(
        sa.Text, nullable=False, server_default=sa.text("'NONE'")
    )
    component_confidence: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    __table_args__ = (
        sa.CheckConstraint("total_fare > 0", name="ck_normalised_quote_total_fare_positive"),
        sa.CheckConstraint("currency = 'INR'", name="ck_normalised_quote_currency_inr"),
        # Only an imputed row may lack a raw quote. Everything else must be
        # traceable to bytes we actually received.
        sa.CheckConstraint(
            "imputation_code = 'Y' OR raw_quote_id IS NOT NULL",
            name="ck_normalised_quote_imputed_or_sourced",
        ),
        enum_check("normalised_quote", "provenance", Provenance),
        enum_check("normalised_quote", "quality_status", QualityStatus),
        enum_check("normalised_quote", "imputation_code", ImputationCode),
        enum_check("normalised_quote", "missing_reason", MissingReason),
        sa.CheckConstraint(
            "component_confidence IS NULL OR component_confidence IN ('HIGH', 'MEDIUM', 'LOW')",
            name="ck_normalised_quote_component_confidence",
        ),
        sa.UniqueConstraint(
            "source_id",
            "carrier",
            "flight_no",
            "departure_ts",
            "fare_brand",
            "collected_date",
            name="uq_normalised_quote_dedup",
        ),
        sa.Index(
            "ix_normalised_quote_route_bucket_date",
            "route_id",
            "bucket_id",
            "collected_date",
        ),
    )


class FareComponent(Entity):
    """One published component of a total fare (base, tax, UDF, ...)."""

    __tablename__ = "fare_component"

    quote_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("normalised_quote.id", name="fk_fare_component_quote_id"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), nullable=False)
    confidence: Mapped[str] = mapped_column(sa.Text, nullable=False)

    __table_args__ = (
        sa.CheckConstraint("amount >= 0", name="ck_fare_component_amount_non_negative"),
        enum_check("fare_component", "kind", FareComponentKind),
        enum_check("fare_component", "confidence", Confidence),
        sa.UniqueConstraint("quote_id", "kind", name="uq_fare_component_quote_kind"),
    )


class CleaningEvent(Entity):
    """A record that a cleaning rule looked at a quote and what it decided.

    Append-only. The set of cleaning events attached to a quote is the audit
    trail a judge follows from a published index value back to the rules that
    shaped the inputs.
    """

    __tablename__ = "cleaning_event"

    quote_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("normalised_quote.id", name="fk_cleaning_event_quote_id"),
        nullable=False,
    )
    rule_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    action: Mapped[str] = mapped_column(sa.Text, nullable=False)
    threshold: Mapped[Decimal | None] = mapped_column(sa.Numeric, nullable=True)
    observed: Mapped[Decimal | None] = mapped_column(sa.Numeric, nullable=True)
    reason: Mapped[str] = mapped_column(sa.Text, nullable=False)

    __table_args__ = (sa.Index("ix_cleaning_event_quote_id", "quote_id"),)


__all__ = ["CleaningEvent", "FareComponent", "NormalisedQuote"]
