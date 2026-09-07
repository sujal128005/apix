"""Pipeline tests, written to fight the code rather than confirm it.

Most of these feed something malformed, ambiguous or subtly wrong and assert the
pipeline notices. The ones that matter most are the pairing tests: a chained
index built on mismatched pairs produces smooth, plausible, wrong numbers, and
nothing downstream would flag it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from pipeline.impute import StratumState, imputation_rate, impute_missing
from pipeline.normalise import (
    NormalisationError,
    ObservedQuote,
    StratumKey,
    build_matched_pairs,
    group_by_stratum,
    normalise_payload,
    score_quality,
)
from schemas.enums import Confidence, ImputationCode, MissingReason, Provenance, QualityStatus

ROUTE, BUCKET = uuid4(), uuid4()
DAY = date(2026, 9, 7)
STRATUM = StratumKey(route_id=ROUTE, bucket_id=BUCKET, collected_date=DAY)


def payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "carrier": "6E",
        "flight_no": "6E2134",
        "fare_brand": "SAVER",
        "total_fare": "5499.00",
        "currency": "INR",
    }
    base.update(overrides)
    return base


def quote(key: str, fare: str, *, stratum: StratumKey = STRATUM) -> ObservedQuote:
    return ObservedQuote(
        stratum=stratum,
        pair_key=key,
        total_fare=Decimal(fare),
        provenance=Provenance.LIVE_COLLECTED,
    )


# -- normalisation: refusals ----------------------------------------------


def test_a_float_fare_is_refused() -> None:
    """Money must not arrive through binary floating point."""
    with pytest.raises(NormalisationError, match="float"):
        normalise_payload(payload(total_fare=5499.00))


@pytest.mark.parametrize("value", ["0", "-100", "0.00"])
def test_a_non_positive_fare_is_refused(value: str) -> None:
    with pytest.raises(NormalisationError, match="must be positive"):
        normalise_payload(payload(total_fare=value))


@pytest.mark.parametrize("carrier", ["", "X", "SIX", "6e7"])
def test_a_malformed_carrier_is_refused(carrier: str) -> None:
    with pytest.raises(NormalisationError, match="2-character IATA"):
        normalise_payload(payload(carrier=carrier))


def test_a_foreign_currency_is_refused_rather_than_converted() -> None:
    """Converting would smuggle an exchange-rate series into a price index."""
    with pytest.raises(NormalisationError, match="out of scope"):
        normalise_payload(payload(currency="USD"))


@pytest.mark.parametrize("value", ["not-a-number", "", "₹₹₹"])
def test_an_unparseable_amount_is_refused(value: str) -> None:
    with pytest.raises(NormalisationError):
        normalise_payload(payload(total_fare=value))


# -- normalisation: tolerances --------------------------------------------


def test_indian_formatting_is_parsed() -> None:
    assert normalise_payload(payload(total_fare="₹12,499.50")).total_fare == Decimal("12499.50")


def test_a_lowercase_carrier_is_normalised() -> None:
    assert normalise_payload(payload(carrier="6e")).carrier == "6E"


def test_a_missing_breakdown_is_usable_not_fatal() -> None:
    """The total is the index price. A missing decomposition is a lesser flaw."""
    fields = normalise_payload(payload())
    assert fields.total_fare == Decimal("5499.00")
    assert fields.quality_status == QualityStatus.PARTIAL
    assert fields.missing_reason == MissingReason.PARTIAL_COMPONENTS
    assert fields.component_confidence == Confidence.LOW


def test_components_exceeding_the_total_flag_but_do_not_reject() -> None:
    """Bad breakdown, good price: keep the observation, mark the breakdown."""
    fields = normalise_payload(payload(base_fare="5000", taxes="900", udf="200"))
    assert fields.total_fare == Decimal("5499.00")
    assert fields.quality_status == QualityStatus.PARTIAL
    assert fields.component_confidence == Confidence.LOW


def test_a_consistent_breakdown_is_complete() -> None:
    fields = normalise_payload(payload(base_fare="4200", taxes="899", udf="400"))
    assert fields.quality_status == QualityStatus.COMPLETE
    assert fields.component_confidence == Confidence.HIGH


# -- quality scoring -------------------------------------------------------


def test_an_unmatchable_quote_scores_lower() -> None:
    """No flight number means it can never be paired across days."""
    full = score_quality(
        normalise_payload(payload(base_fare="4200", taxes="899", udf="400")),
        provenance=Provenance.LIVE_COLLECTED,
    )
    anonymous = score_quality(
        normalise_payload(payload(flight_no=None, base_fare="4200", taxes="899", udf="400")),
        provenance=Provenance.LIVE_COLLECTED,
    )
    assert anonymous < full


def test_simulated_data_scores_far_lower() -> None:
    fields = normalise_payload(payload(base_fare="4200", taxes="899", udf="400"))
    assert score_quality(fields, provenance=Provenance.SIMULATED_DEMO) <= Decimal("0.5")


# -- pairing: the tests that matter ---------------------------------------


def test_only_the_same_priced_unit_is_paired() -> None:
    """A different flight is a different product, not a price change."""
    previous = [quote("6E|6E2134|SAVER", "5000"), quote("SG|SG8194|SAVER", "6000")]
    current = [quote("6E|6E2134|SAVER", "5500"), quote("SG|SG8194|SAVER", "6600")]

    pairs, unmatched, gone = build_matched_pairs(previous, current)
    assert len(pairs) == 2
    assert not unmatched and not gone
    assert {p.key for p in pairs} == {"6E|6E2134|SAVER", "SG|SG8194|SAVER"}


def test_a_cheaper_competitor_does_not_masquerade_as_a_price_fall() -> None:
    """The failure mode that would silently corrupt the index.

    Yesterday's cheapest was IndiGo at 6000; today's is SpiceJet at 4000. Naive
    "cheapest vs cheapest" pairing reports a 33% fall. In fact IndiGo rose and a
    different airline appeared - a substitution, not deflation.
    """
    previous = [quote("6E|6E2134|SAVER", "6000")]
    current = [quote("6E|6E2134|SAVER", "6300"), quote("SG|SG8194|PROMO", "4000")]

    pairs, unmatched, _gone = build_matched_pairs(previous, current)

    assert len(pairs) == 1
    assert pairs[0].key == "6E|6E2134|SAVER"
    assert pairs[0].relative == Decimal("1.05"), "the index sees a 5% rise, correctly"
    assert unmatched == ["SG|SG8194|PROMO"], "the new entrant is reported, not paired"


def test_a_fare_brand_change_is_not_a_price_change() -> None:
    """Same flight, different brand: a different product at a different price."""
    previous = [quote("6E|6E2134|SAVER", "5000")]
    current = [quote("6E|6E2134|FLEXI", "8000")]

    pairs, unmatched, gone = build_matched_pairs(previous, current)
    assert pairs == []
    assert unmatched == ["6E|6E2134|FLEXI"]
    assert gone == ["6E|6E2134|SAVER"]


def test_duplicates_within_a_period_collapse_to_the_lowest_fare() -> None:
    previous = [quote("6E|6E2134|SAVER", "5000")]
    current = [
        quote("6E|6E2134|SAVER", "6000"),
        quote("6E|6E2134|SAVER", "5500"),
        quote("6E|6E2134|SAVER", "5800"),
    ]
    pairs, _, _ = build_matched_pairs(previous, current)
    assert len(pairs) == 1
    assert pairs[0].current == Decimal("5500")


def test_a_withdrawn_flight_is_reported_not_silently_dropped() -> None:
    previous = [quote("6E|6E2134|SAVER", "5000"), quote("6E|6E9999|SAVER", "7000")]
    current = [quote("6E|6E2134|SAVER", "5200")]

    pairs, _unmatched, gone = build_matched_pairs(previous, current)
    assert len(pairs) == 1
    assert gone == ["6E|6E9999|SAVER"]


def test_pairing_is_deterministic_regardless_of_input_order() -> None:
    previous = [quote("B", "5000"), quote("A", "6000"), quote("C", "7000")]
    current = [quote("C", "7700"), quote("A", "6600"), quote("B", "5500")]

    first, _, _ = build_matched_pairs(previous, current)
    second, _, _ = build_matched_pairs(list(reversed(previous)), list(reversed(current)))
    assert [p.key for p in first] == [p.key for p in second]


def test_no_overlap_produces_no_pairs_and_no_crash() -> None:
    pairs, unmatched, gone = build_matched_pairs([quote("A", "5000")], [quote("B", "6000")])
    assert pairs == []
    assert unmatched == ["B"] and gone == ["A"]


# -- grouping --------------------------------------------------------------


def test_quotes_group_into_their_strata() -> None:
    other = StratumKey(route_id=ROUTE, bucket_id=uuid4(), collected_date=DAY)
    grouped = group_by_stratum(
        [quote("A", "5000"), quote("B", "6000"), quote("C", "7000", stratum=other)]
    )
    assert len(grouped) == 2
    assert len(grouped[STRATUM]) == 2


# -- imputation ------------------------------------------------------------


def test_a_missing_stratum_moves_with_its_comparables() -> None:
    """Not carried flat: a flat carry understates inflation every time."""
    state = StratumState(ref="DEL-BOM|T7", previous_index=Decimal("100"))
    result = impute_missing(state, [Decimal("1.10"), Decimal("1.10"), Decimal("1.10")])

    assert result is not None
    assert result.index_value == Decimal("110.000000")
    assert result.imputation_code == ImputationCode.Y
    assert result.donor_count == 3


def test_imputation_uses_a_geometric_mean_of_donors() -> None:
    state = StratumState(ref="X", previous_index=Decimal("100"))
    result = impute_missing(state, [Decimal("1.00"), Decimal("1.21")])
    assert result is not None
    assert result.index_value == Decimal("110.000000")  # sqrt(1.00 * 1.21) = 1.10


def test_imputation_without_donors_returns_nothing() -> None:
    """An unknown value stays unknown rather than being invented."""
    state = StratumState(ref="X", previous_index=Decimal("100"))
    assert impute_missing(state, []) is None


def test_imputation_stops_after_a_bounded_run() -> None:
    """Past a point the stratum is not missing, it is gone."""
    state = StratumState(ref="X", previous_index=Decimal("100"), consecutive_imputations=30)
    assert impute_missing(state, [Decimal("1.05")], max_consecutive=30) is None


def test_consecutive_imputations_are_counted() -> None:
    state = StratumState(ref="X", previous_index=Decimal("100"), consecutive_imputations=4)
    result = impute_missing(state, [Decimal("1.02")])
    assert result is not None
    assert result.consecutive_imputations == 5
    assert "5 consecutive period(s)" in result.reason


def test_the_reason_names_the_cause() -> None:
    state = StratumState(ref="X", previous_index=Decimal("100"))
    result = impute_missing(state, [Decimal("1.02")], missing_reason=MissingReason.SOLD_OUT)
    assert result is not None
    assert result.missing_reason == MissingReason.SOLD_OUT
    assert MissingReason.SOLD_OUT in result.reason


@pytest.mark.parametrize(
    ("total", "imputed", "expected"),
    [(100, 0, "0.000"), (100, 25, "0.250"), (3, 1, "0.333"), (0, 0, "0.000")],
)
def test_imputation_rate(total: int, imputed: int, expected: str) -> None:
    assert imputation_rate(total, imputed) == Decimal(expected)
