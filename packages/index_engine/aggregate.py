"""Higher-level aggregation: Young / Modified Laspeyres, weighted **arithmetic**.

Geometric below, arithmetic above. That asymmetry is deliberate CPI structure,
not an inconsistency to tidy up: the Expert Group Report specifies the weighted
arithmetic mean of lower-level indices, and separately records that CPI 2024
moved the house-rent index *from* weighted geometric *to* weighted arithmetic
specifically to align it with every other item.

    Combined = ( w1*I1 + w2*I2 + ... ) / ( w1 + w2 + ... )

**Say "Young / Modified Laspeyres", not "Laspeyres".** A true Laspeyres takes
weights and base prices from the same period. Here the weights come from traffic
evidence for one period and the base prices from our own base window - different
periods, which is exactly why the report calls it a Young index. A price
statistician will catch the difference.

Two properties this module guarantees, both asserted rather than assumed:

**Contributions sum to the movement.** Because aggregation is arithmetic and
weights are not renormalised, ``sum(contributions) == I_t - I_{t-1}`` exactly.
The engine asserts it; if it ever fails, the index is wrong and should say so
loudly rather than round the discrepancy away.

**No renormalisation.** A route missing today is imputed, not dropped (ADR-011).
Dropping and rescaling the remaining weights is what CPI 2012 did, and the
report records that it caused undue volatility - which is why CPI 2024 stopped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

__all__ = ["AggregateResult", "Component", "Contribution", "weighted_arithmetic"]

QUANT = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class Component:
    """One lower-level index entering an aggregate, with its weight."""

    ref: str
    index_value: Decimal
    weight: Decimal
    previous_index: Decimal | None = None
    imputed: bool = False


@dataclass(frozen=True, slots=True)
class Contribution:
    """How much one component moved the aggregate, in index points."""

    ref: str
    contribution: Decimal


@dataclass(frozen=True, slots=True)
class AggregateResult:
    index_value: Decimal
    previous_index: Decimal | None
    weight_total: Decimal
    components: int
    imputed_components: int
    contributions: tuple[Contribution, ...] = field(default_factory=tuple)

    @property
    def movement(self) -> Decimal | None:
        if self.previous_index is None:
            return None
        return (self.index_value - self.previous_index).quantize(QUANT)


def weighted_arithmetic(components: list[Component]) -> AggregateResult:
    """Aggregate lower-level indices into one, and decompose the movement.

    Raises on an empty component list rather than returning zero. An aggregate
    over nothing is undefined, and a zero would read as a total price collapse.
    """
    if not components:
        raise ValueError(
            "cannot aggregate an empty component list: the result would be "
            "undefined, and returning zero would read as a 100% price collapse"
        )

    for component in components:
        if component.weight <= 0:
            raise ValueError(
                f"component {component.ref!r} has weight {component.weight}; "
                "weights must be strictly positive"
            )
        if component.index_value <= 0:
            raise ValueError(
                f"component {component.ref!r} has index {component.index_value}; "
                "an index value of zero or less is a computation error"
            )

    # Sorted by ref for deterministic summation order - see jevons.py on why
    # "reproducible" has to mean bit-identical.
    ordered = sorted(components, key=lambda c: c.ref)

    weight_total = sum((c.weight for c in ordered), Decimal(0))
    weighted = sum((c.weight * c.index_value for c in ordered), Decimal(0))
    index_value = (weighted / weight_total).quantize(QUANT)

    have_previous = [c for c in ordered if c.previous_index is not None]
    previous_index: Decimal | None = None
    contributions: list[Contribution] = []

    if len(have_previous) == len(ordered):
        previous_weighted = sum(
            (c.weight * (c.previous_index or Decimal(0)) for c in ordered), Decimal(0)
        )
        previous_index = (previous_weighted / weight_total).quantize(QUANT)
        for component in ordered:
            delta = component.index_value - (component.previous_index or Decimal(0))
            contributions.append(
                Contribution(
                    ref=component.ref,
                    contribution=(component.weight * delta / weight_total).quantize(QUANT),
                )
            )

    return AggregateResult(
        index_value=index_value,
        previous_index=previous_index,
        weight_total=weight_total.quantize(QUANT),
        components=len(ordered),
        imputed_components=sum(1 for c in ordered if c.imputed),
        contributions=tuple(contributions),
    )
