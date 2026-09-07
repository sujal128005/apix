"""Contracts for reference data."""

from __future__ import annotations

from uuid import UUID

from schemas.contracts.base import (
    ApixContract,
    IataCode,
    IcaoCode,
    Lambda,
    NonEmptyText,
    RouteCode,
    Utc,
)
from schemas.enums import ReviewVerdict, SourceTier, Transport


class Airport(ApixContract):
    """airport"""

    iata: IataCode
    icao: IcaoCode | None = None
    name: NonEmptyText
    city: NonEmptyText
    state: NonEmptyText
    tz: NonEmptyText
    active: bool


class Route(ApixContract):
    """route - directional; DEL-BOM and BOM-DEL are separate rows."""

    code: RouteCode
    origin_id: UUID
    destination_id: UUID
    directional: bool
    active: bool


class LeadTimeBucket(ApixContract):
    """lead_time_bucket - the field is `lambda_` because `lambda` is reserved in Python."""

    code: NonEmptyText
    days: int
    lambda_: Lambda
    cpi_comparable: bool


class Source(ApixContract):
    """source - base_url is optional; the brief supplies no URLs and we invent none."""

    code: NonEmptyText
    name: NonEmptyText
    tier: SourceTier
    transport: Transport
    adapter_key: NonEmptyText
    base_url: str | None = None
    enabled: bool


class SourceReview(ApixContract):
    """source_review"""

    source_id: UUID
    reviewer: NonEmptyText
    reviewed_at: Utc
    robots_decision: str | None = None
    tos_note: str | None = None
    verdict: ReviewVerdict


__all__ = ["Airport", "LeadTimeBucket", "Route", "Source", "SourceReview"]
