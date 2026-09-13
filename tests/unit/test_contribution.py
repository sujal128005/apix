"""CPI contribution and scenario simulation.

The arithmetic here is trivial. Everything worth testing is about what the
module refuses to claim.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from pipeline.contribution import (
    MAX_AIRFARE_WEIGHT,
    MIN_AIRFARE_WEIGHT,
    TRANSPORT_DIVISION_WEIGHT,
    ScenarioInput,
    estimate_contribution,
    simulate_scenario,
)

# -- the refusal to give a point estimate ----------------------------------


def test_a_contribution_is_a_range_not_a_figure() -> None:
    """APIx does not know the CPI weight of airfare.

    A single number would be precise and unfounded, and precision is exactly
    what makes an unfounded number persuasive.
    """
    estimate = estimate_contribution(Decimal("10"))
    assert estimate.min_bps < estimate.max_bps
    assert estimate.min_weight_pct == MIN_AIRFARE_WEIGHT
    assert estimate.max_weight_pct == MAX_AIRFARE_WEIGHT


def test_the_transport_division_weight_is_never_used_as_the_airfare_weight() -> None:
    """8.796% covers rail, bus, taxi, fuel and vehicles as well as air travel.

    Using it as the airfare weight would overstate air travel by roughly an
    order of magnitude, and would produce a confident, precise, wrong number.
    """
    estimate = estimate_contribution(Decimal("10"))
    division_bps = TRANSPORT_DIVISION_WEIGHT / 100 * Decimal("10") * 100

    assert estimate.max_bps < division_bps / 10, "airfare is a fraction of the division"
    assert estimate.transport_division_bps == division_bps.quantize(Decimal("0.01"))


def test_the_assumption_travels_with_every_estimate() -> None:
    """A range whose basis is elsewhere is a range nobody can evaluate."""
    assumption = estimate_contribution(Decimal("5")).assumption
    assert "not known to this project" in assumption
    assert "assumption, not a measurement" in assumption
    assert "8.796" in assumption
    assert "Annexure 5.3" in assumption


def test_the_summary_states_the_assumed_weight() -> None:
    summary = estimate_contribution(Decimal("2.39")).describe()
    assert "under an assumed airfare weight" in summary
    assert "0.15" in summary and "0.60" in summary


# -- the arithmetic --------------------------------------------------------


def test_contribution_scales_with_the_movement() -> None:
    small = estimate_contribution(Decimal("1"))
    large = estimate_contribution(Decimal("10"))
    assert large.max_bps == small.max_bps * 10


def test_a_fall_contributes_negatively() -> None:
    estimate = estimate_contribution(Decimal("-5"))
    assert estimate.min_bps < 0 and estimate.max_bps < 0
    assert estimate.min_bps <= estimate.max_bps, "ordering holds for negatives too"


def test_no_movement_contributes_nothing() -> None:
    estimate = estimate_contribution(Decimal("0"))
    assert estimate.min_bps == estimate.max_bps == Decimal("0.00")


def test_materiality_is_judged_on_the_upper_bound() -> None:
    """A reader told a contribution is immaterial deserves that to be true under
    every assumption in the range, not just the convenient one."""
    assert estimate_contribution(Decimal("0.5")).is_material is False
    assert estimate_contribution(Decimal("30")).is_material is True


def test_an_inverted_weight_range_is_refused() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        estimate_contribution(
            Decimal("5"), min_weight_pct=Decimal("1"), max_weight_pct=Decimal("0.1")
        )


# -- scenarios -------------------------------------------------------------


def test_a_fuel_shock_reaches_fares_through_share_and_pass_through() -> None:
    """20% fuel rise x 35% of cost x 70% pass-through = 4.9% on fares."""
    result = simulate_scenario(ScenarioInput(fuel_change_pct=Decimal("20")))
    assert result.fare_change_from_fuel_pct == Decimal("4.900")
    assert result.total_fare_change_pct == Decimal("4.900")


def test_channels_are_additive_and_separable() -> None:
    """A reader must be able to see which channel produced which part."""
    result = simulate_scenario(
        ScenarioInput(
            fuel_change_pct=Decimal("20"),
            demand_change_pct=Decimal("5"),
            direct_fare_shock_pct=Decimal("2"),
        )
    )
    assert result.fare_change_from_fuel_pct == Decimal("4.900")
    assert result.fare_change_from_demand_pct == Decimal("2.250")
    assert result.direct_fare_shock_pct == Decimal("2")
    assert result.total_fare_change_pct == Decimal("9.150")


def test_every_coefficient_is_adjustable() -> None:
    """The assumptions are the model. Hiding them would make it unfalsifiable."""
    conservative = simulate_scenario(
        ScenarioInput(
            fuel_change_pct=Decimal("20"),
            fuel_share=Decimal("0.30"),
            pass_through=Decimal("0.50"),
        )
    )
    assert conservative.fare_change_from_fuel_pct == Decimal("3.000")


def test_an_empty_scenario_changes_nothing() -> None:
    result = simulate_scenario(ScenarioInput())
    assert result.total_fare_change_pct == Decimal("0.000")
    assert result.contribution.min_bps == Decimal("0.00")


def test_caveats_are_returned_with_the_result() -> None:
    """Not printed near it. A caveat that can be separated from its figure will
    be."""
    result = simulate_scenario(ScenarioInput(fuel_change_pct=Decimal("20")))
    joined = " ".join(result.caveats)

    assert len(result.caveats) >= 4
    assert "not known to this project" in joined, "the weight assumption"
    assert "pass-through" in joined
    assert "elasticity" in joined
    assert "not an econometric forecast" in joined
    assert "lag" in joined, "additive channels are an approximation"


def test_a_negative_fuel_shock_lowers_fares() -> None:
    result = simulate_scenario(ScenarioInput(fuel_change_pct=Decimal("-20")))
    assert result.fare_change_from_fuel_pct == Decimal("-4.900")
    assert result.contribution.max_bps < 0
