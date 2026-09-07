"""Elementary index: Jevons **short** (chain-base).

MoSPI's Expert Group Report (Jan 2026) states that CPI 2024 moved from the
Jevons *long* index used in CPI 2012 to the **short** form:

    I_t = GM( p_t / p_{t-1} ) x I_{t-1}

APIx implements the same, because an index proposed as an input to CPI should
be computed the way CPI is computed. Phase 1 of this project specified the long
form; that was the 2012 method and it was wrong. See INDEX-METHODOLOGY.md v0.2.

Three consequences follow from "chained", and all three shape this module.

**Matched pairs are required.** ``p_t / p_{t-1}`` is only meaningful for the
same priced unit in both periods. For airfare that unit is a
(carrier, flight number, fare brand) triple - not "the cheapest fare today",
which would compare different products and book a product change as a price
change. Unmatched quotes are simply not part of the ratio.

**Continuity is structural.** A missing period does not lose a point, it breaks
a link. Hence ``CHAIN_GAP`` and the imputation rules in ``impute.py``.

**Logs, not products.** Thirty fares multiplied together overflow quickly, and
the log form makes the geometric mean's damping of the right tail legible to a
reviewer. Airfare distributions have a long right tail by construction.

**Decimal throughout, no floats.** ``Decimal`` provides ``ln()`` and ``exp()``,
so the whole computation stays in exact decimal arithmetic at 28 significant
digits. The obvious implementation converts to float for the logarithms and back
afterwards, and it would pass every test here - but an index whose values must
be reproducible bit-for-bit, and defensible to an auditor, should not route its
prices through binary floating point on the way to a published number. The
project's no-float rule covers this module for exactly that reason, and it is
not exempted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

__all__ = [
    "ElementaryResult",
    "MatchedPair",
    "OutlierVerdict",
    "jevons_short",
    "mad_screen",
]


@dataclass(frozen=True, slots=True)
class MatchedPair:
    """One priced unit observed in both the previous and current period."""

    key: str  # carrier|flight_no|fare_brand
    previous: Decimal
    current: Decimal

    @property
    def relative(self) -> Decimal:
        return self.current / self.previous

    @property
    def log_relative(self) -> Decimal:
        """ln(p_t) - ln(p_{t-1}), in exact decimal arithmetic."""
        return self.current.ln() - self.previous.ln()


@dataclass(frozen=True, slots=True)
class OutlierVerdict:
    """Why one pair was kept or rejected. Written to cleaning_event."""

    key: str
    kept: bool
    observed: Decimal
    threshold: Decimal | None
    rule_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class ElementaryResult:
    """A stratum index, plus everything needed to defend it."""

    index_value: Decimal | None
    previous_index: Decimal
    accepted: int
    rejected: int
    geometric_mean_relative: Decimal | None
    verdicts: tuple[OutlierVerdict, ...] = field(default_factory=tuple)
    insufficient: bool = False
    reason: str = ""


def mad_screen(
    pairs: list[MatchedPair],
    *,
    k: Decimal = Decimal("3.5"),
    winsorise_below_n: int = 5,
    percentiles: tuple[Decimal, Decimal] = (Decimal("5"), Decimal("95")),
) -> tuple[list[MatchedPair], list[OutlierVerdict]]:
    """Screen log price-relatives by median absolute deviation.

    MAD rather than a z-score or IQR: a z-score assumes normality that log fares
    only approximate, IQR needs a reasonable n, and MAD has a 50% breakdown
    point - which matters at the n of 3 to 15 typical of one route x bucket x
    day. Robustness beats efficiency when a single sold-out-cabin fare of
    fifty thousand rupees can sit in a stratum of five.

    Below ``winsorise_below_n`` observations, extremes are pulled in rather than
    discarded: with four points, throwing one away costs more than it removes.

    **This rule is ours, not MoSPI's.** The Expert Group Report prescribes no
    outlier treatment for airfare. Parameters live in methodology_version.params
    and are rendered on the Methodology page as an engineering choice.
    """
    if not pairs:
        return [], []

    logs = [p.log_relative for p in pairs]

    if len(pairs) < winsorise_below_n:
        low = _percentile(logs, percentiles[0])
        high = _percentile(logs, percentiles[1])
        kept: list[MatchedPair] = []
        verdicts: list[OutlierVerdict] = []
        for pair in pairs:
            value = pair.log_relative
            clamped = min(max(value, low), high)
            if clamped != value:
                verdicts.append(
                    OutlierVerdict(
                        key=pair.key,
                        kept=True,
                        observed=value,
                        threshold=clamped,
                        rule_id="OUTLIER_WINSORISE_P5_P95",
                        reason=(
                            f"n={len(pairs)} is below the winsorisation threshold; "
                            f"log-relative pulled from {value:.6f} to {clamped:.6f} "
                            "rather than discarded"
                        ),
                    )
                )
                kept.append(
                    MatchedPair(
                        key=pair.key,
                        previous=pair.previous,
                        current=pair.previous * clamped.exp(),
                    )
                )
            else:
                kept.append(pair)
        return kept, verdicts

    median = _median(logs)
    deviations = [abs(x - median) for x in logs]
    mad = _median(deviations)

    if mad == 0:
        # Every relative identical: nothing to screen, and dividing by zero
        # would reject the whole stratum for being too consistent.
        return list(pairs), []

    scale = Decimal("1.4826") * mad
    kept, verdicts = [], []
    for pair in pairs:
        score = abs(pair.log_relative - median) / scale
        if score > k:
            verdicts.append(
                OutlierVerdict(
                    key=pair.key,
                    kept=False,
                    observed=pair.relative,
                    threshold=k,
                    rule_id="OUTLIER_MAD_LOG_RELATIVE",
                    reason=(
                        f"modified z-score {score:.2f} exceeds k={k} against a "
                        f"stratum median log-relative of {median:.6f}"
                    ),
                )
            )
        else:
            kept.append(pair)
    return kept, verdicts


def jevons_short(
    pairs: list[MatchedPair],
    previous_index: Decimal,
    *,
    k: Decimal = Decimal("3.5"),
    min_quotes: int = 3,
    winsorise_below_n: int = 5,
) -> ElementaryResult:
    """Compute one stratum index by chaining onto its predecessor.

    Returns ``index_value=None`` with ``insufficient=True`` when the stratum
    cannot be computed. That is not zero and must never be treated as zero: a
    stratum with no observations has an unknown price, not a free one.
    """
    if not pairs:
        return ElementaryResult(
            index_value=None,
            previous_index=previous_index,
            accepted=0,
            rejected=0,
            geometric_mean_relative=None,
            insufficient=True,
            reason="no matched pairs: nothing to chain from",
        )

    for pair in pairs:
        if pair.previous <= 0 or pair.current <= 0:
            raise ValueError(
                f"non-positive price in pair {pair.key!r}: "
                f"{pair.previous} -> {pair.current}. A zero or negative fare is a "
                "data error and must be rejected at ingestion, not averaged."
            )

    kept, verdicts = mad_screen(pairs, k=k, winsorise_below_n=winsorise_below_n)
    rejected = len(pairs) - len(kept)

    if len(kept) < min_quotes:
        return ElementaryResult(
            index_value=None,
            previous_index=previous_index,
            accepted=len(kept),
            rejected=rejected,
            geometric_mean_relative=None,
            verdicts=tuple(verdicts),
            insufficient=True,
            reason=(
                f"{len(kept)} accepted pair(s) is below the minimum of {min_quotes}; "
                "stratum reported as INSUFFICIENT rather than computed from too little"
            ),
        )

    # Geometric mean in log space, in Decimal. Sorted for deterministic
    # summation order - exact arithmetic still benefits from a fixed order once
    # results are quantised, and it costs nothing to guarantee.
    mean_log = sum(sorted(p.log_relative for p in kept), Decimal(0)) / len(kept)
    gm = mean_log.exp()

    return ElementaryResult(
        index_value=(previous_index * gm).quantize(Decimal("0.000001")),
        previous_index=previous_index,
        accepted=len(kept),
        rejected=rejected,
        geometric_mean_relative=gm.quantize(Decimal("0.000001")),
        verdicts=tuple(verdicts),
    )


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _percentile(values: list[Decimal], percentile: Decimal) -> Decimal:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (percentile / 100) * (len(ordered) - 1)
    lower = int(position // 1)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight
