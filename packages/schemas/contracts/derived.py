"""Contracts for normalised quotes, fare components and cleaning events."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from schemas.contracts.base import (
    ApixContract,
    CarrierCode,
    NonEmptyText,
    NonNegativeMoney,
    PositiveMoney,
    QualityScore,
    Utc,
)
from schemas.enums import (
    Confidence,
    FareComponentKind,
    ImputationCode,
    MissingReason,
    Provenance,
    QualityStatus,
)


class NormalisedQuote(ApixContract):
    """normalised_quote - the join between the evidence trail and the index.

    provenance has no default. A quote that does not say where it came from is
    not representable.
    """

    raw_quote_id: UUID | None = None
    route_id: UUID
    bucket_id: UUID
    source_id: UUID
    carrier: CarrierCode
    flight_no: str | None = None
    departure_ts: Utc | None = None
    arrival_ts: Utc | None = None
    lead_time_days: int = Field(gt=0)
    fare_brand: str | None = None
    total_fare: PositiveMoney
    currency: Literal["INR"]
    collected_at: Utc
    collected_date: date
    provenance: Provenance
    quality_status: QualityStatus
    quality_score: QualityScore | None = None
    imputation_code: ImputationCode
    missing_reason: MissingReason
    component_confidence: Confidence | None = None

    @model_validator(mode="after")
    def imputed_or_sourced(self) -> NormalisedQuote:
        """Mirror ck_normalised_quote_imputed_or_sourced at the boundary."""
        if self.imputation_code is not ImputationCode.Y and self.raw_quote_id is None:
            raise ValueError(
                "a non-imputed quote must reference the raw_quote it was derived from"
            )
        return self


class FareComponent(ApixContract):
    """fare_component"""

    quote_id: UUID
    kind: FareComponentKind
    amount: NonNegativeMoney
    confidence: Confidence


class CleaningEvent(ApixContract):
    """cleaning_event - one rule, one decision, permanently recorded."""

    quote_id: UUID
    rule_id: NonEmptyText
    action: NonEmptyText
    threshold: Decimal | None = None
    observed: Decimal | None = None
    reason: NonEmptyText


__all__ = ["CleaningEvent", "FareComponent", "NormalisedQuote"]
