"""How much does airfare move CPI, and what if it moved differently?

PS 26056 asks for augmentation of the Consumer Price Index, which means this
question has to be answerable: *an airfare movement of X translates to how many
basis points of headline inflation?*

The arithmetic is trivial. The honesty is not.

    contribution to headline (bps) = weight x movement% x 100

**The weight is the problem.** APIx does not know the CPI weight of airfare. The
Transport division weight is 8.796% (MoSPI CPI 2024 FAQ, Q39), but that division
covers rail, bus, taxi, auto-rickshaw, fuel and vehicle purchase as well as air
travel. Using 8.796 as the airfare weight would overstate air travel by roughly
an order of magnitude, and it would produce a confident, precise, wrong number.

So this module **refuses to publish a single figure**. It reports a range across
a stated span of plausible weights, and names the assumption every time. A
reader gets "between 0.4 and 1.8 basis points, under an assumed airfare weight
of 0.15% to 0.60% of the CPI basket" rather than "1.2 basis points".

That is less impressive and considerably more defensible. A statistician asked
"where did that weight come from?" can be answered honestly; the same question
against a single figure cannot.

**The weight range is an assumption, not a finding.** Its basis is recorded in
``WEIGHT_ASSUMPTION`` and rendered wherever a contribution appears. When
Annexure 5.3 of the Expert Group Report yields the actual item weight, the range
collapses to a point and this module reports that instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

__all__ = [
    "TRANSPORT_DIVISION_WEIGHT",
    "WEIGHT_ASSUMPTION",
    "ContributionEstimate",
    "ScenarioInput",
    "ScenarioResult",
    "estimate_contribution",
    "simulate_scenario",
]

#: Combined Transport division weight, CPI 2024. MoSPI CPI 2024 FAQ, Q39.
#: Covers rail, bus, taxi, auto-rickshaw, fuel and vehicles as well as air.
TRANSPORT_DIVISION_WEIGHT = Decimal("8.796")

#: Plausible span for airfare's own weight within the CPI basket, as a
#: percentage. Not a measurement: a bracket wide enough to be honest about
#: ignorance and narrow enough to be useful.
#:
#: The lower bound reflects that air travel is a small share of Indian household
#: transport spending, which is dominated by bus, rail and two-wheeler fuel. The
#: upper bound allows for air travel being a larger share of urban and higher-
#: income expenditure, which CPI weights by expenditure rather than by
#: passengers.
MIN_AIRFARE_WEIGHT = Decimal("0.15")
MAX_AIRFARE_WEIGHT = Decimal("0.60")

WEIGHT_ASSUMPTION = (
    "The CPI weight of airfare is not known to this project. Contributions are "
    f"reported as a range across an assumed weight of {MIN_AIRFARE_WEIGHT}% to "
    f"{MAX_AIRFARE_WEIGHT}% of the CPI basket. This is an assumption, not a "
    "measurement. The Transport division weight of "
    f"{TRANSPORT_DIVISION_WEIGHT}% is not a substitute: it covers rail, bus, "
    "taxi, fuel and vehicle purchase as well as air travel, and using it would "
    "overstate air travel by roughly an order of magnitude. When Annexure 5.3 "
    "of the Expert Group Report yields the item weight, this range becomes a "
    "point estimate."
)


@dataclass(frozen=True, slots=True)
class ContributionEstimate:
    """Airfare's contribution to inflation, as a range."""

    airfare_movement_pct: Decimal
    min_bps: Decimal
    max_bps: Decimal
    min_weight_pct: Decimal
    max_weight_pct: Decimal
    transport_division_bps: Decimal
    assumption: str = WEIGHT_ASSUMPTION

    @property
    def is_material(self) -> bool:
        """Whether this could plausibly round to a visible 0.1pp of headline CPI.

        Uses the *upper* bound: a contribution that might matter should be
        flagged as such, and a reader told it is immaterial deserves that to be
        true under every assumption in the range, not just the convenient one.
        """
        return self.max_bps >= Decimal("10")

    def describe(self) -> str:
        return (
            f"An airfare movement of {self.airfare_movement_pct:+.2f}% contributes "
            f"between {self.min_bps:+.2f} and {self.max_bps:+.2f} basis points to "
            f"headline CPI, under an assumed airfare weight of "
            f"{self.min_weight_pct}% to {self.max_weight_pct}%."
        )


def estimate_contribution(
    airfare_movement_pct: Decimal,
    *,
    min_weight_pct: Decimal = MIN_AIRFARE_WEIGHT,
    max_weight_pct: Decimal = MAX_AIRFARE_WEIGHT,
) -> ContributionEstimate:
    """Contribution of an airfare movement to headline CPI, in basis points.

    Returns a range because the weight is unknown. A single figure here would be
    precise and unfounded, and precision is exactly what makes an unfounded
    number persuasive.
    """
    if min_weight_pct > max_weight_pct:
        raise ValueError("min_weight_pct exceeds max_weight_pct")
    if min_weight_pct < 0:
        raise ValueError("a weight cannot be negative")

    # weight% x movement% gives a percentage-point change; x100 for basis points.
    low = (min_weight_pct / 100 * airfare_movement_pct * 100).quantize(Decimal("0.01"))
    high = (max_weight_pct / 100 * airfare_movement_pct * 100).quantize(Decimal("0.01"))

    # Reported for context only. Airfare is a fraction of this division, so this
    # is an upper bound on the divisional effect, not an estimate of it.
    division = (
        TRANSPORT_DIVISION_WEIGHT / 100 * airfare_movement_pct * 100
    ).quantize(Decimal("0.01"))

    return ContributionEstimate(
        airfare_movement_pct=airfare_movement_pct,
        min_bps=min(low, high),
        max_bps=max(low, high),
        min_weight_pct=min_weight_pct,
        max_weight_pct=max_weight_pct,
        transport_division_bps=division,
    )


# --------------------------------------------------------------------------
# Scenario simulation
# --------------------------------------------------------------------------

#: Share of an Indian domestic airfare attributable to fuel. Aviation turbine
#: fuel is commonly cited at 30-40% of operating cost for Indian carriers; 35%
#: is the midpoint. **An assumption**, and the single most consequential one in
#: a fuel scenario - a reader should be able to change it and see the effect.
DEFAULT_FUEL_SHARE = Decimal("0.35")

#: How much of a fuel cost change carriers pass to fares. Full pass-through is
#: unrealistic in a competitive market with hedging and lagged repricing.
DEFAULT_PASS_THROUGH = Decimal("0.70")

#: Fare response to a demand change. Positive: demand up, fares up. Airline
#: revenue management makes this steep relative to most consumer goods.
DEFAULT_DEMAND_ELASTICITY = Decimal("0.45")


@dataclass(frozen=True, slots=True)
class ScenarioInput:
    """A hypothetical shock. Every parameter is visible and adjustable."""

    fuel_change_pct: Decimal = Decimal("0")
    demand_change_pct: Decimal = Decimal("0")
    direct_fare_shock_pct: Decimal = Decimal("0")
    fuel_share: Decimal = DEFAULT_FUEL_SHARE
    pass_through: Decimal = DEFAULT_PASS_THROUGH
    demand_elasticity: Decimal = DEFAULT_DEMAND_ELASTICITY


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    """What a scenario implies, with its workings exposed."""

    inputs: ScenarioInput
    fare_change_from_fuel_pct: Decimal
    fare_change_from_demand_pct: Decimal
    direct_fare_shock_pct: Decimal
    total_fare_change_pct: Decimal
    contribution: ContributionEstimate
    caveats: tuple[str, ...]


def simulate_scenario(scenario: ScenarioInput) -> ScenarioResult:
    """Translate a fuel, demand or fare shock into an estimated CPI contribution.

    A deliberately simple, transparent model: three additive channels, each with
    a visible coefficient. It is not an econometric forecast and does not pretend
    to be. Its value is that a reader can see exactly which assumption produced
    which number, and change it.

    The caveats are returned with the result rather than printed somewhere near
    it, so they cannot be separated from the figure they qualify.
    """
    from_fuel = (
        scenario.fuel_change_pct * scenario.fuel_share * scenario.pass_through
    ).quantize(Decimal("0.001"))
    from_demand = (
        scenario.demand_change_pct * scenario.demand_elasticity
    ).quantize(Decimal("0.001"))
    total = (from_fuel + from_demand + scenario.direct_fare_shock_pct).quantize(
        Decimal("0.001")
    )

    caveats = [
        WEIGHT_ASSUMPTION,
        (
            f"Fuel is assumed to be {scenario.fuel_share * 100:.0f}% of fare cost with "
            f"{scenario.pass_through * 100:.0f}% pass-through to fares. Both are "
            "assumptions; aviation turbine fuel is commonly cited at 30-40% of "
            "Indian carriers' operating cost, and pass-through varies with hedging "
            "and competitive conditions."
        ),
        (
            f"A demand change is assumed to move fares with elasticity "
            f"{scenario.demand_elasticity}. Airline revenue management makes this "
            "steep relative to most consumer goods, and it is not constant across "
            "routes or seasons."
        ),
        (
            "Channels are additive and contemporaneous. In practice fuel changes "
            "reach fares with a lag, and a demand shock and a fuel shock arriving "
            "together would not simply sum."
        ),
        (
            "This is a transparent arithmetic model, not an econometric forecast. "
            "It shows what follows from the stated assumptions and nothing more."
        ),
    ]

    return ScenarioResult(
        inputs=scenario,
        fare_change_from_fuel_pct=from_fuel,
        fare_change_from_demand_pct=from_demand,
        direct_fare_shock_pct=scenario.direct_fare_shock_pct,
        total_fare_change_pct=total,
        contribution=estimate_contribution(total),
        caveats=tuple(caveats),
    )
