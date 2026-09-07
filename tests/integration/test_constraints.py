"""The five constraints the phase exists to prove, each by provoking a failure.

C1  route_weight.evidence_rung is NOT NULL
C2  weights sum to 1 +/- 1e-9 per weight set, checked at COMMIT
C3  the append-only tables cannot be updated or deleted (test_roles_and_privileges)
C4  total_fare > 0 and provenance is NOT NULL
C5  SIMULATED_DEMO can never reach a headline index value

A passing assertion here means PostgreSQL refused bad data. None of these are
enforced by application code that a future caller could route around.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from schemas.enums import IndexLevel, Provenance
from schemas.models import RouteWeight
from schemas.uuid7 import uuid7
from tests.support.builders import (
    SeedRefs,
    add_contribution,
    add_quote,
    add_route_weight,
    build_collection,
    make_base_period,
    make_index_observation,
    make_weight_set,
    utc,
)

pytestmark = [pytest.mark.integration, pytest.mark.constraint]

EFFECTIVE_FROM = date(2026, 1, 1)
FOUR_ROUTES = ("DEL-BOM", "BOM-DEL", "DEL-BLR", "BLR-DEL")


def new_weight_set(session: Session, name: str):
    return make_weight_set(
        session,
        version=f"test_weight_set_{name}",
        effective_from=EFFECTIVE_FROM,
        source_note="synthetic weight set built inside a test; never sourced evidence",
    )


# ===========================================================================
# C1 - a weight cannot exist without stating its evidence
# ===========================================================================
def test_c1_weight_without_evidence_rung_is_rejected(
    app_session: Session, refs: SeedRefs
) -> None:
    weight_set = new_weight_set(app_session, "c1")

    with pytest.raises(IntegrityError) as caught, app_session.begin_nested():
        add_route_weight(
            app_session,
            refs,
            weight_set,
            route_code="DEL-BOM",
            weight=Decimal("1.00000000"),
            evidence_rung=None,
        )
        app_session.flush()

    assert "evidence_rung" in str(caught.value)


def test_c1_evidence_rung_outside_one_to_four_is_rejected(
    app_session: Session, refs: SeedRefs
) -> None:
    weight_set = new_weight_set(app_session, "c1_range")

    with (
        pytest.raises(IntegrityError, match="ck_route_weight_evidence_rung_range"),
        app_session.begin_nested(),
    ):
        add_route_weight(
            app_session,
            refs,
            weight_set,
            route_code="DEL-BOM",
            weight=Decimal("1.00000000"),
            evidence_rung=5,
        )
        app_session.flush()


def test_c1_a_fully_evidenced_weight_is_accepted(
    app_session: Session, refs: SeedRefs
) -> None:
    weight_set = new_weight_set(app_session, "c1_ok")
    add_route_weight(
        app_session,
        refs,
        weight_set,
        route_code="DEL-BOM",
        weight=Decimal("1.00000000"),
        evidence_rung=4,
        evidence_ref="synthetic equal weight, single route, test only",
    )
    app_session.flush()

    stored = app_session.query(RouteWeight).filter_by(weight_set_version_id=weight_set.id).one()
    assert stored.evidence_rung == 4
    assert isinstance(stored.weight, Decimal)


# ===========================================================================
# C2 - weights close to 1, checked at COMMIT
# ===========================================================================
def test_c2_weight_set_summing_to_0_97_is_rejected(
    app_session: Session, refs: SeedRefs
) -> None:
    """The classic partial basket: four routes, 0.97 between them."""
    weight_set = new_weight_set(app_session, "c2_short")
    for route_code, weight in zip(
        FOUR_ROUTES,
        ("0.25000000", "0.25000000", "0.25000000", "0.22000000"),
        strict=True,
    ):
        add_route_weight(
            app_session,
            refs,
            weight_set,
            route_code=route_code,
            weight=Decimal(weight),
            evidence_rung=4,
        )
    app_session.flush()

    # The trigger is DEFERRABLE INITIALLY DEFERRED, so nothing has fired yet.
    # Forcing it immediate is the in-transaction equivalent of committing.
    with pytest.raises(IntegrityError) as caught:
        app_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    message = str(caught.value)
    assert "0.97" in message
    assert "must equal 1 within 1e-9" in message


def test_c2_weight_set_summing_to_one_commits(
    app_session: Session, refs: SeedRefs
) -> None:
    weight_set = new_weight_set(app_session, "c2_exact")
    for route_code in FOUR_ROUTES:
        add_route_weight(
            app_session,
            refs,
            weight_set,
            route_code=route_code,
            weight=Decimal("0.25000000"),
            evidence_rung=4,
        )
    app_session.flush()

    app_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    total = app_session.execute(
        text("SELECT sum(weight) FROM route_weight WHERE weight_set_version_id = :id"),
        {"id": weight_set.id},
    ).scalar_one()
    assert total == Decimal("1.00000000")


def test_c2_fires_at_real_commit_not_at_insert(
    committing_session: Session, committing_refs: SeedRefs
) -> None:
    """Rows insert one at a time without complaint; COMMIT is where it fails.

    This is the behaviour the deferred trigger exists to provide: a weight set is
    built row by row, and the closure check happens once, when the set is whole.
    """
    weight_set = new_weight_set(committing_session, "c2_deferred")

    for route_code, weight in zip(
        FOUR_ROUTES,
        ("0.25000000", "0.25000000", "0.25000000", "0.22000000"),
        strict=True,
    ):
        add_route_weight(
            committing_session,
            committing_refs,
            weight_set,
            route_code=route_code,
            weight=Decimal(weight),
            evidence_rung=4,
        )
        # Each individual insert succeeds - a partial set is not an error.
        committing_session.flush()

    with pytest.raises(IntegrityError, match="must equal 1 within 1e-9"):
        committing_session.commit()


def test_c2_a_complete_weight_set_survives_a_real_commit(
    committing_session: Session, committing_refs: SeedRefs
) -> None:
    weight_set = new_weight_set(committing_session, "c2_commit_ok")
    for route_code in FOUR_ROUTES:
        add_route_weight(
            committing_session,
            committing_refs,
            weight_set,
            route_code=route_code,
            weight=Decimal("0.25000000"),
            evidence_rung=1,
            evidence_ref="synthetic test weight set",
        )
    committing_session.commit()

    total = committing_session.execute(
        text("SELECT sum(weight) FROM route_weight WHERE weight_set_version_id = :id"),
        {"id": weight_set.id},
    ).scalar_one()
    assert total == Decimal("1.00000000")


def test_c2_tolerance_is_one_part_in_a_billion(
    app_session: Session, refs: SeedRefs
) -> None:
    """1e-9 is the stated tolerance; 1e-8 out is out."""
    weight_set = new_weight_set(app_session, "c2_tolerance")
    add_route_weight(
        app_session,
        refs,
        weight_set,
        route_code="DEL-BOM",
        weight=Decimal("0.99999999"),
        evidence_rung=4,
    )
    app_session.flush()

    with pytest.raises(IntegrityError, match="must equal 1 within 1e-9"):
        app_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


# ===========================================================================
# C4 - a fare is a positive number and always says where it came from
# ===========================================================================
def collection_for(session: Session, refs: SeedRefs, day: date, travel: date):
    return build_collection(
        session,
        refs,
        travel_date=travel,
        collected_date=day,
        fetched_at=utc(day, time(6, 30)),
    )


@pytest.mark.parametrize("fare", [Decimal("0.00"), Decimal("-100.00")])
def test_c4_non_positive_fares_are_rejected(
    app_session: Session, refs: SeedRefs, fare: Decimal
) -> None:
    collection = collection_for(app_session, refs, date(2026, 4, 1), date(2026, 4, 8))

    with (
        pytest.raises(IntegrityError, match="ck_normalised_quote_total_fare_positive"),
        app_session.begin_nested(),
    ):
        add_quote(
            app_session,
            refs,
            collection,
            flight_no="6E1000",
            fare_brand="SAVER",
            total_fare=fare,
            departure_ts=utc(date(2026, 4, 8), time(7, 45)),
            collected_at=utc(date(2026, 4, 1), time(6, 30)),
            collected_date=date(2026, 4, 1),
        )


def test_c4_provenance_cannot_be_null(app_session: Session, refs: SeedRefs) -> None:
    collection = collection_for(app_session, refs, date(2026, 4, 2), date(2026, 4, 9))

    with pytest.raises(IntegrityError) as caught, app_session.begin_nested():
        app_session.execute(
            text(
                """
                    INSERT INTO normalised_quote (
                        raw_quote_id, route_id, bucket_id, source_id, carrier,
                        flight_no, lead_time_days, fare_brand, total_fare, currency,
                        collected_at, collected_date, provenance, quality_status
                    ) VALUES (
                        NULL, :route_id, :bucket_id, :source_id, '6E',
                        '6E1001', 7, 'SAVER', 5000.00, 'INR',
                        :collected_at, :collected_date, NULL, 'COMPLETE'
                    )
                    """
            ),
            {
                "route_id": refs.routes["DEL-BOM"],
                "bucket_id": refs.buckets["T7"],
                "source_id": refs.sources["indigo_web"],
                "collected_at": utc(date(2026, 4, 2), time(6, 30)),
                "collected_date": date(2026, 4, 2),
            },
        )

    assert "provenance" in str(caught.value)
    assert collection.request.id is not None


def test_c4_a_positive_fare_with_provenance_is_accepted(
    app_session: Session, refs: SeedRefs
) -> None:
    collection = collection_for(app_session, refs, date(2026, 4, 3), date(2026, 4, 10))
    quote = add_quote(
        app_session,
        refs,
        collection,
        flight_no="6E1002",
        fare_brand="SAVER",
        total_fare=Decimal("5000.00"),
        departure_ts=utc(date(2026, 4, 10), time(7, 45)),
        collected_at=utc(date(2026, 4, 3), time(6, 30)),
        collected_date=date(2026, 4, 3),
    )
    app_session.flush()

    assert quote.total_fare == Decimal("5000.00")
    assert isinstance(quote.total_fare, Decimal)
    assert quote.provenance == Provenance.LIVE_COLLECTED


# ===========================================================================
# C5 - simulated data is structurally barred from a headline
# ===========================================================================
def seed_simulated_quote(session: Session, refs: SeedRefs, day: date, route_code: str) -> None:
    collection = build_collection(
        session,
        refs,
        route_code=route_code,
        travel_date=day + timedelta(days=7),
        collected_date=day,
        fetched_at=utc(day, time(6, 30)),
    )
    add_quote(
        session,
        refs,
        collection,
        route_code=route_code,
        flight_no="6E9001",
        fare_brand="DEMO",
        total_fare=Decimal("4200.00"),
        departure_ts=utc(day + timedelta(days=7), time(9, 0)),
        collected_at=utc(day, time(6, 30)),
        collected_date=day,
        provenance=Provenance.SIMULATED_DEMO,
    )
    session.flush()


def test_c5_headline_over_simulated_quotes_is_rejected(
    app_session: Session, refs: SeedRefs
) -> None:
    obs_date = date(2026, 5, 1)
    weight_set = new_weight_set(app_session, "c5_blocked")
    seed_simulated_quote(app_session, refs, obs_date, "DEL-BOM")

    with pytest.raises(IntegrityError) as caught, app_session.begin_nested():
        make_index_observation(
            app_session,
            refs,
            obs_date=obs_date,
            level=IndexLevel.HEADLINE.value,
            weight_set=weight_set,
            index_value=Decimal("102.313000"),
            prev_index_value=Decimal("100.000000"),
            routes_in_basket=1,
        )

    message = str(caught.value)
    assert "SIMULATED_DEMO" in message
    assert "HEADLINE" in message


def test_c5_a_headline_on_a_clean_date_is_accepted(
    app_session: Session, refs: SeedRefs
) -> None:
    """The barrier is specific: it blocks simulated lineage, not headlines as such."""
    obs_date = date(2026, 5, 2)
    weight_set = new_weight_set(app_session, "c5_clean")

    observation = make_index_observation(
        app_session,
        refs,
        obs_date=obs_date,
        level=IndexLevel.HEADLINE.value,
        weight_set=weight_set,
        index_value=Decimal("102.313000"),
        prev_index_value=Decimal("100.000000"),
        routes_in_basket=1,
    )
    assert observation.id is not None


def test_c5_stratum_and_route_levels_are_not_blocked(
    app_session: Session, refs: SeedRefs
) -> None:
    """Simulated data may produce demo-only strata; it may never produce a headline."""
    obs_date = date(2026, 5, 3)
    weight_set = new_weight_set(app_session, "c5_stratum")
    seed_simulated_quote(app_session, refs, obs_date, "DEL-BOM")

    stratum = make_index_observation(
        app_session,
        refs,
        obs_date=obs_date,
        level=IndexLevel.STRATUM.value,
        weight_set=weight_set,
        index_value=Decimal("101.000000"),
        ref_id=refs.routes["DEL-BOM"],
        bucket_id=refs.buckets["T7"],
    )
    assert stratum.id is not None


def test_c5_contribution_from_a_simulated_route_is_rejected(
    app_session: Session, refs: SeedRefs
) -> None:
    """The other end of the relationship is guarded too.

    A headline row is inserted while the date is clean, then a simulated quote
    appears for one of its routes. Attaching that route's contribution is
    refused, so the simulated lineage still cannot reach the published value.
    """
    obs_date = date(2026, 5, 4)
    weight_set = new_weight_set(app_session, "c5_contribution")

    observation = make_index_observation(
        app_session,
        refs,
        obs_date=obs_date,
        level=IndexLevel.HEADLINE.value,
        weight_set=weight_set,
        index_value=Decimal("100.500000"),
        routes_in_basket=1,
    )

    seed_simulated_quote(app_session, refs, obs_date, "DEL-BOM")

    with pytest.raises(IntegrityError) as caught, app_session.begin_nested():
        add_contribution(
            app_session,
            refs,
            observation,
            route_code="DEL-BOM",
            contribution=Decimal("0.500000"),
        )

    assert "SIMULATED_DEMO" in str(caught.value)


def test_c5_contribution_from_a_live_route_is_accepted(
    app_session: Session, refs: SeedRefs
) -> None:
    obs_date = date(2026, 5, 5)
    weight_set = new_weight_set(app_session, "c5_contribution_ok")

    observation = make_index_observation(
        app_session,
        refs,
        obs_date=obs_date,
        level=IndexLevel.HEADLINE.value,
        weight_set=weight_set,
        index_value=Decimal("100.500000"),
        routes_in_basket=1,
    )
    contribution = add_contribution(
        app_session,
        refs,
        observation,
        route_code="DEL-BOM",
        contribution=Decimal("0.500000"),
    )
    assert contribution.contribution == Decimal("0.500000")


def test_c5_guard_is_a_database_trigger_not_application_code(
    app_session: Session, refs: SeedRefs
) -> None:
    """Raw SQL that bypasses the ORM entirely is refused just the same."""
    obs_date = date(2026, 5, 6)
    weight_set = new_weight_set(app_session, "c5_raw_sql")
    seed_simulated_quote(app_session, refs, obs_date, "DEL-BOM")

    with pytest.raises(IntegrityError, match="SIMULATED_DEMO"), app_session.begin_nested():
        app_session.execute(
            text(
                """
                    INSERT INTO index_observation (
                        obs_date, level, index_value, methodology_version_id,
                        weight_set_version_id, input_quote_count, input_hash, computed_at
                    ) VALUES (
                        :obs_date, 'HEADLINE', 102.313000, :methodology_id,
                        :weight_set_id, 3, :input_hash, :computed_at
                    )
                    """
            ),
            {
                "obs_date": obs_date,
                "methodology_id": refs.methodology_version_id,
                "weight_set_id": weight_set.id,
                "input_hash": "d" * 64,
                "computed_at": datetime.now(UTC),
            },
        )


# ===========================================================================
# Architect rulings from the Phase 3 review
# ===========================================================================
def test_two_headlines_for_one_date_and_methodology_are_impossible(
    app_session: Session, refs: SeedRefs
) -> None:
    """UNIQUE NULLS NOT DISTINCT on the identity key (revision 0004).

    A HEADLINE row carries NULL ref_id and NULL bucket_id. Under PostgreSQL's
    default those NULLs are distinct, so the same date and methodology version
    could carry two different published values - which would destroy the
    reproducibility guarantee. The key now treats them as equal.
    """
    obs_date = date(2026, 5, 20)
    weight_set = new_weight_set(app_session, "identity_key")

    make_index_observation(
        app_session,
        refs,
        obs_date=obs_date,
        level=IndexLevel.HEADLINE.value,
        weight_set=weight_set,
        index_value=Decimal("102.313000"),
    )

    with pytest.raises(IntegrityError, match="uq_index_observation_identity"), (
        app_session.begin_nested()
    ):
        make_index_observation(
            app_session,
            refs,
            obs_date=obs_date,
            level=IndexLevel.HEADLINE.value,
            weight_set=weight_set,
            index_value=Decimal("999.000000"),
        )


def test_two_strata_differing_only_by_bucket_still_coexist(
    app_session: Session, refs: SeedRefs
) -> None:
    """NULLS NOT DISTINCT must not collapse rows that genuinely differ."""
    obs_date = date(2026, 5, 21)
    weight_set = new_weight_set(app_session, "identity_key_strata")

    for bucket_code in ("T7", "T21"):
        make_index_observation(
            app_session,
            refs,
            obs_date=obs_date,
            level=IndexLevel.STRATUM.value,
            weight_set=weight_set,
            index_value=Decimal("101.000000"),
            ref_id=refs.routes["DEL-BOM"],
            bucket_id=refs.buckets[bucket_code],
        )
    app_session.flush()

    count = app_session.execute(
        text("SELECT count(*) FROM index_observation WHERE obs_date = :d AND level = 'STRATUM'"),
        {"d": obs_date},
    ).scalar_one()
    assert count == 2


def test_same_day_travel_is_rejected(app_session: Session, refs: SeedRefs) -> None:
    """Strict inequality: every lead-time bucket has days >= 1, so T+0 cannot exist."""
    day = date(2026, 5, 22)
    with pytest.raises(
        IntegrityError, match="ck_collection_request_travel_after_collected"
    ), app_session.begin_nested():
        build_collection(
            app_session,
            refs,
            travel_date=day,
            collected_date=day,
            fetched_at=utc(day, time(6, 30)),
        )


def test_index_observation_base_period_must_exist(
    app_session: Session, refs: SeedRefs
) -> None:
    """base_period_id is a foreign key now, not a loose UUID (revision 0004)."""
    weight_set = new_weight_set(app_session, "base_period_fk")
    period = make_base_period(
        app_session,
        refs,
        code="test_base_period_2026",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )

    observation = make_index_observation(
        app_session,
        refs,
        obs_date=date(2026, 5, 23),
        level=IndexLevel.HEADLINE.value,
        weight_set=weight_set,
        index_value=Decimal("100.000000"),
        base_period=period,
    )
    assert observation.base_period_id == period.id

    with pytest.raises(IntegrityError, match="fk_index_observation_base_period_id"), (
        app_session.begin_nested()
    ):
        app_session.execute(
            text(
                """
                INSERT INTO index_observation (
                    obs_date, level, index_value, base_period_id, methodology_version_id,
                    weight_set_version_id, input_quote_count, input_hash, computed_at
                ) VALUES (
                    :obs_date, 'ROUTE', 100.000000, :missing, :methodology_id,
                    :weight_set_id, 1, :input_hash, :computed_at
                )
                """
            ),
            {
                "obs_date": date(2026, 5, 24),
                "missing": uuid7(),
                "methodology_id": refs.methodology_version_id,
                "weight_set_id": weight_set.id,
                "input_hash": "a" * 64,
                "computed_at": datetime.now(UTC),
            },
        )


def test_a_base_period_must_end_after_it_starts(
    app_session: Session, refs: SeedRefs
) -> None:
    with pytest.raises(IntegrityError, match="ck_base_period_dates_ordered"), (
        app_session.begin_nested()
    ):
        make_base_period(
            app_session,
            refs,
            code="test_base_period_inverted",
            start_date=date(2026, 2, 1),
            end_date=date(2026, 1, 1),
        )
