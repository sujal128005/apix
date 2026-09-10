"""Backtest engine: compare movements, and refuse when there is nothing to compare."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from pipeline.backtest import (
    MonthlyPoint,
    compare_movements,
    monthly_average,
)


def pt(year: int, month: int, value: str) -> MonthlyPoint:
    return MonthlyPoint(year=year, month=month, value=Decimal(value))


# -- monthly aggregation ---------------------------------------------------


def test_daily_values_collapse_to_a_monthly_mean() -> None:
    """The arithmetic mean, because CPI is a monthly average concept."""
    daily = [
        (date(2026, 1, 1), Decimal("100")),
        (date(2026, 1, 2), Decimal("110")),
        (date(2026, 1, 3), Decimal("120")),
        (date(2026, 2, 1), Decimal("130")),
    ]
    months = monthly_average(daily)
    assert len(months) == 2
    assert months[0].value == Decimal("110.000000")
    assert months[1].value == Decimal("130.000000")


def test_months_come_back_in_order() -> None:
    daily = [(date(2026, 3, 1), Decimal("100")), (date(2026, 1, 1), Decimal("90"))]
    assert [m.label for m in monthly_average(daily)] == ["2026-01", "2026-03"]


# -- the comparison --------------------------------------------------------


def test_movements_are_compared_not_levels() -> None:
    """Two series on different bases can still be compared on movement.

    APIx near 100 and CPI near 125 are not comparable as levels. Both rising
    10% is the same fact about the world, and that is what is measured.
    """
    apix = [pt(2026, 1, "100"), pt(2026, 2, "110"), pt(2026, 3, "121"), pt(2026, 4, "133.1")]
    benchmark = [pt(2026, 1, "125"), pt(2026, 2, "137.5"), pt(2026, 3, "151.25"),
                 pt(2026, 4, "166.375")]

    result = compare_movements(apix, benchmark)

    assert result.sufficient is True
    assert result.mae == Decimal("0.000000"), "identical movements, despite different levels"
    assert result.directional_agreement == Decimal("100.00")


def test_opposite_movements_are_caught() -> None:
    apix = [pt(2026, 1, "100"), pt(2026, 2, "110"), pt(2026, 3, "121"), pt(2026, 4, "133")]
    benchmark = [pt(2026, 1, "100"), pt(2026, 2, "90"), pt(2026, 3, "81"), pt(2026, 4, "73")]

    result = compare_movements(apix, benchmark)
    assert result.sufficient is True
    assert result.directional_agreement == Decimal("0.00")
    assert result.mae > Decimal("15")


def test_error_metrics_are_computed_on_the_aligned_months_only() -> None:
    apix = [pt(2026, 1, "100"), pt(2026, 2, "110"), pt(2026, 3, "121"), pt(2026, 4, "133.1")]
    benchmark = [pt(2026, 2, "100"), pt(2026, 3, "110"), pt(2026, 4, "121"), pt(2026, 5, "133.1")]

    result = compare_movements(apix, benchmark)
    assert [m.label for m in result.aligned] == ["2026-03", "2026-04"]


# -- the refusals ----------------------------------------------------------


def test_no_overlap_produces_no_metrics_and_says_why() -> None:
    """The case this project actually hits.

    APIx begins after the benchmark ends, so nothing aligns. Reporting an MAE
    here would require inventing an overlap.
    """
    apix = [pt(2026, 8, "100"), pt(2026, 9, "104")]
    benchmark = [pt(2026, 5, "127"), pt(2026, 6, "126"), pt(2026, 7, "125")]

    result = compare_movements(apix, benchmark)

    assert result.sufficient is False
    assert result.mae is None
    assert result.rmse is None
    assert result.aligned == ()
    assert "No overlapping months" in result.limitation
    assert "2026-08" in result.limitation and "2026-07" in result.limitation


def test_too_few_aligned_months_produces_no_metrics() -> None:
    """One aligned month is arithmetic, not evidence."""
    apix = [pt(2026, 6, "100"), pt(2026, 7, "110")]
    benchmark = [pt(2026, 6, "125"), pt(2026, 7, "130")]

    result = compare_movements(apix, benchmark)

    assert result.sufficient is False
    assert result.mae is None
    assert len(result.aligned) == 1, "the aligned month is still shown for inspection"
    assert "statistical content" in result.limitation


def test_the_minimum_is_configurable_but_defaults_to_three() -> None:
    apix = [pt(2026, 6, "100"), pt(2026, 7, "110")]
    benchmark = [pt(2026, 6, "125"), pt(2026, 7, "130")]
    assert compare_movements(apix, benchmark, min_months=1).sufficient is True


def test_a_limitation_is_always_stated_even_when_metrics_exist() -> None:
    """Sufficient overlap does not make levels comparable."""
    apix = [pt(2026, 1, "100"), pt(2026, 2, "110"), pt(2026, 3, "121"), pt(2026, 4, "133")]
    benchmark = [pt(2026, 1, "125"), pt(2026, 2, "137"), pt(2026, 3, "151"), pt(2026, 4, "166")]

    result = compare_movements(apix, benchmark)
    assert result.sufficient is True
    assert "not comparable" in result.limitation
    assert "Movements only" in result.limitation


@pytest.mark.parametrize(
    ("apix_move", "bench_move", "agree"),
    [("110", "110", True), ("110", "90", False), ("100", "100", True), ("110", "100", False)],
)
def test_directional_agreement_treats_flat_as_its_own_case(
    apix_move: str, bench_move: str, agree: bool
) -> None:
    """A flat month is neither a rise nor a fall, and must not be counted as either."""
    apix = [pt(2026, 1, "100"), pt(2026, 2, apix_move)]
    benchmark = [pt(2026, 1, "100"), pt(2026, 2, bench_move)]
    result = compare_movements(apix, benchmark, min_months=1)
    assert result.aligned[0].same_direction is agree


def test_an_empty_series_does_not_crash() -> None:
    result = compare_movements([], [pt(2026, 1, "100")])
    assert result.sufficient is False
    assert result.aligned == ()
