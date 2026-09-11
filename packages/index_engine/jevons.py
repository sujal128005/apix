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
    "MAX_PLAUSIBLE_RELATIVE",
    "MIN_PLAUSIBLE_RELATIVE",
    "ElementaryResult",
    "MatchedPair",
    "OutlierVerdict",
    "ScreenMode",
    "jevons_short",
    "mad_screen",
]


class ScreenMode:
    """What the screen does with a statistically extreme observation.

    ``REJECT`` was methodology 1.0.0. A sensitivity analysis then measured it
    erasing genuine price events: a tripled fare in a six-observation stratum was
    discarded and the index reported that nothing had happened. The screen could
    not tell a data error from a last-seat fare, because statistically they are
    the same thing - a value far from its neighbours.

    ``FLAG`` is methodology 1.1.0. Extreme observations stay in the index and are
    counted, so a reader can see when a movement was driven by one unusual fare.
    Only *impossible* values are removed, on plausibility grounds rather than on
    being surprising. That is what outlier screening is for in price statistics:
    catching a parse failure or a misplaced decimal, not smoothing volatility the
    index exists to observe.
    """

    REJECT = "reject"
    FLAG = "flag"


#: Bounds on a period-on-period fare relative. Outside these a value is not an
#: unusual price, it is a broken one - a decimal in the wrong place, a currency
#: mix-up, a parse that captured the wrong element. A fare that falls to a
#: hundredth or rises a hundredfold overnight is not a market event.
MIN_PLAUSIBLE_RELATIVE = Decimal("0.01")
MAX_PLAUSIBLE_RELATIVE = Decimal("100")


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
    """Why one pair was kept, flagged or removed. Written to cleaning_event."""

    key: str
    kept: bool
    observed: Decimal
    threshold: Decimal | None
    rule_id: str
    reason: str
    flagged: bool = False
    """True when the observation is statistically extreme but was *kept*.

    A flagged observation contributes to the index and is counted on the Data
    Quality page. Nothing is hidden: a reader can see how much of a movement
    came from unusual fares."""


@dataclass(frozen=True, slots=True)
class ElementaryResult:
    """A stratum index, plus everything needed to defend it."""

    index_value: Decimal | None
    previous_index: Decimal
    accepted: int
    rejected: int
    geometric_mean_relative: Decimal | None
    flagged: int = 0
    """Extreme observations kept in the index and counted (methodology 1.1.0)."""
    implausible: int = 0
    """Observations removed as impossible rather than merely unusual."""
    verdicts: tuple[OutlierVerdict, ...] = field(default_factory=tuple)
    insufficient: bool = False
    reason: str = ""


def mad_screen(
    pairs: list[MatchedPair],
    *,
    k: Decimal = Decimal("3.5"),
    winsorise_below_n: int = 5,
    percentiles: tuple[Decimal, Decimal] = (Decimal("5"), Decimal("95")),
    mode: str = ScreenMode.FLAG,
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

    # Plausibility first, and separately from the statistical screen. A relative
    # outside these bounds is not an unusual price but a broken one, and it is
    # removed in either mode. This is the only thing methodology 1.1.0 discards.
    plausible: list[MatchedPair] = []
    verdicts: list[OutlierVerdict] = []
    for pair in pairs:
        relative = pair.relative
        if not MIN_PLAUSIBLE_RELATIVE <= relative <= MAX_PLAUSIBLE_RELATIVE:
            verdicts.append(
                OutlierVerdict(
                    key=pair.key,
                    kept=False,
                    observed=relative,
                    threshold=MAX_PLAUSIBLE_RELATIVE,
                    rule_id="IMPLAUSIBLE_RELATIVE",
                    reason=(
                        f"period-on-period relative {relative} lies outside "
                        f"[{MIN_PLAUSIBLE_RELATIVE}, {MAX_PLAUSIBLE_RELATIVE}]; "
                        "this is a broken value, not an unusual price"
                    ),
                )
            )
        else:
            plausible.append(pair)

    if not plausible:
        return [], verdicts

    pairs = plausible
    logs = [p.log_relative for p in pairs]

    if len(pairs) < winsorise_below_n:
        low = _percentile(logs, percentiles[0])
        high = _percentile(logs, percentiles[1])
        kept: list[MatchedPair] = []
        for pair in pairs:
            value = pair.log_relative
            clamped = min(max(value, low), high)
            if clamped == value:
                kept.append(pair)
                continue

            if mode == ScreenMode.FLAG:
                # Kept at its observed value. With four observations an extreme
                # may simply be the market, and pulling it in would damp a real
                # event on the strength of a small sample.
                verdicts.append(
                    OutlierVerdict(
                        key=pair.key,
                        kept=True,
                        flagged=True,
                        observed=pair.relative,
                        threshold=None,
                        rule_id="EXTREME_SMALL_N_FLAGGED",
                        reason=(
                            f"n={len(pairs)}: relative {pair.relative} is extreme for "
                            "this stratum and is kept and counted, not adjusted"
                        ),
                    )
                )
                kept.append(pair)
            else:
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
        return kept, verdicts

    median = _median(logs)
    deviations = [abs(x - median) for x in logs]
    mad = _median(deviations)

    # When MAD degenerates, fall back to mean absolute deviation.
    #
    # A sensitivity analysis found this the hard way. In a stratum where most
    # flights move by an identical factor - which is common, because carriers
    # follow each other - the median absolute deviation is *exactly zero*. The
    # previous code returned every pair unscreened in that case, reasoning that
    # zero dispersion meant nothing to screen. That is backwards: it meant a
    # 4x outlier sat beside four identical relatives and survived at every
    # threshold, including k = 3.5. The screen silently stopped working in
    # precisely the case it was most needed.
    #
    # The remedy is Iglewicz and Hoaglin's: where MAD is zero, scale by the mean
    # absolute deviation instead (1.253314 x meanAD, the consistency constant
    # for the normal distribution, against 1.4826 for MAD). Chosen from the
    # robust-statistics literature rather than picked, which was the whole point
    # of running the sensitivity analysis.
    if mad == 0:
        mean_ad = sum(deviations, Decimal(0)) / len(deviations)
        if mean_ad == 0:
            # Every relative genuinely identical. Nothing to screen, and nothing
            # extreme to miss. Plausibility verdicts already collected are kept:
            # resetting them here would silently lose the record of a removed
            # broken value.
            return list(pairs), verdicts
        scale = Decimal("1.253314") * mean_ad
    else:
        scale = Decimal("1.4826") * mad
    # NB: `verdicts` already carries any plausibility removals. Re-initialising
    # it here was a bug - the record of a discarded broken value vanished.
    kept = []
    for pair in pairs:
        score = abs(pair.log_relative - median) / scale
        if score <= k:
            kept.append(pair)
            continue

        if mode == ScreenMode.FLAG:
            # Kept and counted. A fare far from its neighbours may be a last-seat
            # price rather than an error, and the two are statistically
            # indistinguishable - so the index observes it and the Data Quality
            # page reports that it did.
            kept.append(pair)
            verdicts.append(
                OutlierVerdict(
                    key=pair.key,
                    kept=True,
                    flagged=True,
                    observed=pair.relative,
                    threshold=k,
                    rule_id="EXTREME_MAD_FLAGGED",
                    reason=(
                        f"modified z-score {score:.2f} exceeds k={k}; kept in the "
                        "index and counted rather than discarded"
                    ),
                )
            )
        else:
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
    return kept, verdicts


def jevons_short(
    pairs: list[MatchedPair],
    previous_index: Decimal,
    *,
    k: Decimal = Decimal("3.5"),
    min_quotes: int = 3,
    winsorise_below_n: int = 5,
    mode: str = ScreenMode.FLAG,
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

    kept, verdicts = mad_screen(
        pairs, k=k, winsorise_below_n=winsorise_below_n, mode=mode
    )
    rejected = len(pairs) - len(kept)
    flagged = sum(1 for v in verdicts if v.flagged)
    implausible = sum(1 for v in verdicts if v.rule_id == "IMPLAUSIBLE_RELATIVE")

    if len(kept) < min_quotes:
        return ElementaryResult(
            index_value=None,
            previous_index=previous_index,
            accepted=len(kept),
            rejected=rejected,
            geometric_mean_relative=None,
            verdicts=tuple(verdicts),
            flagged=flagged,
            implausible=implausible,
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
        flagged=flagged,
        implausible=implausible,
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
