"""The index itself, its per-route contributions, and the external benchmarks.

index_observation is chained: every value depends on its predecessor, which is
why prev_index_value is stored alongside index_value rather than recomputed.
input_hash pins the exact input set so a value can be reproduced bit for bit.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from schemas.enums import IndexLevel
from schemas.models.base import Entity, enum_check


class IndexObservation(Entity):
    """One computed index value at one level, on one date.

    STRATUM values are Jevons short (chain-base, geometric mean of price
    relatives). ROUTE and HEADLINE values are Young / modified Laspeyres
    (weighted arithmetic mean). Geometric below, arithmetic above: that is
    MoSPI's structure, not a stylistic choice.

    A BEFORE INSERT trigger (migration 0002) refuses any HEADLINE row whose
    contributing quote set contains SIMULATED_DEMO provenance.
    """

    __tablename__ = "index_observation"

    obs_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    level: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # Route id for ROUTE level, stratum reference for STRATUM level, NULL for
    # HEADLINE. Deliberately not a foreign key: it points at different tables
    # depending on level.
    ref_id: Mapped[UUID | None] = mapped_column(sa.Uuid(), nullable=True)
    bucket_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("lead_time_bucket.id", name="fk_index_observation_bucket_id"),
        nullable=True,
    )
    index_value: Mapped[Decimal] = mapped_column(sa.Numeric(12, 6), nullable=False)
    prev_index_value: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 6), nullable=True)
    base_period_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("base_period.id", name="fk_index_observation_base_period_id"),
        nullable=True,
    )
    methodology_version_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("methodology_version.id", name="fk_index_observation_methodology_version_id"),
        nullable=False,
    )
    weight_set_version_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("weight_set_version.id", name="fk_index_observation_weight_set_version_id"),
        nullable=False,
    )
    input_quote_count: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    excluded_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    imputed_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    routes_in_basket: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    revision: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    """Which revision of this figure. 1 is the first computation.

    Part of the identity, so a correction for an already-published date creates
    revision 2 beside revision 1 rather than replacing it. Both are retained: a
    reader can always retrieve what was published at the time."""

    input_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)

    __table_args__ = (
        sa.CheckConstraint("index_value > 0", name="ck_index_observation_index_value_positive"),
        enum_check("index_observation", "level", IndexLevel),
        # NULLS NOT DISTINCT: ref_id and bucket_id are both NULL on a HEADLINE
        # row, and PostgreSQL's default treats NULLs as distinct - which would
        # let two headline values exist for the same date and methodology and
        # break the reproducibility guarantee the project rests on.
        sa.UniqueConstraint(
            "obs_date",
            "level",
            "ref_id",
            "bucket_id",
            "methodology_version_id",
            "revision",
            name="uq_index_observation_identity",
            postgresql_nulls_not_distinct=True,
        ),
        # Added from load-test measurement (revision 0007). At six million
        # observations the dashboard's latest-indices query and the route
        # explorer's history both scanned; these make them lookups.
        sa.Index("ix_index_observation_level_date", "level", "obs_date"),
        sa.Index("ix_index_observation_ref_date", "ref_id", "obs_date"),
    )


class IndexContribution(Entity):
    """How much one route contributed to one higher-level index value."""

    __tablename__ = "index_contribution"

    index_observation_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("index_observation.id", name="fk_index_contribution_index_observation_id"),
        nullable=False,
    )
    route_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("route.id", name="fk_index_contribution_route_id"),
        nullable=False,
    )
    contribution: Mapped[Decimal] = mapped_column(sa.Numeric(12, 6), nullable=False)

    __table_args__ = (
        sa.UniqueConstraint(
            "index_observation_id", "route_id", name="uq_index_contribution_obs_route"
        ),
    )


class BenchmarkObservation(Entity):
    """An external published figure APIx is compared against.

    citation_url is NOT NULL and non-empty: an uncited benchmark cannot exist,
    because a comparison no one can check is not evidence.
    """

    __tablename__ = "benchmark_observation"

    bench_source: Mapped[str] = mapped_column(sa.Text, nullable=False)
    period: Mapped[str] = mapped_column(sa.Text, nullable=False)
    ref: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    value: Mapped[Decimal] = mapped_column(sa.Numeric(14, 4), nullable=False)
    definition: Mapped[str] = mapped_column(sa.Text, nullable=False)
    citation_url: Mapped[str] = mapped_column(sa.Text, nullable=False)
    citation_page: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)

    __table_args__ = (
        sa.CheckConstraint("citation_url <> ''", name="ck_benchmark_observation_citation_present"),
    )


class BacktestRun(Entity):
    """One backtest execution and, mandatorily, what it cannot tell you.

    limitations is NOT NULL and non-empty. Every backtest in this project has
    them: there is no public DGCA fare time series to validate against, and a
    run that does not say so would be misleading.
    """

    __tablename__ = "backtest_run"

    window_start: Mapped[date] = mapped_column(sa.Date, nullable=False)
    window_end: Mapped[date] = mapped_column(sa.Date, nullable=False)
    tier: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    limitations: Mapped[str] = mapped_column(sa.Text, nullable=False)
    input_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    run_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)

    __table_args__ = (
        sa.CheckConstraint("tier BETWEEN 1 AND 3", name="ck_backtest_run_tier_range"),
        sa.CheckConstraint("limitations <> ''", name="ck_backtest_run_limitations_present"),
    )


class Publication(Entity):
    """The release lifecycle of one computed index value.

    Separate from ``index_observation`` because that table is append-only and
    this state moves. Keeping them apart means the *figure* cannot change while
    its *status* does - which is the property that makes a revision
    distinguishable from a correction after the fact.
    """

    __tablename__ = "publication"

    index_observation_id: Mapped[UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("index_observation.id"), nullable=False, unique=True
    )
    state: Mapped[str] = mapped_column(sa.Text, nullable=False, default="PENDING")
    approved_by: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    scheduled_release_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    supersedes_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid(), sa.ForeignKey("index_observation.id"), nullable=True
    )
    revision_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    withdrawn_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    __table_args__ = (
        sa.CheckConstraint(
            "state IN ('PENDING','APPROVED','PUBLISHED','WITHDRAWN')",
            name="ck_publication_state",
        ),
        sa.CheckConstraint(
            "state = 'PENDING' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_publication_approval_is_attributed",
        ),
        sa.CheckConstraint(
            "supersedes_id IS NULL OR revision_reason IS NOT NULL",
            name="ck_publication_revision_has_reason",
        ),
        sa.CheckConstraint(
            "state <> 'WITHDRAWN' OR withdrawn_reason IS NOT NULL",
            name="ck_publication_withdrawal_has_reason",
        ),
        sa.Index("ix_publication_state", "state"),
        sa.Index("ix_publication_published_at", "published_at"),
    )


__all__ = [
    "BacktestRun",
    "BenchmarkObservation",
    "IndexContribution",
    "IndexObservation",
    "Publication",
]
