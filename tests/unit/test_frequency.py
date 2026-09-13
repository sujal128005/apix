"""Daily, weekly and monthly aggregation.

PS 26056 asks for all three. The load-bearing decision is that weekly and
monthly are *averages* of the daily values, not the value on the last day.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from pipeline.frequency import Frequency, aggregate_to_frequency, period_key


def series(start: date, values: list[str]) -> list[tuple[date, Decimal]]:
    from datetime import timedelta

    return [
        (start + timedelta(days=i), Decimal(v)) for i, v in enumerate(values)
    ]


# -- the choice of average over snapshot -----------------------------------


def test_a_period_is_the_mean_of_its_days_not_the_last_day() -> None:
    """CPI is a monthly average concept.

    The published figure answers "what did prices do over this month", not
    "where was the index on the 30th". A period-end snapshot answers a different
    question and carries the day-of-week effect the average exists to absorb.
    """
    # Monday to Sunday, ending high.
    weekly = aggregate_to_frequency(
        series(date(2026, 9, 7), ["100", "100", "100", "100", "100", "100", "170"]),
        Frequency.WEEKLY,
    )
    assert len(weekly) == 1
    assert weekly[0].index_value == Decimal("110.000000"), "the mean, not 170"


def test_the_daily_frequency_returns_each_day_unchanged() -> None:
    daily = aggregate_to_frequency(series(date(2026, 9, 7), ["100", "110"]), Frequency.DAILY)
    assert [d.index_value for d in daily] == [Decimal("100.000000"), Decimal("110.000000")]


# -- period boundaries -----------------------------------------------------


def test_weeks_are_iso_weeks_monday_to_sunday() -> None:
    """ISO rather than a rolling seven days, so "week 37" means the same span to
    every consumer, including one joining this series to another."""
    start, end, label = period_key(date(2026, 9, 10), Frequency.WEEKLY)  # a Thursday
    assert start.weekday() == 0 and end.weekday() == 6
    assert start == date(2026, 9, 7)
    assert end == date(2026, 9, 13)
    assert label == "2026-W37"


def test_a_sunday_belongs_to_the_week_that_began_on_monday() -> None:
    start, _, label = period_key(date(2026, 9, 13), Frequency.WEEKLY)
    assert start == date(2026, 9, 7)
    assert label == "2026-W37"


def test_months_run_to_their_real_length() -> None:
    for day, expected_end, days in (
        (date(2026, 2, 15), date(2026, 2, 28), 28),
        (date(2026, 9, 15), date(2026, 9, 30), 30),
        (date(2026, 12, 15), date(2026, 12, 31), 31),
    ):
        start, end, _ = period_key(day, Frequency.MONTHLY)
        assert end == expected_end
        assert (end - start).days + 1 == days


def test_december_rolls_into_the_next_year() -> None:
    _, end, label = period_key(date(2026, 12, 5), Frequency.MONTHLY)
    assert end == date(2026, 12, 31)
    assert label == "2026-12"


# -- partial periods -------------------------------------------------------


def test_a_partial_period_is_flagged_not_suppressed() -> None:
    """Hiding it loses information; publishing it unmarked lets a reader compare
    a part-month against a full one and conclude something false."""
    monthly = aggregate_to_frequency(
        series(date(2026, 9, 1), ["100"] * 10), Frequency.MONTHLY
    )
    assert len(monthly) == 1
    assert monthly[0].is_complete is False
    assert monthly[0].days_observed == 10
    assert monthly[0].days_in_period == 30
    assert monthly[0].coverage_pct == Decimal("33.3")


def test_a_complete_period_is_marked_complete() -> None:
    weekly = aggregate_to_frequency(
        series(date(2026, 9, 7), ["100"] * 7), Frequency.WEEKLY
    )
    assert weekly[0].is_complete is True
    assert weekly[0].coverage_pct == Decimal("100.0")


def test_a_gap_within_a_period_reduces_coverage() -> None:
    observations = [
        (date(2026, 9, 7), Decimal("100")),
        (date(2026, 9, 9), Decimal("100")),
        (date(2026, 9, 11), Decimal("100")),
    ]
    weekly = aggregate_to_frequency(observations, Frequency.WEEKLY)
    assert weekly[0].days_observed == 3
    assert weekly[0].is_complete is False


# -- movement --------------------------------------------------------------


def test_movement_is_measured_between_period_averages() -> None:
    """Not by chaining daily movements across a boundary, which would compound
    day-of-week effects into the weekly series."""
    observations = series(date(2026, 9, 7), ["100"] * 7) + series(
        date(2026, 9, 14), ["110"] * 7
    )
    weekly = aggregate_to_frequency(observations, Frequency.WEEKLY)

    assert weekly[1].previous_index_value == Decimal("100.000000")
    assert weekly[1].movement == Decimal("10.000000")
    assert weekly[1].movement_pct == Decimal("10.000")


def test_the_first_period_has_no_movement() -> None:
    weekly = aggregate_to_frequency(series(date(2026, 9, 7), ["100"] * 7), Frequency.WEEKLY)
    assert weekly[0].movement is None
    assert weekly[0].movement_pct is None


# -- edges -----------------------------------------------------------------


def test_an_empty_series_produces_no_periods() -> None:
    assert aggregate_to_frequency([], Frequency.MONTHLY) == []


def test_periods_come_back_in_order() -> None:
    observations = series(date(2026, 8, 25), ["100"] * 20)
    for frequency in Frequency:
        periods = aggregate_to_frequency(observations, frequency)
        assert [p.label for p in periods] == sorted(p.label for p in periods)


@pytest.mark.parametrize("frequency", list(Frequency))
def test_unsorted_input_is_handled(frequency: Frequency) -> None:
    observations = list(reversed(series(date(2026, 9, 1), ["100", "110", "120"])))
    periods = aggregate_to_frequency(observations, frequency)
    assert periods
    assert all(p.index_value > 0 for p in periods)
