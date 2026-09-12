"""Sampling uncertainty for the index."""

from __future__ import annotations

from decimal import Decimal

from index_engine.jevons import MatchedPair
from pipeline.uncertainty import aggregate_standard_error, stratum_uncertainty


def pairs(relatives: list[str]) -> list[MatchedPair]:
    return [
        MatchedPair(
            key=str(i), previous=Decimal("5000"), current=Decimal("5000") * Decimal(r)
        )
        for i, r in enumerate(relatives)
    ]


def test_identical_relatives_give_a_zero_standard_error() -> None:
    """No dispersion means no sampling uncertainty - the flights agree exactly."""
    u = stratum_uncertainty(pairs(["1.1"] * 6), Decimal("110"))
    assert u.standard_error == Decimal("0.000000")
    assert u.lower_95 == u.upper_95 == Decimal("110.000000")


def test_dispersed_relatives_widen_the_interval() -> None:
    tight = stratum_uncertainty(pairs(["1.09", "1.10", "1.11"]), Decimal("110"))
    loose = stratum_uncertainty(pairs(["0.80", "1.10", "1.45"]), Decimal("110"))
    assert loose.standard_error > tight.standard_error


def test_more_observations_narrow_the_interval() -> None:
    """se scales with 1/sqrt(n): the reason stratum size matters."""
    few = stratum_uncertainty(pairs(["0.95", "1.10", "1.25"]), Decimal("110"))
    many = stratum_uncertainty(pairs(["0.95", "1.10", "1.25"] * 4), Decimal("110"))
    assert many.standard_error < few.standard_error


def test_a_single_observation_has_no_estimable_variance() -> None:
    """Reported as unknown, never as zero.

    Printing 0.000 would read as perfect precision rather than as no
    information, which is the opposite of what one observation tells you.
    """
    u = stratum_uncertainty(pairs(["1.1"]), Decimal("110"))
    assert u.is_estimable is False
    assert u.standard_error is None
    assert "not estimable" in u.note


def test_the_note_states_what_the_interval_excludes() -> None:
    """Basket, weighting and coverage error are larger sources here than sampling.

    An interval presented as though it bounded total error would overstate what
    is known, so the exclusion travels with the number.
    """
    u = stratum_uncertainty(pairs(["1.09", "1.10", "1.11"]), Decimal("110"))
    assert "sampling error only" in u.note
    assert "weighting" in u.note


def test_relative_standard_error_is_reported_for_quality_assessment() -> None:
    u = stratum_uncertainty(pairs(["0.95", "1.10", "1.25"]), Decimal("110"))
    assert u.relative_standard_error_pct is not None
    assert u.relative_standard_error_pct > 0


def test_small_samples_use_a_wider_multiplier() -> None:
    """Below eight observations a normal multiplier understates the interval."""
    small = stratum_uncertainty(pairs(["0.95", "1.10", "1.25"]), Decimal("110"))
    width = (small.upper_95 or Decimal(0)) - (small.lower_95 or Decimal(0))
    naive = 2 * Decimal("1.96") * (small.standard_error or Decimal(0))
    assert width > naive, "a t-multiplier must widen the interval at n=3"


# -- aggregation -----------------------------------------------------------


def test_aggregate_error_combines_weighted_components() -> None:
    se = aggregate_standard_error(
        [(Decimal("0.5"), Decimal("2.0")), (Decimal("0.5"), Decimal("2.0"))]
    )
    assert se is not None
    assert se < Decimal("2.0"), "averaging independent components reduces error"


def test_components_without_an_estimate_are_skipped() -> None:
    se = aggregate_standard_error(
        [(Decimal("0.5"), Decimal("2.0")), (Decimal("0.5"), None)]
    )
    assert se is not None


def test_nothing_estimable_returns_nothing() -> None:
    assert aggregate_standard_error([(Decimal("1"), None)]) is None
