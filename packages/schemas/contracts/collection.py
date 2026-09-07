"""Contracts for collection jobs, requests, compliance decisions and raw payloads."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from schemas.contracts.base import ApixContract, NonEmptyText, Sha256Hex, Utc
from schemas.enums import ComplianceDecisionCode, JobStatus


class CollectionJob(ApixContract):
    """collection_job"""

    started_at: Utc
    finished_at: Utc | None = None
    status: JobStatus
    requests_total: int = Field(ge=0)
    requests_ok: int = Field(ge=0)
    requests_blocked: int = Field(ge=0)
    parse_failures: int = Field(ge=0)


class CollectionRequest(ApixContract):
    """collection_request - one intended search, uniquely identified by query_hash."""

    job_id: UUID
    source_id: UUID
    route_id: UUID
    bucket_id: UUID
    travel_date: date
    collected_date: date
    query_hash: Sha256Hex

    @model_validator(mode="after")
    def travel_not_before_collection(self) -> CollectionRequest:
        """Mirror ck_collection_request_travel_not_before_collected at the boundary."""
        if self.travel_date < self.collected_date:
            raise ValueError(
                f"travel_date {self.travel_date} precedes collected_date {self.collected_date}: "
                "a fare quoted on a given day cannot be for a departure before it"
            )
        return self


class ComplianceDecision(ApixContract):
    """compliance_decision"""

    source_id: UUID
    request_id: UUID | None = None
    path: NonEmptyText
    user_agent: NonEmptyText
    robots_sha256: Sha256Hex | None = None
    matched_rule: str | None = None
    decision: ComplianceDecisionCode
    decided_at: Utc


class RawResponse(ApixContract):
    """raw_response"""

    request_id: UUID
    payload_ref: NonEmptyText
    sha256: Sha256Hex
    http_status: int | None = None
    fetched_at: Utc


class RawQuote(ApixContract):
    """raw_quote"""

    raw_response_id: UUID
    ordinal: int = Field(ge=0)
    payload: dict[str, Any]


__all__ = [
    "CollectionJob",
    "CollectionRequest",
    "ComplianceDecision",
    "RawQuote",
    "RawResponse",
]
