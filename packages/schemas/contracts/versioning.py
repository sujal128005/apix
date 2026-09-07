"""Contracts for versioned methodology and weights."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from pydantic import model_validator

from schemas.contracts.base import ApixContract, NonEmptyText, Utc, Weight
from schemas.enums import EvidenceRung


class MethodologyVersion(ApixContract):
    """methodology_version"""

    version: NonEmptyText
    effective_from: date
    params: dict[str, Any]
    changelog: NonEmptyText


class WeightSetVersion(ApixContract):
    """weight_set_version"""

    version: NonEmptyText
    effective_from: date
    source_note: NonEmptyText


class BasePeriod(ApixContract):
    """base_period - the reference period an index value is chained back to."""

    code: NonEmptyText
    start_date: date
    end_date: date
    description: NonEmptyText
    methodology_version_id: UUID

    @model_validator(mode="after")
    def dates_ordered(self) -> BasePeriod:
        """Mirror ck_base_period_dates_ordered at the boundary."""
        if self.end_date <= self.start_date:
            raise ValueError("base period end_date must be after start_date")
        return self


class RouteWeight(ApixContract):
    """route_weight - a weight cannot exist without stating its evidence."""

    route_id: UUID
    weight: Weight
    evidence_rung: EvidenceRung
    evidence_ref: NonEmptyText
    evidence_retrieved_at: Utc
    weight_set_version_id: UUID


__all__ = ["BasePeriod", "MethodologyVersion", "RouteWeight", "WeightSetVersion"]
