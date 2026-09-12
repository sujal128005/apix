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
from schemas.enums import IndexLevel, PublicationState


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
    revision: int = Field(default=1, ge=1)
    """Which revision of this figure. 1 is the first computation.

    Part of the identity, so a correction for an already-published date creates
    revision 2 beside revision 1 rather than replacing it."""

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


class Publication(ApixContract):
    """publication - the release lifecycle of one computed index value.

    Separate from the observation because the figure is immutable and its status
    is not. That separation is what keeps "what was published on the 14th?"
    answerable after a revision on the 20th.
    """

    index_observation_id: UUID
    state: PublicationState = PublicationState.PENDING
    approved_by: NonEmptyText | None = None
    approved_at: Utc | None = None
    scheduled_release_at: Utc | None = None
    published_at: Utc | None = None
    supersedes_id: UUID | None = None
    revision_reason: NonEmptyText | None = None
    withdrawn_reason: NonEmptyText | None = None

    @model_validator(mode="after")
    def approval_is_attributed(self) -> Publication:
        """A figure released under no one's name is not an approved figure."""
        if self.state is not PublicationState.PENDING and not self.approved_by:
            raise ValueError(f"a {self.state} publication must record who approved it")
        return self

    @model_validator(mode="after")
    def changes_explain_themselves(self) -> Publication:
        """A revision or withdrawal a reader cannot evaluate is not disclosure."""
        if self.supersedes_id is not None and not self.revision_reason:
            raise ValueError("a revision must state its reason")
        if self.state is PublicationState.WITHDRAWN and not self.withdrawn_reason:
            raise ValueError("a withdrawal must state its reason")
        return self


__all__ = [
    "BacktestRun",
    "BenchmarkObservation",
    "IndexContribution",
    "IndexObservation",
    "Publication",
]
