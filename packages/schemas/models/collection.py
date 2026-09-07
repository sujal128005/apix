"""Collection: jobs, requests, compliance decisions and raw payloads.

Everything downstream of raw_response is derived. Everything in this module
except collection_job is append-only, because it is the evidence trail: if a
raw payload or a compliance decision could be edited, no published number would
be defensible.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from schemas.enums import ComplianceDecisionCode, JobStatus
from schemas.models.base import Entity, enum_check


class CollectionJob(Entity):
    """One scheduled collection run. Mutable: counters advance as it progresses."""

    __tablename__ = "collection_job"

    started_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(sa.Text, nullable=False)
    requests_total: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    requests_ok: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    requests_blocked: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    parse_failures: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )

    __table_args__ = (
        enum_check("collection_job", "status", JobStatus),
        sa.Index("ix_collection_job_started_at", sa.text("started_at DESC")),
    )


class CollectionRequest(Entity):
    """One intended search: source x route x bucket x travel date x collection date.

    query_hash is the sha256 of that identity (see schemas.hashing) and is
    unique, so the same search cannot be issued twice.
    """

    __tablename__ = "collection_request"

    job_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("collection_job.id", name="fk_collection_request_job_id"),
        nullable=False,
    )
    source_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("source.id", name="fk_collection_request_source_id"),
        nullable=False,
    )
    route_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("route.id", name="fk_collection_request_route_id"),
        nullable=False,
    )
    bucket_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("lead_time_bucket.id", name="fk_collection_request_bucket_id"),
        nullable=False,
    )
    travel_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    collected_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    query_hash: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)

    __table_args__ = (
        # Travel is strictly after collection. Every lead-time bucket has
        # days >= 1, so travel_date > collected_date always holds and the
        # tighter form is the correct one (architect ruling, Phase 3 review).
        sa.CheckConstraint(
            "travel_date > collected_date",
            name="ck_collection_request_travel_after_collected",
        ),
    )


class ComplianceDecision(Entity):
    """The gate verdict for one attempted fetch, with the evidence behind it.

    Written for allowed and refused fetches alike. BLOCKED_ROBOTS rows are the
    proof that the crawler respected a disallow, not an error log.
    """

    __tablename__ = "compliance_decision"

    source_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("source.id", name="fk_compliance_decision_source_id"),
        nullable=False,
    )
    request_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("collection_request.id", name="fk_compliance_decision_request_id"),
        nullable=True,
    )
    path: Mapped[str] = mapped_column(sa.Text, nullable=False)
    user_agent: Mapped[str] = mapped_column(sa.Text, nullable=False)
    robots_sha256: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    matched_rule: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    decision: Mapped[str] = mapped_column(sa.Text, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)

    __table_args__ = (
        enum_check("compliance_decision", "decision", ComplianceDecisionCode),
        sa.Index(
            "ix_compliance_decision_source_decided",
            "source_id",
            sa.text("decided_at DESC"),
        ),
    )


class RawResponse(Entity):
    """A stored payload, referenced by location and content hash.

    payload_ref points at the archived bytes; sha256 fixes their content so a
    re-run can prove it read the same bytes. http_status is nullable because a
    transport failure produces no status at all.
    """

    __tablename__ = "raw_response"

    request_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("collection_request.id", name="fk_raw_response_request_id"),
        nullable=False,
    )
    payload_ref: Mapped[str] = mapped_column(sa.Text, nullable=False)
    sha256: Mapped[str] = mapped_column(sa.Text, nullable=False)
    http_status: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)

    __table_args__ = (
        sa.UniqueConstraint("request_id", "sha256", name="uq_raw_response_request_sha256"),
    )


class RawQuote(Entity):
    """One fare offer as it appeared in a raw payload, before any normalisation."""

    __tablename__ = "raw_quote"

    raw_response_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("raw_response.id", name="fk_raw_quote_raw_response_id"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        sa.UniqueConstraint("raw_response_id", "ordinal", name="uq_raw_quote_response_ordinal"),
    )


__all__ = [
    "CollectionJob",
    "CollectionRequest",
    "ComplianceDecision",
    "RawQuote",
    "RawResponse",
]
