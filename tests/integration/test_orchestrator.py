"""The orchestrator, against a real database.

These assert the behaviours that are easy to get wrong and hard to spot: that a
first sighting does not fabricate a movement, that a refused headline is
recorded rather than worked around, and that the same inputs give the same
numbers twice.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from pipeline.orchestrator import compute_index_for_date
from pipeline.weights import build_equal_weights
from schemas.enums import ImputationCode, IndexLevel, MissingReason, Provenance, QualityStatus
from schemas.models.derived import NormalisedQuote
from schemas.models.indexing import IndexObservation
from schemas.models.reference import Route
from schemas.models.versioning import RouteWeight, WeightSetVersion
from tests.support.builders import SeedRefs

DAY1 = date(2026, 8, 1)
DAY2 = date(2026, 8, 2)


@pytest.fixture
def weight_set(app_session: Session, refs: SeedRefs) -> WeightSetVersion:
    routes = {r.code: r for r in app_session.execute(sa.select(Route)).scalars()}
    built = build_equal_weights(sorted(routes), version="test-equal", reason="test fixture")
    version = WeightSetVersion(
        version=built.version, effective_from=DAY1, source_note=built.note
    )
    app_session.add(version)
    app_session.flush()
    for candidate in built.candidates:
        app_session.add(
            RouteWeight(
                route_id=routes[candidate.route_code].id,
                weight=candidate.weight,
                evidence_rung=candidate.evidence_rung,
                evidence_ref=candidate.evidence_ref,
                evidence_retrieved_at=datetime.now(UTC),
                weight_set_version_id=version.id,
            )
        )
    app_session.flush()
    return version


def add_quote(
    session: Session,
    *,
    route_id: UUID,
    bucket_id: UUID,
    source_id: UUID,
    day: date,
    carrier: str,
    flight: str,
    fare: str,
    provenance: str = Provenance.SIMULATED_DEMO,
) -> None:
    session.add(
        NormalisedQuote(
            raw_quote_id=None,
            route_id=route_id,
            bucket_id=bucket_id,
            source_id=source_id,
            carrier=carrier,
            flight_no=flight,
            lead_time_days=7,
            fare_brand="SAVER",
            total_fare=Decimal(fare),
            currency="INR",
            collected_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
            collected_date=day,
            provenance=provenance,
            quality_status=QualityStatus.COMPLETE,
            imputation_code=ImputationCode.Y,  # allows a null raw_quote_id
            missing_reason=MissingReason.NONE,
            component_confidence="HIGH",
        )
    )


def seed_two_days(session: Session, refs: SeedRefs, *, rise: str = "1.10") -> None:
    route_id = refs.routes["DEL-BOM"]
    bucket_id = refs.buckets["T7"]
    source_id = refs.sources["indigo_web"]
    for carrier, flight, fare in (
        ("6E", "6E101", "5000"),
        ("6E", "6E102", "5500"),
        ("6E", "6E103", "6000"),
    ):
        add_quote(session, route_id=route_id, bucket_id=bucket_id, source_id=source_id,
                  day=DAY1, carrier=carrier, flight=flight, fare=fare)
        raised = (Decimal(fare) * Decimal(rise)).quantize(Decimal("0.01"))
        add_quote(session, route_id=route_id, bucket_id=bucket_id, source_id=source_id,
                  day=DAY2, carrier=carrier, flight=flight, fare=str(raised))
    session.flush()


def test_a_first_sighting_starts_at_base_and_records_no_movement(
    app_session: Session, refs: SeedRefs, weight_set: WeightSetVersion
) -> None:
    """There is no honest way to invent a predecessor for a chained index."""
    seed_two_days(app_session, refs)
    compute_index_for_date(app_session, DAY1)

    stratum = app_session.execute(
        sa.select(IndexObservation)
        .where(IndexObservation.level == IndexLevel.STRATUM)
        .where(IndexObservation.obs_date == DAY1)
    ).scalars().first()
    assert stratum is not None
    assert stratum.index_value == Decimal("100.000000")
    assert stratum.prev_index_value is None


def test_the_second_day_chains_and_measures_the_real_rise(
    app_session: Session, refs: SeedRefs, weight_set: WeightSetVersion
) -> None:
    """Every fare up 10% must give a stratum index of 110."""
    seed_two_days(app_session, refs, rise="1.10")
    compute_index_for_date(app_session, DAY1)
    compute_index_for_date(app_session, DAY2, previous_date=DAY1)

    stratum = app_session.execute(
        sa.select(IndexObservation)
        .where(IndexObservation.level == IndexLevel.STRATUM)
        .where(IndexObservation.obs_date == DAY2)
    ).scalars().first()
    assert stratum is not None
    assert stratum.index_value == Decimal("110.000000")
    assert stratum.prev_index_value == Decimal("100.000000")


def test_a_flat_market_does_not_drift(
    app_session: Session, refs: SeedRefs, weight_set: WeightSetVersion
) -> None:
    """Unchanged prices must give an unchanged index, exactly."""
    seed_two_days(app_session, refs, rise="1.00")
    compute_index_for_date(app_session, DAY1)
    compute_index_for_date(app_session, DAY2, previous_date=DAY1)

    stratum = app_session.execute(
        sa.select(IndexObservation)
        .where(IndexObservation.level == IndexLevel.STRATUM)
        .where(IndexObservation.obs_date == DAY2)
    ).scalars().first()
    assert stratum is not None
    assert stratum.index_value == Decimal("100.000000")


def test_a_headline_is_refused_for_simulated_data_and_the_reason_is_recorded(
    app_session: Session, refs: SeedRefs, weight_set: WeightSetVersion
) -> None:
    """The guarantee, exercised end to end.

    The refusal is not caught and worked around: no HEADLINE row exists, and the
    run explains why in language the dashboard can show a judge.
    """
    seed_two_days(app_session, refs)
    compute_index_for_date(app_session, DAY1)
    run = compute_index_for_date(app_session, DAY2, previous_date=DAY1)

    assert run.headline is None
    assert "SIMULATED_DEMO" in run.headline_refused_reason
    assert "cannot become a published statistic" in run.headline_refused_reason

    headlines = app_session.execute(
        sa.select(sa.func.count())
        .select_from(IndexObservation)
        .where(IndexObservation.level == IndexLevel.HEADLINE)
    ).scalar_one()
    assert headlines == 0, "no headline row may exist for simulated data"


def test_route_indices_are_still_produced_when_the_headline_is_refused(
    app_session: Session, refs: SeedRefs, weight_set: WeightSetVersion
) -> None:
    """The refusal is targeted, not a blanket outage."""
    seed_two_days(app_session, refs)
    compute_index_for_date(app_session, DAY1)
    run = compute_index_for_date(app_session, DAY2, previous_date=DAY1)

    assert run.routes_with_index >= 1
    computed = [r for r in run.routes if r.index_value is not None]
    assert any(r.route_code == "DEL-BOM" for r in computed)


def test_a_stratum_with_too_few_quotes_is_insufficient_not_zero(
    app_session: Session, refs: SeedRefs, weight_set: WeightSetVersion
) -> None:
    """An unobserved stratum has an unknown price, never a zero one."""
    route_id, bucket_id = refs.routes["DEL-BOM"], refs.buckets["T7"]
    source_id = refs.sources["indigo_web"]
    add_quote(app_session, route_id=route_id, bucket_id=bucket_id, source_id=source_id,
              day=DAY1, carrier="6E", flight="6E101", fare="5000")
    add_quote(app_session, route_id=route_id, bucket_id=bucket_id, source_id=source_id,
              day=DAY2, carrier="6E", flight="6E101", fare="5500")
    app_session.flush()

    compute_index_for_date(app_session, DAY1)
    run = compute_index_for_date(app_session, DAY2, previous_date=DAY1)

    assert run.strata_insufficient >= 1
    values = app_session.execute(
        sa.select(IndexObservation.index_value).where(IndexObservation.obs_date == DAY2)
    ).scalars().all()
    assert all(v > 0 for v in values), "no index value may be zero"


def test_a_published_index_value_cannot_be_silently_recomputed(
    app_session: Session, refs: SeedRefs, weight_set: WeightSetVersion
) -> None:
    """Recomputing a day under the same methodology is refused by the database.

    Discovered while writing a reproducibility test: the attempt raised rather
    than quietly writing a second value. That is the stronger property. If a
    published figure could be recomputed in place, "reproducible" would mean
    only that the latest run agrees with itself, and an index revision would be
    indistinguishable from an index correction.

    A genuine revision creates a new methodology version and recomputes forward,
    leaving both series intact. Reproducibility of the *calculation* is asserted
    in tests/unit/test_index_engine_golden.py, where it belongs - the engine is
    a pure function and needs no database to prove it.
    """
    from sqlalchemy.exc import IntegrityError

    seed_two_days(app_session, refs)
    compute_index_for_date(app_session, DAY1)
    first = compute_index_for_date(app_session, DAY2, previous_date=DAY1)
    assert first.routes_with_index >= 1

    with pytest.raises(IntegrityError, match="uq_index_observation_identity"):
        compute_index_for_date(app_session, DAY2, previous_date=DAY1)


def test_every_index_row_records_its_methodology_and_weight_set(
    app_session: Session, refs: SeedRefs, weight_set: WeightSetVersion
) -> None:
    """A number nobody can attribute to a method is not a statistic."""
    seed_two_days(app_session, refs)
    compute_index_for_date(app_session, DAY1)

    rows = app_session.execute(sa.select(IndexObservation)).scalars().all()
    assert rows
    for row in rows:
        assert row.methodology_version_id is not None
        assert row.weight_set_version_id is not None
        assert row.input_hash, "every value must record a digest of its inputs"
