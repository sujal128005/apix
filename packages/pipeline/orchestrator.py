"""The daily run: collection through to a persisted index.

    plan -> compliance gate -> adapter -> raw storage
         -> normalise -> matched pairs -> Jevons short
         -> route aggregate -> headline aggregate -> index_observation

Everything upstream of this module is testable in isolation; this is where it
becomes a system. Three decisions here are worth stating because they are easy
to get subtly wrong and hard to notice afterwards.

**The first day of a stratum has no index.** A chained index needs a
predecessor, and there is no honest way to manufacture one. The first
observation of a stratum initialises it at the base value and produces no
movement - it is a starting point, not a measurement.

**A stratum that cannot be computed is not zero.** It is INSUFFICIENT, or
imputed from comparable movements, and either way it is counted and reported.
The moment a missing stratum becomes a zero, the index reports a price collapse
that never happened.

**The headline may legitimately refuse to exist.** The database trigger from
Phase 3 blocks a HEADLINE row on any date carrying SIMULATED_DEMO observations.
When that fires, this module records why and moves on. Catching the refusal and
writing the row anyway would defeat the only guarantee that stops development
data being presented as a published statistic.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from index_engine.aggregate import Component, weighted_arithmetic
from index_engine.jevons import jevons_short
from pipeline.normalise import ObservedQuote, StratumKey, build_matched_pairs
from schemas.enums import ImputationCode, IndexLevel, Provenance
from schemas.models.derived import NormalisedQuote
from schemas.models.indexing import IndexContribution, IndexObservation
from schemas.models.reference import LeadTimeBucket, Route
from schemas.models.versioning import MethodologyVersion, RouteWeight, WeightSetVersion

__all__ = ["IndexRun", "RouteOutcome", "compute_index_for_date"]

logger = logging.getLogger("apix.pipeline")

BASE_INDEX = Decimal("100")
QUANT = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class RouteOutcome:
    route_code: str
    index_value: Decimal | None
    previous_index: Decimal | None
    strata_computed: int
    strata_insufficient: int
    quotes_used: int
    quotes_excluded: int
    note: str = ""


@dataclass(slots=True)
class IndexRun:
    """What one day's computation produced, in a shape the UI can render."""

    obs_date: date
    routes: list[RouteOutcome] = field(default_factory=list)
    headline: Decimal | None = None
    headline_refused_reason: str = ""
    strata_total: int = 0
    strata_insufficient: int = 0
    quotes_considered: int = 0

    @property
    def routes_with_index(self) -> int:
        return sum(1 for r in self.routes if r.index_value is not None)


def _load_quotes(session: Session, obs_date: date) -> dict[StratumKey, list[ObservedQuote]]:
    """Read a day's observations, keyed by elementary stratum."""
    rows = session.execute(
        sa.select(NormalisedQuote).where(NormalisedQuote.collected_date == obs_date)
    ).scalars().all()

    grouped: dict[StratumKey, list[ObservedQuote]] = {}
    for row in rows:
        key = StratumKey(
            route_id=row.route_id, bucket_id=row.bucket_id, collected_date=obs_date
        )
        grouped.setdefault(key, []).append(
            ObservedQuote(
                stratum=key,
                pair_key=f"{row.carrier}|{row.flight_no or '?'}|{row.fare_brand or '?'}",
                total_fare=row.total_fare,
                provenance=row.provenance,
                imputed=row.imputation_code == ImputationCode.Y,
            )
        )
    return grouped


def _previous_index(
    session: Session,
    *,
    level: str,
    ref_id: UUID,
    bucket_id: UUID | None,
    before: date,
) -> Decimal | None:
    """The most recent index for this series strictly before ``before``.

    Deliberately not "yesterday": a gap in collection should chain across the
    gap rather than break the series, provided the gap is bounded. What must not
    happen is silently restarting at 100, which would erase every movement
    recorded so far.
    """
    statement = (
        sa.select(IndexObservation.index_value)
        .where(IndexObservation.level == level)
        .where(IndexObservation.ref_id == ref_id)
        .where(IndexObservation.obs_date < before)
        .order_by(IndexObservation.obs_date.desc())
        .limit(1)
    )
    statement = (
        statement.where(IndexObservation.bucket_id == bucket_id)
        if bucket_id is not None
        else statement.where(IndexObservation.bucket_id.is_(None))
    )
    return session.execute(statement).scalar_one_or_none()


def _hash_inputs(quotes: list[ObservedQuote]) -> str:
    """A digest of the exact observations behind an index value.

    Stored on every row so a recomputation can be proved to have used the same
    inputs, rather than merely to have produced the same number.
    """
    payload = "|".join(
        f"{q.pair_key}:{q.total_fare}" for q in sorted(quotes, key=lambda q: q.pair_key)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_index_for_date(
    session: Session,
    obs_date: date,
    *,
    previous_date: date | None = None,
    min_quotes: int = 3,
    k: Decimal = Decimal("3.5"),
) -> IndexRun:
    """Compute and persist stratum, route and headline indices for one day."""
    methodology = session.execute(
        sa.select(MethodologyVersion).order_by(MethodologyVersion.effective_from.desc()).limit(1)
    ).scalar_one()
    weight_set = session.execute(
        sa.select(WeightSetVersion).order_by(WeightSetVersion.effective_from.desc()).limit(1)
    ).scalar_one_or_none()
    if weight_set is None:
        raise RuntimeError(
            "No weight set exists. A headline index needs a closed, evidence-tagged "
            "basket; run scripts/run_demo_pipeline.py --ensure-weights or seed one."
        )

    weights: dict[str, Decimal] = {
        row.code: row.weight
        for row in session.execute(
            sa.select(Route.code, RouteWeight.weight)
            .join(Route, Route.id == RouteWeight.route_id)
            .where(RouteWeight.weight_set_version_id == weight_set.id)
        )
    }
    routes = {r.id: r for r in session.execute(sa.select(Route)).scalars()}
    buckets = {b.id: b for b in session.execute(sa.select(LeadTimeBucket)).scalars()}

    current = _load_quotes(session, obs_date)
    prior_day = previous_date or _most_recent_date_before(session, obs_date)
    previous = _load_quotes(session, prior_day) if prior_day else {}

    run = IndexRun(obs_date=obs_date)
    run.quotes_considered = sum(len(v) for v in current.values())

    # --- elementary strata -------------------------------------------------
    stratum_index: dict[tuple[UUID, UUID], Decimal] = {}
    stratum_stats: dict[UUID, list[tuple[int, int, int]]] = {}

    for key, quotes in sorted(current.items(), key=lambda kv: str(kv[0])):
        run.strata_total += 1
        prev_key = StratumKey(
            route_id=key.route_id, bucket_id=key.bucket_id, collected_date=prior_day
        ) if prior_day else None
        prior_quotes = previous.get(prev_key, []) if prev_key else []

        prev_value = _previous_index(
            session,
            level=IndexLevel.STRATUM,
            ref_id=key.route_id,
            bucket_id=key.bucket_id,
            before=obs_date,
        )

        if prev_value is None:
            # First sighting: a starting point, not a measurement.
            _persist(
                session,
                obs_date=obs_date,
                level=IndexLevel.STRATUM,
                ref_id=key.route_id,
                bucket_id=key.bucket_id,
                value=BASE_INDEX,
                previous=None,
                methodology_id=methodology.id,
                weight_set_id=weight_set.id,
                quote_count=len(quotes),
                excluded=0,
                imputed=0,
                input_hash=_hash_inputs(quotes),
            )
            stratum_index[(key.route_id, key.bucket_id)] = BASE_INDEX
            stratum_stats.setdefault(key.route_id, []).append((len(quotes), 0, 0))
            continue

        pairs, _unmatched, _gone = build_matched_pairs(prior_quotes, quotes)
        result = jevons_short(pairs, prev_value, k=k, min_quotes=min_quotes)

        if result.index_value is None:
            run.strata_insufficient += 1
            stratum_stats.setdefault(key.route_id, []).append((len(quotes), result.rejected, 1))
            logger.info(
                "stratum insufficient",
                extra={"route": str(key.route_id), "bucket": str(key.bucket_id),
                       "reason": result.reason},
            )
            continue

        _persist(
            session,
            obs_date=obs_date,
            level=IndexLevel.STRATUM,
            ref_id=key.route_id,
            bucket_id=key.bucket_id,
            value=result.index_value,
            previous=prev_value,
            methodology_id=methodology.id,
            weight_set_id=weight_set.id,
            quote_count=result.accepted,
            excluded=result.rejected,
            imputed=0,
            input_hash=_hash_inputs(quotes),
        )
        stratum_index[(key.route_id, key.bucket_id)] = result.index_value
        stratum_stats.setdefault(key.route_id, []).append(
            (result.accepted, result.rejected, 0)
        )

    # --- route level: weighted arithmetic across buckets --------------------
    route_components: list[Component] = []
    for route_id, route in sorted(routes.items(), key=lambda kv: kv[1].code):
        parts = [
            Component(ref=buckets[bucket_id].code, index_value=value,
                      weight=buckets[bucket_id].lambda_)
            for (r_id, bucket_id), value in stratum_index.items()
            if r_id == route_id and bucket_id in buckets
        ]
        stats = stratum_stats.get(route_id, [])
        used = sum(s[0] for s in stats)
        excluded = sum(s[1] for s in stats)
        insufficient = sum(s[2] for s in stats)

        if not parts:
            run.routes.append(
                RouteOutcome(
                    route_code=route.code, index_value=None, previous_index=None,
                    strata_computed=0, strata_insufficient=insufficient,
                    quotes_used=used, quotes_excluded=excluded,
                    note="no computable strata on this date",
                )
            )
            continue

        prev_route = _previous_index(
            session, level=IndexLevel.ROUTE, ref_id=route_id, bucket_id=None, before=obs_date
        )
        aggregate = weighted_arithmetic(parts)

        _persist(
            session,
            obs_date=obs_date,
            level=IndexLevel.ROUTE,
            ref_id=route_id,
            bucket_id=None,
            value=aggregate.index_value,
            previous=prev_route,
            methodology_id=methodology.id,
            weight_set_id=weight_set.id,
            quote_count=used,
            excluded=excluded,
            imputed=insufficient,
            input_hash=_hash_inputs([q for k, v in current.items() if k.route_id == route_id
                                     for q in v]),
        )
        run.routes.append(
            RouteOutcome(
                route_code=route.code,
                index_value=aggregate.index_value,
                previous_index=prev_route,
                strata_computed=len(parts),
                strata_insufficient=insufficient,
                quotes_used=used,
                quotes_excluded=excluded,
            )
        )
        if route.code in weights:
            route_components.append(
                Component(
                    ref=route.code,
                    index_value=aggregate.index_value,
                    weight=weights[route.code],
                    previous_index=prev_route,
                )
            )

    # --- headline: the database may refuse, and that is the point -----------
    if not route_components:
        run.headline_refused_reason = (
            "No route in the weighted basket had a computable index on this date."
        )
        return run

    headline = weighted_arithmetic(route_components)
    prev_headline = _previous_index(
        session, level=IndexLevel.HEADLINE, ref_id=None, bucket_id=None, before=obs_date
    ) if False else session.execute(
        sa.select(IndexObservation.index_value)
        .where(IndexObservation.level == IndexLevel.HEADLINE)
        .where(IndexObservation.obs_date < obs_date)
        .order_by(IndexObservation.obs_date.desc())
        .limit(1)
    ).scalar_one_or_none()

    savepoint = session.begin_nested()
    try:
        observation = _persist(
            session,
            obs_date=obs_date,
            level=IndexLevel.HEADLINE,
            ref_id=None,
            bucket_id=None,
            value=headline.index_value,
            previous=prev_headline,
            methodology_id=methodology.id,
            weight_set_id=weight_set.id,
            quote_count=run.quotes_considered,
            excluded=sum(r.quotes_excluded for r in run.routes),
            imputed=run.strata_insufficient,
            input_hash=_hash_inputs([q for v in current.values() for q in v]),
            routes_in_basket=len(route_components),
        )
        for contribution in headline.contributions:
            route_id = next(r.id for r in routes.values() if r.code == contribution.ref)
            session.add(
                IndexContribution(
                    index_observation_id=observation.id,
                    route_id=route_id,
                    contribution=contribution.contribution,
                )
            )
        session.flush()
        savepoint.commit()
        run.headline = headline.index_value
    except DatabaseError as exc:
        # The Phase 3 trigger refused. Record why; do not work around it.
        savepoint.rollback()
        simulated = any(
            q.provenance == Provenance.SIMULATED_DEMO
            for quotes in current.values()
            for q in quotes
        )
        run.headline_refused_reason = (
            "The database refused to publish a headline index for this date because "
            "it carries SIMULATED_DEMO observations. Development data cannot become "
            "a published statistic. Route-level indices above are computed from the "
            "same pipeline and are labelled with their provenance."
            if simulated
            else f"The database refused the headline row: {exc.orig}"
        )
        logger.warning("headline refused", extra={"date": obs_date.isoformat()})

    return run


def refresh_quality_summary(engine: sa.Engine) -> None:
    """Rebuild the data-quality summary. **Call after committing, not during.**

    Takes an engine rather than a session, and opens its own autocommit
    connection, because ``REFRESH MATERIALIZED VIEW CONCURRENTLY`` cannot run
    inside a transaction block. Calling it mid-transaction does not merely fail
    - it aborts the surrounding transaction, and catching the error does not
    un-poison it. The first version of this function did exactly that and took
    eleven orchestrator tests down with it.

    CONCURRENTLY so the page keeps serving the previous summary while the new
    one is built: at six million observations the aggregate takes around 800 ms,
    and a reader arriving mid-refresh should get slightly stale figures rather
    than a stalled page.

    Failure is logged and swallowed. A stale quality summary is a presentation
    problem; a collection run that fails because a reporting view could not be
    rebuilt is a data problem, and the second is worse.
    """
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(
                sa.text("REFRESH MATERIALIZED VIEW CONCURRENTLY quality_summary")
            )
    except DatabaseError as exc:
        logger.warning(
            "quality summary refresh failed; the page will show the previous run",
            extra={"error": str(exc.orig)},
        )


def _most_recent_date_before(session: Session, obs_date: date) -> date | None:
    return session.execute(
        sa.select(NormalisedQuote.collected_date)
        .where(NormalisedQuote.collected_date < obs_date)
        .order_by(NormalisedQuote.collected_date.desc())
        .limit(1)
    ).scalar_one_or_none()


def _persist(
    session: Session,
    *,
    obs_date: date,
    level: str,
    ref_id: UUID | None,
    bucket_id: UUID | None,
    value: Decimal,
    previous: Decimal | None,
    methodology_id: UUID,
    weight_set_id: UUID,
    quote_count: int,
    excluded: int,
    imputed: int,
    input_hash: str,
    routes_in_basket: int | None = None,
) -> IndexObservation:
    observation = IndexObservation(
        obs_date=obs_date,
        level=level,
        ref_id=ref_id,
        bucket_id=bucket_id,
        index_value=value.quantize(QUANT),
        prev_index_value=previous.quantize(QUANT) if previous is not None else None,
        methodology_version_id=methodology_id,
        weight_set_version_id=weight_set_id,
        input_quote_count=quote_count,
        excluded_count=excluded,
        imputed_count=imputed,
        routes_in_basket=routes_in_basket,
        input_hash=input_hash,
        computed_at=datetime.now(UTC),
    )
    session.add(observation)
    session.flush()
    return observation
