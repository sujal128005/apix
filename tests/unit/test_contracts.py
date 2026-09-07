"""Contract validation: the boundary rejects what the database cannot catch.

Most invariants belong in PostgreSQL, and they are there. Two do not:

* a naive ``datetime`` written to a TIMESTAMPTZ column is silently reinterpreted
  in the session time zone rather than rejected, so the only place to stop it is
  before the driver sees it;
* a float where money belongs would already have lost precision by the time it
  reached a NUMERIC column.

The rest of the checks here mirror database constraints deliberately: failing
fast at the boundary produces a better error than a driver exception, without
either layer being load-bearing on its own.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from schemas import contracts
from schemas.enums import ImputationCode, IndexLevel, Provenance, QualityStatus
from schemas.uuid7 import uuid7

AWARE = datetime(2026, 3, 3, 6, 30, tzinfo=UTC)
NAIVE = datetime(2026, 3, 3, 6, 30)


def quote_kwargs(**overrides: object) -> dict[str, object]:
    """A valid normalised_quote payload, before any override."""
    base: dict[str, object] = {
        "id": uuid7(),
        "created_at": AWARE,
        "raw_quote_id": uuid7(),
        "route_id": uuid4(),
        "bucket_id": uuid4(),
        "source_id": uuid4(),
        "carrier": "6E",
        "flight_no": "6E2001",
        "departure_ts": AWARE,
        "arrival_ts": None,
        "lead_time_days": 7,
        "fare_brand": "SAVER",
        "total_fare": Decimal("5000.00"),
        "currency": "INR",
        "collected_at": AWARE,
        "collected_date": date(2026, 3, 3),
        "provenance": Provenance.LIVE_COLLECTED,
        "quality_status": QualityStatus.COMPLETE,
        "quality_score": None,
        "imputation_code": ImputationCode.N,
        "missing_reason": "NONE",
        "component_confidence": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# timezone awareness - adversarial case `naive_departure_timestamp`
# ---------------------------------------------------------------------------
def test_naive_departure_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        contracts.NormalisedQuote(**quote_kwargs(departure_ts=NAIVE))


def test_naive_collected_at_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        contracts.NormalisedQuote(**quote_kwargs(collected_at=NAIVE))


def test_aware_timestamps_are_accepted() -> None:
    quote = contracts.NormalisedQuote(**quote_kwargs())
    assert quote.departure_ts is not None
    assert quote.departure_ts.tzinfo is not None


# ---------------------------------------------------------------------------
# money
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fare", [Decimal("0.00"), Decimal("-100.00")])
def test_non_positive_fares_are_rejected(fare: Decimal) -> None:
    with pytest.raises(ValidationError, match=r"greater_than|greater than"):
        contracts.NormalisedQuote(**quote_kwargs(total_fare=fare))


def test_fare_scale_beyond_two_places_is_rejected() -> None:
    """NUMERIC(12,2) would round it; the contract refuses to lose the difference."""
    with pytest.raises(ValidationError, match=r"decimal_places|decimal places"):
        contracts.NormalisedQuote(**quote_kwargs(total_fare=Decimal("5000.005")))


def test_fare_stays_a_decimal() -> None:
    quote = contracts.NormalisedQuote(**quote_kwargs())
    assert isinstance(quote.total_fare, Decimal)


def test_currency_must_be_inr_this_phase() -> None:
    with pytest.raises(ValidationError):
        contracts.NormalisedQuote(**quote_kwargs(currency="USD"))


# ---------------------------------------------------------------------------
# provenance and imputation
# ---------------------------------------------------------------------------
def test_provenance_is_required() -> None:
    kwargs = quote_kwargs()
    del kwargs["provenance"]
    with pytest.raises(ValidationError, match="provenance"):
        contracts.NormalisedQuote(**kwargs)


def test_provenance_cannot_be_null() -> None:
    with pytest.raises(ValidationError, match="provenance"):
        contracts.NormalisedQuote(**quote_kwargs(provenance=None))


def test_unknown_provenance_is_rejected() -> None:
    with pytest.raises(ValidationError):
        contracts.NormalisedQuote(**quote_kwargs(provenance="GUESSED"))


def test_a_non_imputed_quote_must_reference_a_raw_quote() -> None:
    with pytest.raises(ValidationError, match="imputed"):
        contracts.NormalisedQuote(
            **quote_kwargs(raw_quote_id=None, imputation_code=ImputationCode.N)
        )


def test_an_imputed_quote_may_have_no_raw_quote() -> None:
    quote = contracts.NormalisedQuote(
        **quote_kwargs(
            raw_quote_id=None,
            imputation_code=ImputationCode.Y,
            missing_reason="CHAIN_GAP",
        )
    )
    assert quote.raw_quote_id is None
    assert quote.imputation_code is ImputationCode.Y


# ---------------------------------------------------------------------------
# reference data
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("iata", ["XX", "DELH", "del", "D3L", "   "])
def test_invalid_iata_codes_are_rejected(iata: str) -> None:
    with pytest.raises(ValidationError):
        contracts.Airport(
            id=uuid7(),
            created_at=AWARE,
            iata=iata,
            icao=None,
            name="Test",
            city="Test",
            state="Test",
            tz="Asia/Kolkata",
            active=True,
        )


def test_valid_iata_is_accepted() -> None:
    airport = contracts.Airport(
        id=uuid7(),
        created_at=AWARE,
        iata="DEL",
        icao=None,
        name="Indira Gandhi International Airport",
        city="Delhi",
        state="Delhi",
        tz="Asia/Kolkata",
        active=True,
    )
    assert airport.iata == "DEL"


@pytest.mark.parametrize("code", ["DEL_BOM", "DELBOM", "del-bom", "DEL-BOMB"])
def test_invalid_route_codes_are_rejected(code: str) -> None:
    with pytest.raises(ValidationError):
        contracts.Route(
            id=uuid7(),
            created_at=AWARE,
            code=code,
            origin_id=uuid4(),
            destination_id=uuid4(),
            directional=True,
            active=True,
        )


# ---------------------------------------------------------------------------
# collection
# ---------------------------------------------------------------------------
def request_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": uuid7(),
        "created_at": AWARE,
        "job_id": uuid4(),
        "source_id": uuid4(),
        "route_id": uuid4(),
        "bucket_id": uuid4(),
        "travel_date": date(2026, 3, 10),
        "collected_date": date(2026, 3, 3),
        "query_hash": "a" * 64,
    }
    base.update(overrides)
    return base


def test_travel_date_before_collected_date_is_rejected() -> None:
    with pytest.raises(ValidationError, match="precedes"):
        contracts.CollectionRequest(**request_kwargs(travel_date=date(2026, 3, 2)))


def test_same_day_travel_is_allowed() -> None:
    """T+0 is not a bucket, but the boundary rejects only the impossible case."""
    request = contracts.CollectionRequest(**request_kwargs(travel_date=date(2026, 3, 3)))
    assert request.travel_date == request.collected_date


def test_query_hash_must_look_like_sha256() -> None:
    with pytest.raises(ValidationError):
        contracts.CollectionRequest(**request_kwargs(query_hash="not-a-hash"))


# ---------------------------------------------------------------------------
# index
# ---------------------------------------------------------------------------
def observation_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": uuid7(),
        "created_at": AWARE,
        "obs_date": date(2026, 3, 3),
        "level": IndexLevel.HEADLINE,
        "ref_id": None,
        "bucket_id": None,
        "index_value": Decimal("102.313000"),
        "prev_index_value": Decimal("100.000000"),
        "base_period_id": None,
        "methodology_version_id": uuid4(),
        "weight_set_version_id": uuid4(),
        "input_quote_count": 3,
        "excluded_count": 1,
        "imputed_count": 0,
        "routes_in_basket": 1,
        "input_hash": "b" * 64,
        "computed_at": AWARE,
    }
    base.update(overrides)
    return base


def test_headline_may_not_carry_a_ref_id() -> None:
    with pytest.raises(ValidationError, match="ref_id"):
        contracts.IndexObservation(**observation_kwargs(ref_id=uuid4()))


def test_route_level_may_carry_a_ref_id() -> None:
    observation = contracts.IndexObservation(
        **observation_kwargs(level=IndexLevel.ROUTE, ref_id=uuid4())
    )
    assert observation.ref_id is not None


def test_index_value_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        contracts.IndexObservation(**observation_kwargs(index_value=Decimal("0.000000")))


def test_benchmark_requires_a_citation() -> None:
    with pytest.raises(ValidationError):
        contracts.BenchmarkObservation(
            id=uuid7(),
            created_at=AWARE,
            bench_source="test",
            period="2026-03",
            ref=None,
            value=Decimal("100.0000"),
            definition="test",
            citation_url="",
            citation_page=None,
            retrieved_at=AWARE,
        )


def test_backtest_requires_stated_limitations() -> None:
    with pytest.raises(ValidationError):
        contracts.BacktestRun(
            id=uuid7(),
            created_at=AWARE,
            window_start=date(2026, 1, 1),
            window_end=date(2026, 2, 1),
            tier=1,
            metrics={},
            limitations="",
            input_hash="c" * 64,
            run_at=AWARE,
        )


# ---------------------------------------------------------------------------
# shape
# ---------------------------------------------------------------------------
def test_unknown_fields_are_refused() -> None:
    """extra='forbid' turns a schema drift into a loud failure, not silent loss."""
    with pytest.raises(ValidationError):
        contracts.NormalisedQuote(**quote_kwargs(nonexistent_column="x"))


def test_lambda_field_is_named_lambda_underscore() -> None:
    """`lambda` is reserved in Python; the database column keeps the brief's name."""
    bucket = contracts.LeadTimeBucket(
        id=uuid7(),
        created_at=AWARE,
        code="T21",
        days=21,
        lambda_=Decimal("0.166667"),
        cpi_comparable=True,
    )
    assert bucket.lambda_ == Decimal("0.166667")
    assert bucket.cpi_comparable is True
