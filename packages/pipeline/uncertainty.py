"""How precise is the index?

An official statistic published without a stated precision invites a question
with no answer. If APIx reports a 0.4% daily movement, a reader is entitled to
know whether that is a signal or sampling noise.

The elementary index is a geometric mean of price relatives, so its logarithm is
an arithmetic mean of log relatives, and the standard error of a mean is
available directly:

    se(ln I) = s / sqrt(n)

where ``s`` is the sample standard deviation of the log relatives in the
stratum. Converting back to index points gives an approximate standard error on
the index itself, and the usual multiplier gives a confidence interval.

**What this measures and what it does not.** It is a *sampling* error: how much
the index would move if a different set of flights had been observed within the
same stratum. It says nothing about whether the basket is the right basket, the
weights are the right weights, or the collection is representative. Those are
larger sources of error here than sampling is, and no interval computed from
observed prices can capture them.

Stating that plainly matters more than the arithmetic. A confidence interval
presented as though it bounded total error would overstate what is known.

**Small strata.** With six observations per stratum, an interval is wide and the
normal approximation is doing work it is not really entitled to. A t-multiplier
is used below eight observations, which is the conventional remedy and still an
approximation.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from index_engine.jevons import MatchedPair

__all__ = [
    "StratumUncertainty",
    "aggregate_standard_error",
    "stratum_uncertainty",
]

#: Two-sided 95% multipliers by degrees of freedom. Below eight observations a
#: normal multiplier understates the interval; these are Student's t. Above it,
#: the difference stops mattering at the precision this index is published to.
_T_95: dict[int, Decimal] = {
    1: Decimal("12.706"), 2: Decimal("4.303"), 3: Decimal("3.182"),
    4: Decimal("2.776"), 5: Decimal("2.571"), 6: Decimal("2.447"),
    7: Decimal("2.365"),
}
_NORMAL_95 = Decimal("1.96")


@dataclass(frozen=True, slots=True)
class StratumUncertainty:
    """Sampling uncertainty for one elementary aggregate."""

    observations: int
    index_value: Decimal
    standard_error: Decimal | None
    lower_95: Decimal | None
    upper_95: Decimal | None
    note: str = ""

    @property
    def is_estimable(self) -> bool:
        return self.standard_error is not None

    @property
    def relative_standard_error_pct(self) -> Decimal | None:
        """Standard error as a percentage of the index. The usual quality cue.

        Statistical offices commonly suppress or annotate a figure whose
        relative standard error exceeds a threshold. That threshold is a
        publication policy decision, not one this module should make.
        """
        if self.standard_error is None or self.index_value == 0:
            return None
        return (self.standard_error / self.index_value * 100).quantize(Decimal("0.001"))


def _multiplier(n: int) -> Decimal:
    return _T_95.get(n - 1, _NORMAL_95)


def stratum_uncertainty(
    pairs: list[MatchedPair], index_value: Decimal
) -> StratumUncertainty:
    """Sampling standard error and a 95% interval for one stratum.

    Returns an unestimable result rather than a zero when there are fewer than
    two observations. A single observation has no sampling variance to report,
    and printing 0.000 would read as perfect precision rather than as no
    information.
    """
    n = len(pairs)
    if n < 2:
        return StratumUncertainty(
            observations=n,
            index_value=index_value,
            standard_error=None,
            lower_95=None,
            upper_95=None,
            note=(
                "fewer than two matched observations: sampling variance is not "
                "estimable, and is reported as unknown rather than as zero"
            ),
        )

    logs = [p.log_relative for p in pairs]
    mean = sum(logs, Decimal(0)) / n
    variance = sum(((x - mean) ** 2 for x in logs), Decimal(0)) / (n - 1)
    se_log = (variance / n).sqrt()

    # Delta-method transfer from log scale to index points. Exact for small
    # se_log, which is the case here; the approximation degrades only when the
    # interval is already too wide to publish.
    se_index = (index_value * se_log).quantize(Decimal("0.000001"))
    half_width = _multiplier(n) * se_index

    return StratumUncertainty(
        observations=n,
        index_value=index_value,
        standard_error=se_index,
        lower_95=(index_value - half_width).quantize(Decimal("0.000001")),
        upper_95=(index_value + half_width).quantize(Decimal("0.000001")),
        note=(
            f"sampling error only, from {n} matched observations. Excludes basket, "
            "weighting and coverage error, which are larger sources here."
        ),
    )


def aggregate_standard_error(
    components: list[tuple[Decimal, Decimal | None]],
) -> Decimal | None:
    """Standard error of a weighted arithmetic mean of independent components.

    ``components`` is a list of ``(weight, standard_error)``. Weights need not
    sum to one; they are normalised here.

        se(sum w_i x_i) = sqrt( sum w_i^2 se_i^2 )   for independent x_i

    **Independence is assumed and is not true.** Fares on Delhi-Mumbai and
    Delhi-Bengaluru move together: shared carriers, shared fuel costs, shared
    demand shocks. Positive correlation means this understates the true
    standard error. Reported anyway, because a stated lower bound with its
    assumption named is more useful than no figure, but it must be labelled as
    a lower bound rather than an estimate.
    """
    usable = [(w, se) for w, se in components if se is not None]
    if not usable:
        return None

    total_weight = sum((w for w, _ in usable), Decimal(0))
    if total_weight == 0:
        return None

    variance = sum(
        (((w / total_weight) ** 2) * (se**2) for w, se in usable), Decimal(0)
    )
    return variance.sqrt().quantize(Decimal("0.000001"))
