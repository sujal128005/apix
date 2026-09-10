"""Validation of the index against itself and against official statistics.

PS 26056 asks for "at least 30 days of back-tested results against publicly
available DGCA monthly average-fare data". Phase 1 research established that no
such public series demonstrably exists: DGCA's Tariff Monitoring Unit covers 78
routes monthly, but its output surfaces through parliamentary replies rather
than as a downloadable time series. Inventing one is not an option, so ADR-015
replaced the single assumed comparison with three tiers of decreasing certainty
and increasing honesty about their limits.

    Tier 1  Internal reproducibility.  Recompute a window from stored
            observations and prove the result is identical. Always available,
            and the only tier that tests the engine rather than the world.

    Tier 2  Official CPI benchmark.  Compare APIx *movements* against the
            official CPI 2024 domestic-airfare index (item 294, COICOP
            07.3.3.1.2.01), fetched from MoSPI's own API.

    Tier 3  Public DGCA figures.  Individually cited, never interpolated.
            Currently empty, which is itself a finding.

**Levels are not comparable.** CPI 2024 is based at 2024 = 100 with prices
referenced to calendar 2024; APIx is based on its own first collection days.
Comparing levels would produce a large, meaningless error. Only month-on-month
movements are comparable, and every metric here is computed on movements.

**Too little overlap produces no metrics.** An MAE over one or two aligned
months is a number with no statistical content, and printing one anyway is how
a validation section becomes decoration. Below the minimum the engine reports
the shortfall and declines to compute.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

__all__ = [
    "AlignedMonth",
    "BacktestReport",
    "MonthlyPoint",
    "ReplayResult",
    "TierTwoResult",
    "compare_movements",
    "monthly_average",
]

MIN_ALIGNED_MONTHS = 3
QUANT = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class MonthlyPoint:
    year: int
    month: int
    value: Decimal

    @property
    def key(self) -> tuple[int, int]:
        return self.year, self.month

    @property
    def label(self) -> str:
        return f"{self.year}-{self.month:02d}"


@dataclass(frozen=True, slots=True)
class AlignedMonth:
    """One month present in both series, with each side's movement."""

    label: str
    apix_movement_pct: Decimal
    benchmark_movement_pct: Decimal

    @property
    def error(self) -> Decimal:
        return self.apix_movement_pct - self.benchmark_movement_pct

    @property
    def same_direction(self) -> bool:
        """Whether both series moved the same way, treating flat as its own case."""
        if self.apix_movement_pct == 0 or self.benchmark_movement_pct == 0:
            return self.apix_movement_pct == self.benchmark_movement_pct
        return (self.apix_movement_pct > 0) == (self.benchmark_movement_pct > 0)


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """Tier 1: does the engine give the same answer twice?"""

    days_replayed: int
    values_compared: int
    mismatches: tuple[str, ...] = ()

    @property
    def reproducible(self) -> bool:
        return not self.mismatches and self.values_compared > 0


@dataclass(frozen=True, slots=True)
class TierTwoResult:
    """Tier 2: APIx movements against the official CPI airfare index."""

    apix_months: int
    benchmark_months: int
    aligned: tuple[AlignedMonth, ...]
    sufficient: bool
    limitation: str
    mae: Decimal | None = None
    rmse: Decimal | None = None
    directional_agreement: Decimal | None = None


@dataclass(slots=True)
class BacktestReport:
    window_start: date | None
    window_end: date | None
    tier1: ReplayResult | None = None
    tier2: TierTwoResult | None = None
    tier3_points: int = 0
    tier3_note: str = ""
    limitations: list[str] = field(default_factory=list)


def monthly_average(daily: list[tuple[date, Decimal]]) -> list[MonthlyPoint]:
    """Collapse a daily index to monthly averages.

    The arithmetic mean of daily values, because CPI is a monthly *average*
    concept and that is the comparable quantity. The chained end-of-month value
    answers a different question ("where is the index now") and using it here
    would compare an average with a snapshot.
    """
    buckets: dict[tuple[int, int], list[Decimal]] = {}
    for day, value in daily:
        buckets.setdefault((day.year, day.month), []).append(value)

    return [
        MonthlyPoint(
            year=year,
            month=month,
            value=(sum(values, Decimal(0)) / len(values)).quantize(QUANT),
        )
        for (year, month), values in sorted(buckets.items())
    ]


def _movements(points: list[MonthlyPoint]) -> dict[tuple[int, int], Decimal]:
    """Month-on-month percentage change, keyed by month."""
    movements: dict[tuple[int, int], Decimal] = {}
    for previous, current in itertools.pairwise(points):
        if previous.value == 0:
            continue
        change = (current.value - previous.value) / previous.value * 100
        movements[current.key] = change.quantize(QUANT)
    return movements


def compare_movements(
    apix: list[MonthlyPoint],
    benchmark: list[MonthlyPoint],
    *,
    min_months: int = MIN_ALIGNED_MONTHS,
) -> TierTwoResult:
    """Align two monthly series and compare their movements.

    Refuses to produce metrics on too few aligned months. An MAE over one point
    is arithmetic, not evidence, and a validation section that always prints a
    number teaches a reader to stop reading it.
    """
    apix_moves = _movements(apix)
    bench_moves = _movements(benchmark)
    shared = sorted(set(apix_moves) & set(bench_moves))

    aligned = tuple(
        AlignedMonth(
            label=f"{year}-{month:02d}",
            apix_movement_pct=apix_moves[(year, month)],
            benchmark_movement_pct=bench_moves[(year, month)],
        )
        for year, month in shared
    )

    if len(aligned) < min_months:
        if not aligned:
            limitation = (
                f"No overlapping months. APIx covers "
                f"{apix[0].label if apix else 'nothing'} to "
                f"{apix[-1].label if apix else 'nothing'}; the benchmark covers "
                f"{benchmark[0].label if benchmark else 'nothing'} to "
                f"{benchmark[-1].label if benchmark else 'nothing'}. "
                "No comparison is possible and none is reported."
            )
        else:
            limitation = (
                f"Only {len(aligned)} aligned month(s); {min_months} are required "
                "before error metrics carry any statistical content. The aligned "
                "months are listed for inspection but no metrics are computed."
            )
        return TierTwoResult(
            apix_months=len(apix),
            benchmark_months=len(benchmark),
            aligned=aligned,
            sufficient=False,
            limitation=limitation,
        )

    # Decimal throughout. These errors are differences between index movements,
    # so they inherit the money path and must not detour through binary floating
    # point on the way to a published error metric.
    errors = [month.error for month in aligned]
    count = Decimal(len(aligned))
    mae = (sum((abs(e) for e in errors), Decimal(0)) / count).quantize(QUANT)
    mean_square = sum((e * e for e in errors), Decimal(0)) / count
    rmse = mean_square.sqrt().quantize(QUANT)
    agreement = (
        Decimal(sum(1 for month in aligned if month.same_direction)) / count * 100
    ).quantize(Decimal("0.01"))

    return TierTwoResult(
        apix_months=len(apix),
        benchmark_months=len(benchmark),
        aligned=aligned,
        sufficient=True,
        limitation=(
            "Movements only. CPI 2024 is based at 2024=100 with prices referenced "
            "to calendar 2024; APIx uses its own base period, so index levels are "
            "not comparable and no level comparison is reported."
        ),
        mae=mae,
        rmse=rmse,
        directional_agreement=agreement,
    )
