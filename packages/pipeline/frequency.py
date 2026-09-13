"""Daily, weekly, monthly — the three frequencies PS 26056 asks for.

APIx computes a daily index. Weekly and monthly figures are **averages of the
daily values within the period**, not the value on the last day.

That choice is the whole content of this module, so it is worth stating why.
CPI is a monthly *average* concept: the published figure answers "what did
prices do over this month", not "where was the index on the 30th". Taking an
end-of-period snapshot would answer a different question and would be far more
volatile, because airfare on any single day carries a day-of-week effect that
the monthly average is meant to absorb.

**Partial periods are labelled, not hidden.** A month with eleven days of
collection produces a figure from eleven days, and says so. Suppressing it would
lose information; publishing it unmarked would let a reader compare a partial
month against a complete one and conclude something false about the difference.

**Movements are computed between period averages**, never by chaining daily
movements across a boundary. Chaining would compound day-of-week effects into
the weekly series.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

__all__ = [
    "Frequency",
    "PeriodIndex",
    "aggregate_to_frequency",
    "period_key",
]

QUANT = Decimal("0.000001")


class Frequency(StrEnum):
    DAILY = "D"
    WEEKLY = "W"
    MONTHLY = "M"


@dataclass(frozen=True, slots=True)
class PeriodIndex:
    """One period's index value, and how completely it was observed."""

    frequency: Frequency
    period_start: date
    period_end: date
    label: str
    index_value: Decimal
    previous_index_value: Decimal | None
    days_observed: int
    days_in_period: int

    @property
    def is_complete(self) -> bool:
        """Whether every day in the period contributed an observation.

        Incomplete periods are published with this flag rather than suppressed:
        a reader comparing a part-month with a full one needs to know which is
        which, and hiding the figure entirely loses real information.
        """
        return self.days_observed >= self.days_in_period

    @property
    def coverage_pct(self) -> Decimal:
        if self.days_in_period == 0:
            return Decimal("0.0")
        return (
            Decimal(self.days_observed) / Decimal(self.days_in_period) * 100
        ).quantize(Decimal("0.1"))

    @property
    def movement(self) -> Decimal | None:
        """Change from the previous period, in index points.

        Between period *averages*. Chaining daily movements across a period
        boundary would compound day-of-week effects into the series.
        """
        if self.previous_index_value is None:
            return None
        return (self.index_value - self.previous_index_value).quantize(QUANT)

    @property
    def movement_pct(self) -> Decimal | None:
        if self.previous_index_value in (None, 0):
            return None
        previous = self.previous_index_value
        assert previous is not None
        return ((self.index_value - previous) / previous * 100).quantize(Decimal("0.001"))


def period_key(day: date, frequency: Frequency) -> tuple[date, date, str]:
    """The period a day belongs to: (start, end, label).

    Weeks are **ISO weeks**, Monday to Sunday. The ISO convention is used rather
    than a rolling seven days so that "week 37" means the same span to every
    consumer, including one joining this series to another.
    """
    if frequency is Frequency.DAILY:
        return day, day, day.isoformat()

    if frequency is Frequency.WEEKLY:
        start = day - timedelta(days=day.weekday())
        end = start + timedelta(days=6)
        iso_year, iso_week, _ = day.isocalendar()
        return start, end, f"{iso_year}-W{iso_week:02d}"

    start = day.replace(day=1)
    end = (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    ) - timedelta(days=1)
    return start, end, f"{day.year}-{day.month:02d}"


def aggregate_to_frequency(
    daily: Iterable[tuple[date, Decimal]], frequency: Frequency
) -> list[PeriodIndex]:
    """Collapse a daily index series to the requested frequency.

    The arithmetic mean of daily values within each period — see the module
    docstring on why an average rather than a period-end snapshot.
    """
    observations = sorted(daily)
    if not observations:
        return []

    buckets: dict[str, list[tuple[date, Decimal]]] = {}
    spans: dict[str, tuple[date, date]] = {}
    for day, value in observations:
        start, end, label = period_key(day, frequency)
        buckets.setdefault(label, []).append((day, value))
        spans[label] = (start, end)

    periods: list[PeriodIndex] = []
    previous: Decimal | None = None

    for label in sorted(buckets):
        start, end = spans[label]
        values = [value for _, value in buckets[label]]
        mean = (sum(values, Decimal(0)) / len(values)).quantize(QUANT)

        periods.append(
            PeriodIndex(
                frequency=frequency,
                period_start=start,
                period_end=end,
                label=label,
                index_value=mean,
                previous_index_value=previous,
                days_observed=len({day for day, _ in buckets[label]}),
                days_in_period=(end - start).days + 1,
            )
        )
        previous = mean

    return periods
