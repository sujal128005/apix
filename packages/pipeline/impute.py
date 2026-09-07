"""Missing strata: impute by comparable movement, carry until they return.

The Expert Group Report is unusually direct about this. CPI 2012 imputed a
missing price for one month only and, when an item was missing everywhere,
redistributed its weight across the rest. The report records that the
redistribution **caused undue volatility and hurt index stability**, which is
why CPI 2024 stopped doing it. CPI 2024 imputes every missing price, keeps
imputing until real prices reappear, and never redistributes weights.

APIx follows that exactly (ADR-011). Phase 1 of this project specified a two-day
carry-forward followed by dropping the route and renormalising the remaining
weights - both halves of which are the behaviour MoSPI abandoned.

The prescribed rule:

    imputed_p_t = p_{t-1} x GM( available p_t / p_{t-1} )

The missing stratum moves by the observed movement of comparable strata. Note
what this is *not*: it is not carrying the old price forward unchanged, which
would understate inflation in every month a stratum went missing, and it is not
zero, which would fabricate a total price collapse.

Two consequences worth stating plainly, because they are the honest cost of the
method:

**Imputation rate is a published metric.** A stratum imputed for weeks is a
weakness, and the Data Quality page shows it rather than burying it.

**Imputed strata are excluded from the headline above a threshold.** Reported
always, counted always, but not silently blended into a number presented as
observed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from schemas.enums import ImputationCode, MissingReason

__all__ = [
    "ImputationResult",
    "StratumState",
    "imputation_rate",
    "impute_missing",
]


@dataclass(frozen=True, slots=True)
class StratumState:
    """A stratum's index at the previous period, and whether it was real."""

    ref: str
    previous_index: Decimal
    was_imputed: bool = False
    consecutive_imputations: int = 0


@dataclass(frozen=True, slots=True)
class ImputationResult:
    """An imputed stratum index, with the evidence for it."""

    ref: str
    index_value: Decimal
    imputation_code: str
    missing_reason: str
    donor_count: int
    movement_applied: Decimal
    consecutive_imputations: int
    reason: str


def impute_missing(
    state: StratumState,
    observed_movements: list[Decimal],
    *,
    missing_reason: str = MissingReason.NO_FLIGHTS,
    max_consecutive: int = 30,
) -> ImputationResult | None:
    """Move a missing stratum by the geometric mean movement of its comparables.

    ``observed_movements`` are the period-on-period ratios of strata that *were*
    observed - typically the other lead-time buckets on the same route, falling
    back to other routes if none are available.

    Returns ``None`` when there is nothing to impute from. That is deliberate: an
    unobservable stratum with no comparable movement has an unknown value, and
    inventing one would be worse than reporting the gap.
    """
    if not observed_movements:
        return None

    if state.consecutive_imputations >= max_consecutive:
        # Past this point the "stratum" is not missing, it is gone. Continuing
        # to impute would manufacture a series for something that stopped
        # existing, which is a different claim from "we could not observe it".
        return None

    # Geometric mean of the donor movements, in exact decimal arithmetic.
    total_log = sum((m.ln() for m in sorted(observed_movements)), Decimal(0))
    movement = (total_log / len(observed_movements)).exp()

    consecutive = state.consecutive_imputations + 1
    return ImputationResult(
        ref=state.ref,
        index_value=(state.previous_index * movement).quantize(Decimal("0.000001")),
        imputation_code=ImputationCode.Y,
        missing_reason=missing_reason,
        donor_count=len(observed_movements),
        movement_applied=movement.quantize(Decimal("0.000001")),
        consecutive_imputations=consecutive,
        reason=(
            f"{missing_reason}: moved by the geometric mean movement of "
            f"{len(observed_movements)} comparable stratum/strata "
            f"({movement:.6f}); imputed for {consecutive} consecutive period(s)"
        ),
    )


def imputation_rate(total: int, imputed: int) -> Decimal:
    """Share of strata that were imputed rather than observed.

    Published on the Data Quality page. A rising rate is the first sign that a
    source has quietly stopped working, well before anyone notices the index
    looks odd.
    """
    if total <= 0:
        return Decimal("0.000")
    return (Decimal(imputed) / Decimal(total)).quantize(Decimal("0.001"))
