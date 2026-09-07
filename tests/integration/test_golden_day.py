"""The golden day round-trips through the schema with its lineage intact.

Phase 3 does not compute an index. What it must prove is that the four price
pairs from build brief section 8 can be stored with every link in the evidence
chain present and readable: source, request, compliance decision, raw payload,
raw offer, normalised quote, cleaning events.

The expected stratum index of 102.313 is recorded in the fixture as the Phase 9
target. It is asserted here only as a stored expectation, never computed - the
index engine is a later phase and writing it early would be building ahead.
"""

from __future__ import annotations

from datetime import UTC, date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from schemas.enums import ImputationCode, MissingReason, Provenance, QualityStatus
from schemas.models import (
    CleaningEvent,
    CollectionRequest,
    ComplianceDecision,
    NormalisedQuote,
    RawQuote,
    RawResponse,
)
from tests.support.builders import SeedRefs
from tests.support.golden import IST, load_golden_day

pytestmark = pytest.mark.integration


@pytest.fixture
def loaded(app_session: Session, refs: SeedRefs, golden_day: dict[str, Any]):
    return load_golden_day(app_session, refs, golden_day)


def test_eight_quotes_across_two_collection_days(loaded, app_session: Session) -> None:
    """Four matched pairs: one price on t-1 and one on t for each."""
    assert len(loaded.previous_quotes) == 4
    assert len(loaded.current_quotes) == 4
    assert set(loaded.previous_quotes) == {"A", "B", "C", "D"}
    assert set(loaded.current_quotes) == {"A", "B", "C", "D"}

    total = app_session.execute(select(func.count()).select_from(NormalisedQuote)).scalar_one()
    assert total == 8


def test_fares_round_trip_as_exact_decimals(
    loaded, app_session: Session, golden_day: dict[str, Any]
) -> None:
    """Every fare comes back byte for byte. No float has touched the path."""
    for entry in golden_day["pairs"]:
        previous = app_session.get(NormalisedQuote, loaded.previous_quotes[entry["pair"]].id)
        current = app_session.get(NormalisedQuote, loaded.current_quotes[entry["pair"]].id)
        assert previous is not None and current is not None

        assert previous.total_fare == Decimal(entry["previous_fare"])
        assert current.total_fare == Decimal(entry["current_fare"])
        assert isinstance(previous.total_fare, Decimal)
        assert isinstance(current.total_fare, Decimal)
        assert str(current.total_fare) == entry["current_fare"]


def test_the_outlier_is_stored_not_discarded(
    loaded, app_session: Session, golden_day: dict[str, Any]
) -> None:
    """Pair D is the outlier Phase 9 will reject. Phase 3 keeps it, and says so."""
    outlier_entry = next(entry for entry in golden_day["pairs"] if entry.get("outlier"))
    assert outlier_entry["pair"] == "D"

    quote = loaded.current_quotes["D"]
    assert quote.total_fare == Decimal("20000.00")

    rules = set(
        app_session.execute(
            select(CleaningEvent.rule_id).where(CleaningEvent.quote_id == quote.id)
        ).scalars()
    )
    assert "R-OUTLIER-MAD-LOG-RELATIVES" in rules

    flagged = app_session.execute(
        select(CleaningEvent).where(
            CleaningEvent.quote_id == quote.id,
            CleaningEvent.rule_id == "R-OUTLIER-MAD-LOG-RELATIVES",
        )
    ).scalars().one()
    assert flagged.threshold == Decimal("3.5")
    assert flagged.observed is None, (
        "the MAD statistic is computed by the Phase 9 engine; storing a number "
        "here would be inventing one"
    )


def test_every_quote_is_traceable_to_a_raw_offer(loaded, app_session: Session) -> None:
    """No quote in this fixture is imputed, so every one must reference raw bytes."""
    for quote in loaded.all_quotes:
        assert quote.raw_quote_id is not None
        assert quote.imputation_code == ImputationCode.N
        assert quote.missing_reason == MissingReason.NONE

        raw_quote = app_session.get(RawQuote, quote.raw_quote_id)
        assert raw_quote is not None
        response = app_session.get(RawResponse, raw_quote.raw_response_id)
        assert response is not None
        request = app_session.get(CollectionRequest, response.request_id)
        assert request is not None
        assert request.route_id == quote.route_id
        assert request.bucket_id == quote.bucket_id
        assert request.collected_date == quote.collected_date


def test_every_quote_carries_a_provenance(loaded) -> None:
    for quote in loaded.all_quotes:
        assert quote.provenance is not None
        assert quote.provenance == Provenance.LIVE_COLLECTED
        assert quote.quality_status == QualityStatus.COMPLETE


def test_the_raw_payload_keeps_money_as_a_string(loaded, app_session: Session) -> None:
    """JSON numbers are floats. Fares in a raw payload stay strings."""
    quote = loaded.current_quotes["B"]
    raw_quote = app_session.get(RawQuote, quote.raw_quote_id)
    assert raw_quote is not None
    assert raw_quote.payload["total_fare"] == "5610.00"
    assert isinstance(raw_quote.payload["total_fare"], str)
    assert Decimal(raw_quote.payload["total_fare"]) == quote.total_fare


def test_each_collection_day_has_its_own_compliance_decision(
    loaded, app_session: Session
) -> None:
    """A fetch that was never cleared by the gate has no business producing a fare."""
    for collection in (loaded.previous_collection, loaded.current_collection):
        decision = app_session.execute(
            select(ComplianceDecision).where(
                ComplianceDecision.request_id == collection.request.id
            )
        ).scalars().one()
        assert decision.decision == "ALLOWED"
        assert decision.user_agent
        assert decision.robots_sha256 is not None


def test_the_two_days_are_distinguishable_under_the_dedup_key(loaded) -> None:
    """Same flight, same brand, different collection date: two legitimate rows."""
    previous = loaded.previous_quotes["A"]
    current = loaded.current_quotes["A"]
    assert previous.flight_no == current.flight_no
    assert previous.fare_brand == current.fare_brand
    assert previous.source_id == current.source_id
    assert previous.collected_date != current.collected_date
    assert previous.id != current.id


def test_departure_times_are_stored_in_utc(loaded, golden_day: dict[str, Any]) -> None:
    """Storage is UTC. IST is applied at the edge, when a human reads it."""
    entry = next(item for item in golden_day["pairs"] if item["pair"] == "A")
    quote = loaded.current_quotes["A"]
    assert quote.departure_ts is not None
    assert quote.departure_ts.utcoffset().total_seconds() == 0

    rendered_ist = quote.departure_ts.astimezone(IST)
    assert rendered_ist.strftime("%H:%M:%S") == entry["departure_time"]
    assert quote.departure_ts.astimezone(UTC).hour == 2  # 07:45 IST


def test_the_stratum_chain_link_is_representable(
    loaded, app_session: Session, refs: SeedRefs, golden_day: dict[str, Any]
) -> None:
    """The prior index value is stored on the observation, because the index is chained.

    This asserts the schema can hold the chain, not that the value is right:
    computing it is Phase 9.
    """
    from tests.support.builders import make_index_observation, make_weight_set

    weight_set = make_weight_set(
        app_session,
        version="test_weight_set_golden_day",
        effective_from=date(2026, 1, 1),
        source_note="synthetic weight set built inside a test; never sourced evidence",
    )
    observation = make_index_observation(
        app_session,
        refs,
        obs_date=loaded.current_date,
        level="STRATUM",
        weight_set=weight_set,
        index_value=Decimal(golden_day["expected_stratum_index"]),
        prev_index_value=Decimal(golden_day["prior_stratum_index"]),
        ref_id=refs.routes[loaded.route_code],
        bucket_id=refs.buckets[loaded.bucket_code],
        input_quote_count=4,
    )

    stored = app_session.get(type(observation), observation.id)
    assert stored is not None
    assert stored.prev_index_value == Decimal("100.000000")
    assert stored.index_value == Decimal("102.313000")
    assert isinstance(stored.index_value, Decimal)


def test_expected_index_is_recorded_as_a_target_not_computed_here(
    golden_day: dict[str, Any],
) -> None:
    """Phase 3 stores the expectation. Phase 9 has to earn it."""
    assert golden_day["expected_stratum_index"] == "102.313"
    assert golden_day["prior_stratum_index"] == "100.000000"
    note = " ".join(golden_day["expected_stratum_index_note"])
    assert "PHASE 9" in note
    assert "does not compute the index" in note


def test_the_fixture_survives_a_full_reread(loaded, app_session: Session) -> None:
    """Expire everything and read it back from PostgreSQL, not from the identity map."""
    expected = {
        (quote.flight_no, quote.collected_date, quote.total_fare) for quote in loaded.all_quotes
    }
    app_session.expire_all()

    rows = app_session.execute(
        text(
            """
            SELECT flight_no, collected_date, total_fare
            FROM normalised_quote
            ORDER BY collected_date, flight_no
            """
        )
    ).all()
    assert {(row.flight_no, row.collected_date, row.total_fare) for row in rows} == expected
    assert all(isinstance(row.total_fare, Decimal) for row in rows)
