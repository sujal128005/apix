"""Versioned methodology and weights.

Nothing published by APIx is reproducible unless the formulae and the weights
that produced it are pinned. Both are append-only: a correction is a new
version, never an edit to an old one.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from schemas.models.base import Entity


class MethodologyVersion(Entity):
    """A frozen set of index-computation parameters, identified by semver."""

    __tablename__ = "methodology_version"

    version: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    effective_from: Mapped[date] = mapped_column(sa.Date, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    changelog: Mapped[str] = mapped_column(sa.Text, nullable=False)


class WeightSetVersion(Entity):
    """A frozen set of route weights, identified by version string."""

    __tablename__ = "weight_set_version"

    version: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    effective_from: Mapped[date] = mapped_column(sa.Date, nullable=False)
    source_note: Mapped[str] = mapped_column(sa.Text, nullable=False)



class BasePeriod(Entity):
    """The reference period an index level is chained back to.

    A published index value means nothing without the period it is 100 against,
    so the period is a stored definition rather than a constant in code.
    ``index_observation.base_period_id`` points here.

    Unlike the other versioned definitions, this table is **mutable** (architect
    ruling, Phase 3 review round 2). A base period is a definition, not an
    observation: Phase 9 establishes it from real collection dates and may need
    to refine it before anything is published. Reproducibility is not weakened by
    that, because the two things that pin a published value are immutable -
    ``index_observation`` is append-only, so the ``base_period_id`` it recorded
    can never be repointed, and ``methodology_version`` is frozen alongside it.

    Ships empty: inventing a base period now would put a fabricated reference
    point under every future index value.
    """

    __tablename__ = "base_period"

    code: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    start_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    end_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    methodology_version_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("methodology_version.id", name="fk_base_period_methodology_version_id"),
        nullable=False,
    )

    __table_args__ = (
        sa.CheckConstraint("end_date > start_date", name="ck_base_period_dates_ordered"),
    )


class RouteWeight(Entity):
    """One route's share of the headline basket, within one weight set.

    This table is deliberately EMPTY after seeding. Weight evidence is open
    item O-5 and is unresolved; a placeholder weight would be indistinguishable
    from a sourced one in every downstream artefact, which is precisely the
    failure this project exists to avoid.

    evidence_rung and evidence_ref are NOT NULL so that a weight cannot exist
    without saying where it came from. Per weight set, the weights must sum to
    1 within 1e-9; that is enforced by a DEFERRABLE constraint trigger
    (migration 0002) which fires at COMMIT, so a set can be inserted row by row.
    """

    __tablename__ = "route_weight"

    route_id: Mapped[UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("route.id", name="fk_route_weight_route_id"), nullable=False
    )
    weight: Mapped[Decimal] = mapped_column(sa.Numeric(10, 8), nullable=False)
    evidence_rung: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    evidence_ref: Mapped[str] = mapped_column(sa.Text, nullable=False)
    evidence_retrieved_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    weight_set_version_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("weight_set_version.id", name="fk_route_weight_weight_set_version_id"),
        nullable=False,
    )

    __table_args__ = (
        sa.CheckConstraint("weight > 0 AND weight <= 1", name="ck_route_weight_weight_range"),
        sa.CheckConstraint(
            "evidence_rung BETWEEN 1 AND 4", name="ck_route_weight_evidence_rung_range"
        ),
        sa.UniqueConstraint("route_id", "weight_set_version_id", name="uq_route_weight_route_set"),
    )


__all__ = ["BasePeriod", "MethodologyVersion", "RouteWeight", "WeightSetVersion"]
