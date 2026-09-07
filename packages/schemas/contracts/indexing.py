"""Contracts for index observations, contributions, benchmarks and backtests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from schemas.contracts.base import (
    ApixContract,
    IndexValue,
    NonEmptyText,
    SignedIndexValue,
    Utc,
)
from schemas.enums import IndexLevel


class IndexObservation(ApixContract):
    """index_observation - one computed value, with the inputs that produced it."""

    obs_date: date
    level: IndexLevel
    ref_id: UUID | None = None
    bucket_id: UUID | None = None
    index_value: IndexValue
    prev_index_value: IndexValue | None = None
    base_period_id: UUID | None = None
    methodology_version_id: UUID
    weight_set_version_id: UUID
    input_quote_count: int = Field(ge=0)
    excluded_count: int = Field(ge=0)
    imputed_count: int = Field(ge=0)
    routes_in_basket: int | None = Field(default=None, ge=0)
    input_hash: NonEmptyText
    computed_at: Utc

    @model_validator(mode="after")
    def headline_has_no_ref(self) -> IndexObservation:
        """A HEADLINE value is the whole basket, so it references nothing narrower."""
        if self.level is IndexLevel.HEADLINE and self.ref_id is not None:
            raise ValueError("a HEADLINE index_observation must not carry a ref_id")
        return self


class IndexContribution(ApixContract):
    """index_contribution"""

    index_observation_id: UUID
    route_id: UUID
    contribution: SignedIndexValue


class BenchmarkObservation(ApixContract):
    """benchmark_observation - an uncited benchmark cannot exist."""

    bench_source: NonEmptyText
    period: NonEmptyText
    ref: str | None = None
    value: Decimal = Field(max_digits=14, decimal_places=4)
    definition: NonEmptyText
    citation_url: NonEmptyText
    citation_page: str | None = None
    retrieved_at: Utc


class BacktestRun(ApixContract):
    """backtest_run - limitations are mandatory, because this backtest has them."""

    window_start: date
    window_end: date
    tier: int = Field(ge=1, le=3)
    metrics: dict[str, Any]
    limitations: NonEmptyText
    input_hash: NonEmptyText
    run_at: Utc

    @model_validator(mode="after")
    def window_ordered(self) -> BacktestRun:
        if self.window_end < self.window_start:
            raise ValueError("window_end precedes window_start")
        return self


__all__ = [
    "BacktestRun",
    "BenchmarkObservation",
    "IndexContribution",
    "IndexObservation",
]
