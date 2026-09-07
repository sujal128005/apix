"""One test per known-bad input in tests/fixtures/adversarial/adversarial_cases.json.

Twelve of the fourteen cases are refused by PostgreSQL. One is refused at the
contract boundary, because PostgreSQL cannot see the problem: a naive timestamp
going into a TIMESTAMPTZ column is silently reinterpreted rather than rejected.
One is deliberately flagged instead of refused, and the reasoning for that is in
the manifest and repeated in the test.

``test_manifest_is_fully_covered`` ties the two together: every case id in the
manifest must have a ``test_<id>`` here, and every such test must correspond to a
case. Neither list can grow or shrink unnoticed.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, text
from sqlalchemy.exc import DataError, IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from schemas import contracts
from schemas.enums import (
    Confidence,
    FareComponentKind,
    IndexLevel,
    MissingReason,
    Provenance,
    QualityStatus,
)
from schemas.models import IMMUTABLE_TABLES, Airport, Route
from schemas.uuid7 import uuid7
from tests.support.builders import (
    SeedRefs,
    add_cleaning_event,
    add_fare_component,
    add_quote,
    add_route_weight,
    build_collection,
    make_index_observation,
    make_weight_set,
    utc,
)

pytestmark = [pytest.mark.integration, pytest.mark.adversarial]

WEIGHT_SET_KWARGS = {
    "effective_from": date(2026, 1, 1),
    "source_note": "synthetic weight set built inside a test; never sourced evidence",
}


def a_collection(session: Session, refs: SeedRefs, day: date, travel: date, **kwargs: Any):
    return build_collection(
        session,
        refs,
        travel_date=travel,
        collected_date=day,
        fetched_at=utc(day, time(6, 30)),
        **kwargs,
    )


# ===========================================================================
# manifest coverage
# ===========================================================================
def test_manifest_is_fully_covered(adversarial_manifest: dict[str, Any]) -> None:
    """Every listed case has a test, and every test corresponds to a listed case."""
    module = sys.modules[__name__]
    declared = {case["id"] for case in adversarial_manifest["cases"]}
    implemented = {
        name[len("test_") :]
        for name in dir(module)
        if name.startswith("test_") and name != "test_manifest_is_fully_covered"
    }

    assert declared - implemented == set(), f"cases with no test: {sorted(declared - implemented)}"
    assert implemented - declared == set(), (
        f"tests with no manifest entry: {sorted(implemented - declared)}"
    )
    assert len(declared) == 14


# ===========================================================================
# 1-2. fares that are not fares
# ===========================================================================
def test_zero_fare(app_session: Session, refs: SeedRefs) -> None:
    collection = a_collection(app_session, refs, date(2026, 6, 1), date(2026, 6, 8))
    with (
        pytest.raises(IntegrityError, match="ck_normalised_quote_total_fare_positive"),
        app_session.begin_nested(),
    ):
        add_quote(
            app_session,
            refs,
            collection,
            flight_no="6E3000",
            fare_brand="SAVER",
            total_fare=Decimal("0.00"),
            departure_ts=utc(date(2026, 6, 8), time(7, 45)),
            collected_at=utc(date(2026, 6, 1), time(6, 30)),
            collected_date=date(2026, 6, 1),
        )


def test_negative_fare(app_session: Session, refs: SeedRefs) -> None:
    collection = a_collection(app_session, refs, date(2026, 6, 2), date(2026, 6, 9))
    with (
        pytest.raises(IntegrityError, match="ck_normalised_quote_total_fare_positive"),
        app_session.begin_nested(),
    ):
        add_quote(
            app_session,
            refs,
            collection,
            flight_no="6E3001",
            fare_brand="SAVER",
            total_fare=Decimal("-100.00"),
            departure_ts=utc(date(2026, 6, 9), time(7, 45)),
            collected_at=utc(date(2026, 6, 2), time(6, 30)),
            collected_date=date(2026, 6, 2),
        )


# ===========================================================================
# 3. the same offer collected twice
# ===========================================================================
def test_duplicate_quote_dedup_key(app_session: Session, refs: SeedRefs) -> None:
    """One flight, one brand, one source, one collection date: one row."""
    day, travel = date(2026, 6, 3), date(2026, 6, 10)
    collection = a_collection(app_session, refs, day, travel)
    shared = {
        "flight_no": "6E3002",
        "fare_brand": "SAVER",
        "departure_ts": utc(travel, time(7, 45)),
        "collected_at": utc(day, time(6, 30)),
        "collected_date": day,
    }

    add_quote(app_session, refs, collection, total_fare=Decimal("5000.00"), **shared)

    with (
        pytest.raises(IntegrityError, match="uq_normalised_quote_dedup"),
        app_session.begin_nested(),
    ):
        add_quote(app_session, refs, collection, total_fare=Decimal("5100.00"), **shared)


# ===========================================================================
# 4. an observation that will not say where it came from
# ===========================================================================
def test_missing_provenance(app_session: Session, refs: SeedRefs) -> None:
    day, travel = date(2026, 6, 4), date(2026, 6, 11)
    a_collection(app_session, refs, day, travel)

    with pytest.raises(IntegrityError) as caught, app_session.begin_nested():
        app_session.execute(
            text(
                """
                    INSERT INTO normalised_quote (
                        raw_quote_id, route_id, bucket_id, source_id, carrier,
                        lead_time_days, total_fare, currency, collected_at,
                        collected_date, provenance, quality_status, imputation_code
                    ) VALUES (
                        NULL, :route_id, :bucket_id, :source_id, '6E',
                        7, 5000.00, 'INR', :collected_at,
                        :collected_date, NULL, 'COMPLETE', 'Y'
                    )
                    """
            ),
            {
                "route_id": refs.routes["DEL-BOM"],
                "bucket_id": refs.buckets["T7"],
                "source_id": refs.sources["indigo_web"],
                "collected_at": utc(day, time(6, 30)),
                "collected_date": day,
            },
        )
    assert "provenance" in str(caught.value)


# ===========================================================================
# 5. codes that are not IATA codes
# ===========================================================================
@pytest.mark.parametrize(
    ("iata", "expected_error"),
    [
        ("XX", IntegrityError),  # CHAR(3) pads to 'XX ', which fails the pattern
        ("DELH", DataError),  # too long for the column
        ("del", IntegrityError),  # lower case fails the pattern
    ],
    ids=["too_short", "too_long", "lower_case"],
)
def test_invalid_iata(
    app_session: Session, iata: str, expected_error: type[Exception]
) -> None:
    with pytest.raises(expected_error), app_session.begin_nested():
        app_session.add(
            Airport(
                iata=iata,
                icao=None,
                name="Not a real airport",
                city="Nowhere",
                state="Nowhere",
                tz="Asia/Kolkata",
                active=True,
            )
        )
        app_session.flush()


# ===========================================================================
# 6. a route that goes nowhere
# ===========================================================================
def test_origin_equals_destination(app_session: Session, refs: SeedRefs) -> None:
    delhi = refs.airports["DEL"]
    with (
        pytest.raises(IntegrityError, match="ck_route_origin_ne_destination"),
        app_session.begin_nested(),
    ):
        app_session.add(
            Route(
                code="DEL-DEL",
                origin_id=delhi,
                destination_id=delhi,
                directional=True,
                active=True,
            )
        )
        app_session.flush()


# ===========================================================================
# 7. components that do not add up - stored and flagged, not refused
# ===========================================================================
def test_fare_components_exceed_total(app_session: Session, refs: SeedRefs) -> None:
    """Flagged rather than rejected - architect ruling, Phase 3 review.

    The total is the index price; the components are supplementary. A source
    with a bad decomposition is giving us a bad breakdown, not a bad price, and
    refusing the row would discard a usable observation over a presentation
    artefact. The quote is kept and labelled: quality_status PARTIAL,
    missing_reason PARTIAL_COMPONENTS, component_confidence LOW, plus a
    cleaning_event recording exactly what was seen. This is what
    PARTIAL_COMPONENTS exists for.
    """
    day, travel = date(2026, 6, 5), date(2026, 6, 12)
    collection = a_collection(app_session, refs, day, travel)

    quote = add_quote(
        app_session,
        refs,
        collection,
        flight_no="6E3003",
        fare_brand="SAVER",
        total_fare=Decimal("5000.00"),
        departure_ts=utc(travel, time(7, 45)),
        collected_at=utc(day, time(6, 30)),
        collected_date=day,
        quality_status=QualityStatus.PARTIAL,
        missing_reason=MissingReason.PARTIAL_COMPONENTS,
        component_confidence=Confidence.LOW,
    )
    add_fare_component(
        app_session, quote, kind=FareComponentKind.BASE, amount=Decimal("4000.00")
    )
    add_fare_component(
        app_session, quote, kind=FareComponentKind.TAX, amount=Decimal("2000.00")
    )
    add_cleaning_event(
        app_session,
        quote,
        rule_id="R-COMPONENTS-EXCEED-TOTAL",
        action="FLAG_PARTIAL_COMPONENTS",
        threshold=Decimal("5000.00"),
        observed=Decimal("6000.00"),
        reason="published components sum above the published total; total retained as the index price",
    )
    app_session.flush()

    detected = app_session.execute(
        text(
            """
            SELECT q.id, q.total_fare, sum(c.amount) AS component_total,
                   q.quality_status, q.missing_reason, q.component_confidence
            FROM normalised_quote q
            JOIN fare_component c ON c.quote_id = q.id
            WHERE q.id = :quote_id
            GROUP BY q.id, q.total_fare, q.quality_status, q.missing_reason,
                     q.component_confidence
            HAVING sum(c.amount) > q.total_fare
            """
        ),
        {"quote_id": quote.id},
    ).one()

    # The price survives intact; the breakdown is what is marked down.
    assert detected.total_fare == Decimal("5000.00")
    assert detected.component_total == Decimal("6000.00")
    assert detected.quality_status == QualityStatus.PARTIAL
    assert detected.missing_reason == MissingReason.PARTIAL_COMPONENTS
    assert detected.component_confidence == Confidence.LOW

    rules = app_session.execute(
        text("SELECT rule_id FROM cleaning_event WHERE quote_id = :quote_id"),
        {"quote_id": quote.id},
    ).scalars().all()
    assert rules == ["R-COMPONENTS-EXCEED-TOTAL"]


# ===========================================================================
# 8-9. weights
# ===========================================================================
def test_null_evidence_rung(app_session: Session, refs: SeedRefs) -> None:
    weight_set = make_weight_set(
        app_session, version="test_weight_set_adv_rung", **WEIGHT_SET_KWARGS
    )
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


def test_weight_set_sums_to_0_97(app_session: Session, refs: SeedRefs) -> None:
    weight_set = make_weight_set(
        app_session, version="test_weight_set_adv_097", **WEIGHT_SET_KWARGS
    )
    for route_code, weight in (
        ("DEL-BOM", "0.50000000"),
        ("BOM-DEL", "0.47000000"),
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

    with pytest.raises(IntegrityError, match="must equal 1 within 1e-9"):
        app_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


# ===========================================================================
# 10. simulated data trying to become a published number
# ===========================================================================
def test_simulated_demo_reaches_headline(app_session: Session, refs: SeedRefs) -> None:
    day = date(2026, 6, 6)
    weight_set = make_weight_set(
        app_session, version="test_weight_set_adv_headline", **WEIGHT_SET_KWARGS
    )
    collection = a_collection(app_session, refs, day, day + timedelta(days=7))
    add_quote(
        app_session,
        refs,
        collection,
        flight_no="6E3004",
        fare_brand="DEMO",
        total_fare=Decimal("4200.00"),
        departure_ts=utc(day + timedelta(days=7), time(9, 0)),
        collected_at=utc(day, time(6, 30)),
        collected_date=day,
        provenance=Provenance.SIMULATED_DEMO,
    )
    app_session.flush()

    with pytest.raises(IntegrityError, match="SIMULATED_DEMO"), app_session.begin_nested():
        make_index_observation(
            app_session,
            refs,
            obs_date=day,
            level=IndexLevel.HEADLINE.value,
            weight_set=weight_set,
            index_value=Decimal("101.000000"),
        )


# ===========================================================================
# 11. rewriting history
# ===========================================================================
@pytest.mark.parametrize("table", sorted(IMMUTABLE_TABLES))
@pytest.mark.parametrize("statement", ["UPDATE {} SET created_at = now()", "DELETE FROM {}"])
def test_update_on_immutable_table(app_engine: Engine, table: str, statement: str) -> None:
    with app_engine.connect() as connection, pytest.raises(ProgrammingError) as caught:
        connection.execute(text(statement.format(table)))
    assert "permission denied" in str(caught.value).lower()


# ===========================================================================
# 12. a fare in the wrong currency
# ===========================================================================
def test_currency_usd(app_session: Session, refs: SeedRefs) -> None:
    day, travel = date(2026, 6, 7), date(2026, 6, 14)
    a_collection(app_session, refs, day, travel)

    with (
        pytest.raises(IntegrityError, match="ck_normalised_quote_currency_inr"),
        app_session.begin_nested(),
    ):
        app_session.execute(
            text(
                """
                INSERT INTO normalised_quote (
                    raw_quote_id, route_id, bucket_id, source_id, carrier,
                    lead_time_days, total_fare, currency, collected_at,
                    collected_date, provenance, quality_status, imputation_code
                ) VALUES (
                    NULL, :route_id, :bucket_id, :source_id, '6E',
                    7, 60.00, 'USD', :collected_at,
                    :collected_date, 'LIVE_COLLECTED', 'COMPLETE', 'Y'
                )
                """
            ),
            {
                "route_id": refs.routes["DEL-BOM"],
                "bucket_id": refs.buckets["T7"],
                "source_id": refs.sources["indigo_web"],
                "collected_at": utc(day, time(6, 30)),
                "collected_date": day,
            },
        )


# ===========================================================================
# 13. travelling into the past
# ===========================================================================
@pytest.mark.parametrize(
    ("collected", "travel"),
    [
        (date(2026, 6, 8), date(2026, 6, 7)),  # travel in the past
        (date(2026, 6, 8), date(2026, 6, 8)),  # same day: no bucket has days = 0
    ],
    ids=["travel_in_the_past", "same_day"],
)
def test_travel_date_before_collected_date(
    app_session: Session, refs: SeedRefs, collected: date, travel: date
) -> None:
    """A fare quoted on day D cannot be for a departure on or before D.

    Strict inequality by architect ruling: every lead-time bucket has days >= 1,
    so travel_date > collected_date always holds and the tighter form is right.
    """
    with pytest.raises(
        IntegrityError, match="ck_collection_request_travel_after_collected"
    ), app_session.begin_nested():
        build_collection(
            app_session,
            refs,
            travel_date=travel,
            collected_date=collected,
            fetched_at=utc(collected, time(6, 30)),
        )


# ===========================================================================
# 14. a timestamp with no time zone
# ===========================================================================
def test_naive_departure_timestamp(admin_engine: Engine) -> None:
    """Rejected at the contract, because the database cannot reject it.

    PostgreSQL accepts a naive timestamp into a TIMESTAMPTZ column and applies
    the session time zone. There is no constraint that can see the difference
    afterwards, so the only place to stop it is before the driver. The second
    half of this test demonstrates the coercion that makes the first half
    necessary.
    """
    naive = datetime(2026, 3, 3, 6, 30)

    with pytest.raises(ValidationError, match="timezone"):
        contracts.NormalisedQuote(
            id=uuid7(),
            created_at=datetime(2026, 3, 3, 6, 30, tzinfo=UTC),
            raw_quote_id=uuid7(),
            route_id=uuid7(),
            bucket_id=uuid7(),
            source_id=uuid7(),
            carrier="6E",
            flight_no="6E2001",
            departure_ts=naive,
            arrival_ts=None,
            lead_time_days=7,
            fare_brand="SAVER",
            total_fare=Decimal("5000.00"),
            currency="INR",
            collected_at=datetime(2026, 3, 3, 6, 30, tzinfo=UTC),
            collected_date=date(2026, 3, 3),
            provenance=Provenance.LIVE_COLLECTED,
            quality_status=QualityStatus.COMPLETE,
            quality_score=None,
            imputation_code="N",
            missing_reason="NONE",
            component_confidence=None,
        )

    # And this is why: the database silently attaches an offset of its own.
    with admin_engine.connect() as connection:
        interpreted = connection.execute(
            text("SELECT CAST(:naive AS timestamptz) AS value"), {"naive": naive.isoformat()}
        ).scalar_one()
    assert interpreted.tzinfo is not None
    assert interpreted.utcoffset().total_seconds() == 0, (
        "the database is pinned to UTC by migration 0001, so a naive value that "
        "slipped past the contract is at least interpreted deterministically"
    )
