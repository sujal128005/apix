"""The CPI 2024 airfare item identity, and the weight we do not yet have.

Item 294 was read from MoSPI's own API. The *weight* was not, and these tests
exist to keep that distinction from eroding. An unsourced weight would look
exactly like a sourced one on the Methodology page, which is precisely why it
must be impossible to add without tripping something.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE = REPO_ROOT / "data" / "reference" / "cpi_airfare_item.json"


@pytest.fixture(scope="module")
def item() -> dict[str, object]:
    return json.loads(REFERENCE.read_text(encoding="utf-8"))


def test_the_reference_file_exists(item: dict[str, object]) -> None:
    assert REFERENCE.exists()


def test_the_item_identity_matches_what_the_api_returned(item: dict[str, object]) -> None:
    assert item["item_code"] == 294
    assert item["item_name"] == "Airfare"
    assert item["sub_class_code"] == 125
    assert item["class_code"] == 58
    assert item["group_code"] == 24
    assert item["division_code"] == 7
    assert item["base_year"] == "2024"


def test_the_item_weight_is_still_unknown(item: dict[str, object]) -> None:
    """UNKNOWN until two independent sources agree (Phase 1.5 rule).

    If this test fails because someone filled the weight in, that is fine - but
    they must also record where it came from, and this test must be updated to
    assert the value rather than its absence. Failing loudly is the point.
    """
    assert item["item_weight_combined"] is None, (
        "A weight has been recorded. Confirm it against Annexure 5.3 of the "
        "Expert Group Report AND a second official source, cite both, then "
        "update this test to assert the value."
    )


def test_the_sub_class_is_the_domestic_one(item: dict[str, object]) -> None:
    """MoSPI splits domestic from international air travel at sub-class level.

    APIx collects domestic routes only. Comparing our index against a series
    that blended international fares would be a silent scope mismatch - the kind
    that produces a plausible chart and a wrong conclusion.
    """
    assert item["sub_class_name"] == "Passenger transport by air, domestic"
    assert item["coicop_code"] == "07.3.3.1.2.01"


def test_the_comparison_sector_is_recorded(item: dict[str, object]) -> None:
    """Rural, Urban and Combined are published separately; we must name ours."""
    assert "Combined" in item["sectors_available"]  # type: ignore[operator]


def test_every_recorded_figure_carries_its_source(item: dict[str, object]) -> None:
    """No number without provenance, including the one we did get."""
    assert item["division_weight_source"], "the division weight must cite its source"
    assert item["verified_via"], "the item identity must record how it was verified"
    assert item["verified_on"], "the item identity must record when"


def test_the_division_weight_is_the_official_figure(item: dict[str, object]) -> None:
    """8.796 combined, from the MoSPI CPI 2024 FAQ. Not a stand-in for the item."""
    assert item["division_weight_combined"] == 8.796
    assert item["division_weight_rural"] == 8.644
    assert item["division_weight_urban"] == 8.985


def test_the_division_weight_is_not_reused_as_the_item_weight(
    item: dict[str, object],
) -> None:
    """Transport's 8.796 covers rail, bus, taxi, fuel and vehicles too.

    Using it as the airfare weight would overstate air travel by an order of
    magnitude. The two fields are deliberately separate and must stay so.
    """
    assert item["item_weight_combined"] != item["division_weight_combined"]
