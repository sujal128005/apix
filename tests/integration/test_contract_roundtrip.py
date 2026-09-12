"""Every contract round-trips against its SQLAlchemy model, on real persisted rows.

A contract that only works on hand-built dictionaries proves nothing. These
tests persist an actual row for all 21 tables, validate the contract straight off
the ORM instance, dump it back, rebuild an ORM instance from the dump and check
that nothing changed on the way through - in particular that Decimals stay
Decimals and timestamps stay timezone-aware.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from schemas.contracts import CONTRACT_BY_TABLE
from schemas.enums import (
    ComplianceDecisionCode,
    Confidence,
    FareComponentKind,
    IndexLevel,
    PublicationState,
    ReviewVerdict,
)
from schemas.models import (
    ALL_TABLES,
    Airport,
    BacktestRun,
    BenchmarkObservation,
    LeadTimeBucket,
    MethodologyVersion,
    Publication,
    RawQuote,
    Route,
    Source,
    SourceReview,
    SystemEvent,
)
from tests.support.builders import (
    SeedRefs,
    add_cleaning_event,
    add_contribution,
    add_fare_component,
    add_quote,
    add_route_weight,
    build_collection,
    make_base_period,
    make_index_observation,
    make_weight_set,
    utc,
)

pytestmark = pytest.mark.integration

DAY = date(2026, 7, 1)
TRAVEL = date(2026, 7, 8)


@pytest.fixture
def one_row_per_table(app_session: Session, refs: SeedRefs) -> dict[str, Any]:
    """A persisted instance of every table, seeded rows included."""
    rows: dict[str, Any] = {
        "airport": app_session.execute(select(Airport).limit(1)).scalars().one(),
        "route": app_session.execute(select(Route).limit(1)).scalars().one(),
        "lead_time_bucket": app_session.execute(select(LeadTimeBucket).limit(1))
        .scalars()
        .one(),
        "source": app_session.execute(select(Source).limit(1)).scalars().one(),
        "methodology_version": app_session.execute(select(MethodologyVersion).limit(1))
        .scalars()
        .one(),
    }

    review = SourceReview(
        source_id=refs.sources["makemytrip"],
        reviewer="compliance-review-fixture",
        reviewed_at=utc(DAY, time(9, 0)),
        robots_decision="Disallow: /flight/search",
        tos_note="automated flight-search collection is not permitted",
        verdict=ReviewVerdict.REJECTED.value,
    )
    app_session.add(review)
    app_session.flush()
    rows["source_review"] = review

    weight_set = make_weight_set(
        app_session,
        version="test_weight_set_roundtrip",
        effective_from=DAY,
        source_note="synthetic weight set built inside a test; never sourced evidence",
    )
    rows["weight_set_version"] = weight_set

    rows["route_weight"] = add_route_weight(
        app_session,
        refs,
        weight_set,
        route_code="DEL-BOM",
        weight=Decimal("1.00000000"),
        evidence_rung=4,
        evidence_ref="synthetic equal weight, single route, test only",
        evidence_retrieved_at=utc(DAY, time(9, 0)),
    )
    app_session.flush()

    collection = build_collection(
        app_session,
        refs,
        travel_date=TRAVEL,
        collected_date=DAY,
        fetched_at=utc(DAY, time(6, 30)),
        decision=ComplianceDecisionCode.ALLOWED,
    )
    rows["collection_job"] = collection.job
    rows["collection_request"] = collection.request
    rows["compliance_decision"] = collection.decision
    rows["raw_response"] = collection.response

    quote = add_quote(
        app_session,
        refs,
        collection,
        flight_no="6E7000",
        fare_brand="SAVER",
        total_fare=Decimal("5432.10"),
        departure_ts=utc(TRAVEL, time(7, 45)),
        collected_at=utc(DAY, time(6, 30)),
        collected_date=DAY,
        quality_score=Decimal("0.875"),
        component_confidence=Confidence.HIGH,
    )
    rows["normalised_quote"] = quote
    rows["raw_quote"] = app_session.get(RawQuote, quote.raw_quote_id)

    rows["fare_component"] = add_fare_component(
        app_session, quote, kind=FareComponentKind.BASE, amount=Decimal("4000.00")
    )
    rows["cleaning_event"] = add_cleaning_event(
        app_session,
        quote,
        rule_id="R-NORMALISE-CURRENCY",
        action="ACCEPT",
        threshold=Decimal("1.5"),
        observed=Decimal("0.25"),
        reason="quoted currency is INR; no conversion applied",
    )

    period = make_base_period(
        app_session,
        refs,
        code="test_base_period_roundtrip",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )
    rows["base_period"] = period

    observation = make_index_observation(
        app_session,
        refs,
        obs_date=DAY,
        level=IndexLevel.ROUTE.value,
        weight_set=weight_set,
        index_value=Decimal("102.313000"),
        prev_index_value=Decimal("100.000000"),
        ref_id=refs.routes["DEL-BOM"],
        routes_in_basket=1,
        base_period=period,
    )
    rows["index_observation"] = observation
    rows["index_contribution"] = add_contribution(
        app_session, refs, observation, route_code="DEL-BOM", contribution=Decimal("102.313000")
    )

    # An approved-but-unpublished figure: the state carrying the most fields, so
    # the round trip exercises attribution and scheduling rather than the empty
    # PENDING case.
    publication = Publication(
        index_observation_id=observation.id,
        state=PublicationState.APPROVED.value,
        approved_by="round-trip fixture",
        approved_at=utc(DAY, time(10, 0)),
        scheduled_release_at=utc(DAY, time(11, 30)),
        published_at=None,
        supersedes_id=None,
        revision_reason=None,
        withdrawn_reason=None,
    )
    app_session.add(publication)
    app_session.flush()
    rows["publication"] = publication

    benchmark = BenchmarkObservation(
        bench_source="fixture",
        period="2026-07",
        ref=None,
        value=Decimal("1234.5678"),
        definition="round-trip fixture value; not a published statistic",
        citation_url="https://example.invalid/fixture",
        citation_page=None,
        retrieved_at=utc(DAY, time(9, 0)),
    )
    app_session.add(benchmark)

    backtest = BacktestRun(
        window_start=date(2026, 1, 1),
        window_end=date(2026, 6, 30),
        tier=3,
        metrics={"note": "round-trip fixture; no metric is claimed"},
        limitations="No public DGCA fare time series exists to validate against.",
        input_hash="f" * 64,
        run_at=utc(DAY, time(9, 0)),
    )
    app_session.add(backtest)

    event = SystemEvent(
        level="INFO",
        component="tests",
        event="contract_roundtrip_fixture",
        payload={"phase": 3},
    )
    app_session.add(event)
    app_session.flush()

    rows["benchmark_observation"] = benchmark
    rows["backtest_run"] = backtest
    rows["system_event"] = event
    return rows


def test_the_fixture_covers_every_table(one_row_per_table: dict[str, Any]) -> None:
    assert set(one_row_per_table) == set(ALL_TABLES)


@pytest.mark.parametrize("table", sorted(ALL_TABLES))
def test_contract_validates_off_the_orm_instance(
    one_row_per_table: dict[str, Any], table: str
) -> None:
    contract = CONTRACT_BY_TABLE[table]
    instance = one_row_per_table[table]

    validated = contract.model_validate(instance)

    assert validated.id == instance.id
    assert validated.created_at == instance.created_at
    assert validated.created_at.tzinfo is not None


@pytest.mark.parametrize("table", sorted(ALL_TABLES))
def test_contract_round_trips_back_into_the_model(
    one_row_per_table: dict[str, Any], table: str
) -> None:
    """ORM -> contract -> dict -> ORM, with every value unchanged."""
    contract = CONTRACT_BY_TABLE[table]
    original = one_row_per_table[table]

    dumped = contract.model_validate(original).model_dump()
    rebuilt = type(original)(**dumped)

    for name in contract.model_fields:
        before = getattr(original, name)
        after = getattr(rebuilt, name)
        assert before == after, f"{table}.{name}: {before!r} became {after!r}"
        if isinstance(before, Decimal):
            assert isinstance(after, Decimal), f"{table}.{name} stopped being a Decimal"
        if isinstance(before, datetime):
            assert after.tzinfo is not None, f"{table}.{name} lost its time zone"


@pytest.mark.parametrize("table", sorted(ALL_TABLES))
def test_round_trip_is_stable_on_a_second_pass(
    one_row_per_table: dict[str, Any], table: str
) -> None:
    contract = CONTRACT_BY_TABLE[table]
    original = one_row_per_table[table]

    first = contract.model_validate(original).model_dump()
    second = contract.model_validate(type(original)(**first)).model_dump()
    assert first == second


def test_money_survives_the_round_trip_exactly(one_row_per_table: dict[str, Any]) -> None:
    """5432.10 is not representable in binary floating point. It must come back exact."""
    quote = one_row_per_table["normalised_quote"]
    validated = CONTRACT_BY_TABLE["normalised_quote"].model_validate(quote)

    assert validated.total_fare == Decimal("5432.10")
    assert str(validated.total_fare) == "5432.10"
    assert isinstance(validated.total_fare, Decimal)


def test_index_values_survive_at_six_decimal_places(
    one_row_per_table: dict[str, Any],
) -> None:
    observation = one_row_per_table["index_observation"]
    validated = CONTRACT_BY_TABLE["index_observation"].model_validate(observation)

    assert validated.index_value == Decimal("102.313000")
    assert str(validated.index_value) == "102.313000"


def test_timestamps_come_back_from_postgres_in_utc(
    one_row_per_table: dict[str, Any],
) -> None:
    quote = one_row_per_table["normalised_quote"]
    validated = CONTRACT_BY_TABLE["normalised_quote"].model_validate(quote)

    assert validated.collected_at.tzinfo is not None
    assert validated.collected_at.utcoffset().total_seconds() == 0
    assert validated.collected_at == datetime(2026, 7, 1, 6, 30, tzinfo=UTC)
