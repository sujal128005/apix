"""The airfare product specification.

A price index compares the price of the same thing over time. These tests are
about what "the same thing" means, which is the sampling decision an expert
reviewer examines first.
"""

from __future__ import annotations

from datetime import datetime, time

import pytest

from pipeline.specification import (
    Cabin,
    Changeability,
    DepartureBand,
    ProductSpecification,
    Refundability,
    RoutingType,
    TripType,
    departure_band_for,
    specification_from_quote,
)


def spec(**overrides: object) -> ProductSpecification:
    base: dict[str, object] = {
        "route_code": "DEL-BOM",
        "carrier": "6E",
        "cabin": Cabin.ECONOMY,
        "trip_type": TripType.ONE_WAY,
        "routing": RoutingType.DIRECT,
        "departure_band": DepartureBand.EARLY_MORNING,
        "fare_brand": "SAVER",
        "baggage_kg": 15,
        "refundability": Refundability.NON_REFUNDABLE,
        "changeability": Changeability.CHANGE_WITH_FEE,
    }
    base.update(overrides)
    return ProductSpecification(**base)  # type: ignore[arg-type]


# -- the failure this module exists to fix --------------------------------


def test_a_renumbered_flight_is_still_the_same_product() -> None:
    """The case that broke the old matching key.

    A schedule change renumbers 6E1234 to 6E5678. Cabin, baggage,
    refundability, routing and departure time are unchanged. Nothing about the
    product changed, so the index must still see a matched pair - the previous
    key saw a disappearance and an arrival, and recorded no price movement
    where there was one.
    """
    morning_a = spec(departure_band=departure_band_for(datetime(2026, 9, 15, 6, 15)))
    morning_b = spec(departure_band=departure_band_for(datetime(2026, 9, 15, 6, 40)))

    assert morning_a.match_key == morning_b.match_key
    assert morning_a.differs_from(morning_b) == ()


def test_flight_number_is_absent_from_the_match_key() -> None:
    """It is operational metadata, not a price-determining characteristic."""
    assert "flight" not in spec().match_key.lower()


# -- what must NOT be pooled ----------------------------------------------


def test_a_dawn_and_an_evening_departure_are_different_products() -> None:
    """Genuinely different products at genuinely different prices."""
    dawn = spec(departure_band=DepartureBand.EARLY_MORNING)
    evening = spec(departure_band=DepartureBand.NIGHT)

    assert dawn.match_key != evening.match_key
    assert dawn.differs_from(evening) == ("departure_band",)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("carrier", "SG"),
        ("cabin", Cabin.BUSINESS),
        ("fare_brand", "FLEXI"),
        ("baggage_kg", 25),
        ("refundability", Refundability.FULLY_REFUNDABLE),
        ("changeability", Changeability.FREE_CHANGES),
        ("routing", RoutingType.ONE_STOP),
        ("trip_type", TripType.RETURN),
    ],
)
def test_each_price_determining_characteristic_separates_products(
    field: str, value: object
) -> None:
    assert spec().match_key != spec(**{field: value}).match_key
    assert spec().differs_from(spec(**{field: value})) == (field,)


# -- departure bands -------------------------------------------------------


@pytest.mark.parametrize(
    ("clock", "expected"),
    [
        (time(0, 30), DepartureBand.EARLY_MORNING),
        (time(7, 59), DepartureBand.EARLY_MORNING),
        (time(8, 0), DepartureBand.MORNING),
        (time(11, 59), DepartureBand.MORNING),
        (time(12, 0), DepartureBand.MIDDAY),
        (time(16, 0), DepartureBand.EVENING),
        (time(20, 0), DepartureBand.NIGHT),
        (time(23, 59), DepartureBand.NIGHT),
    ],
)
def test_departure_bands_partition_the_day(clock: time, expected: DepartureBand) -> None:
    assert departure_band_for(clock) is expected


# -- completeness ----------------------------------------------------------


def test_a_specification_missing_a_characteristic_is_not_fully_specified() -> None:
    """An unknown characteristic might be the one that changed.

    Such a product can still be priced - the total is the total - but it cannot
    safely be matched across periods, and the pipeline needs to know that
    rather than pairing on incomplete information.
    """
    assert spec().is_fully_specified is True
    assert spec(baggage_kg=None).is_fully_specified is False
    assert spec(refundability=Refundability.UNKNOWN).is_fully_specified is False
    assert spec(fare_brand=None).is_fully_specified is False


def test_unknown_characteristics_are_not_guessed() -> None:
    """Inventing a baggage allowance would match products that are not the same,
    and would do it invisibly."""
    built = specification_from_quote(
        {"carrier": "6E", "stops": 0, "departure_at": "2026-09-15T06:15:00"},
        route_code="DEL-BOM",
    )
    assert built.baggage_kg is None
    assert built.refundability is Refundability.UNKNOWN
    assert built.changeability is Changeability.UNKNOWN
    assert built.is_fully_specified is False


def test_a_specification_is_built_from_a_quote_payload() -> None:
    built = specification_from_quote(
        {
            "carrier": "ai",
            "stops": 0,
            "departure_at": "2026-09-15T21:30:00",
            "fare_brand": "ECOVALUE",
            "baggage_kg": 25,
            "refundability": "partially_refundable",
            "changeability": "change_with_fee",
        },
        route_code="DEL-BOM",
    )
    assert built.carrier == "AI"
    assert built.departure_band is DepartureBand.NIGHT
    assert built.refundability is Refundability.PARTIALLY_REFUNDABLE
    assert built.is_fully_specified is True


# -- validation ------------------------------------------------------------


def test_a_malformed_carrier_is_refused() -> None:
    with pytest.raises(ValueError, match="2-character IATA"):
        spec(carrier="INDIGO")


def test_a_malformed_route_is_refused() -> None:
    with pytest.raises(ValueError, match="ORIG-DEST"):
        spec(route_code="DELBOM")


def test_the_match_hash_is_stable_and_short() -> None:
    assert spec().match_hash == spec().match_hash
    assert len(spec().match_hash) == 16
    assert spec().match_hash != spec(carrier="SG").match_hash
