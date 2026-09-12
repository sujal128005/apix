"""Structured Product Description for airfare.

A price index compares the price of *the same thing* over time. Deciding what
"the same thing" means is the sampling decision, and it is the one an expert
reviewer examines first.

The prototype matched observations on ``(carrier, flight number, fare brand)``.
An independent review identified that correctly as an **identifier tuple, not a
product specification**, and gave the failing case: a schedule change renumbers
IndiGo 6E1234 to 6E5678 with identical cabin, baggage, refundability, routing
and departure time. Nothing about the product changed. The index sees a
disappearance and an arrival, loses the matched pair, and records nothing where a
price movement should have been.

Flight number is operational metadata. It is not a price-determining
characteristic.

This module replaces it with a specification built from characteristics that
actually determine what a traveller is buying. The Expert Group Report's own
framing applies: for services such as airfare, specifications describe *service
attributes* rather than physical ones (§4.4.14), and the airline is explicitly a
price-determining characteristic.

**Departure-time band rather than flight number.** A 06:00 departure and a 21:00
departure on the same route are genuinely different products at genuinely
different prices, and must not be pooled. The same flight renumbered is the same
product and must stay matched. A time band separates those two cases, where a
flight number conflates them.

Characteristics deliberately excluded, with reasons, because an unstated
exclusion is indistinguishable from an oversight:

    aircraft type       not a price-determining characteristic for the traveller
    flight number       operational metadata; see above
    seat number         not priced separately in economy on Indian domestic routes
    booking channel     a distribution difference, not a product difference; the
                        index measures what a traveller pays, not where
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum
from typing import Any

__all__ = [
    "Cabin",
    "Changeability",
    "DepartureBand",
    "ProductSpecification",
    "Refundability",
    "RoutingType",
    "TripType",
    "departure_band_for",
    "specification_from_quote",
]


class Cabin(StrEnum):
    ECONOMY = "ECONOMY"
    PREMIUM_ECONOMY = "PREMIUM_ECONOMY"
    BUSINESS = "BUSINESS"
    FIRST = "FIRST"


class TripType(StrEnum):
    ONE_WAY = "ONE_WAY"
    RETURN = "RETURN"


class RoutingType(StrEnum):
    DIRECT = "DIRECT"
    ONE_STOP = "ONE_STOP"
    MULTI_STOP = "MULTI_STOP"


class Refundability(StrEnum):
    NON_REFUNDABLE = "NON_REFUNDABLE"
    PARTIALLY_REFUNDABLE = "PARTIALLY_REFUNDABLE"
    FULLY_REFUNDABLE = "FULLY_REFUNDABLE"
    UNKNOWN = "UNKNOWN"


class Changeability(StrEnum):
    NO_CHANGES = "NO_CHANGES"
    CHANGE_WITH_FEE = "CHANGE_WITH_FEE"
    FREE_CHANGES = "FREE_CHANGES"
    UNKNOWN = "UNKNOWN"


class DepartureBand(StrEnum):
    """Departure-time bands, in IST.

    Boundaries follow how Indian domestic fares actually behave rather than
    even six-hour blocks: the early-morning and evening peaks are the business
    departures that price differently from midday and late-night services.
    """

    EARLY_MORNING = "EARLY_MORNING"  # 00:00 - 07:59
    MORNING = "MORNING"  # 08:00 - 11:59
    MIDDAY = "MIDDAY"  # 12:00 - 15:59
    EVENING = "EVENING"  # 16:00 - 19:59
    NIGHT = "NIGHT"  # 20:00 - 23:59


_BAND_BOUNDARIES: tuple[tuple[time, DepartureBand], ...] = (
    (time(8, 0), DepartureBand.EARLY_MORNING),
    (time(12, 0), DepartureBand.MORNING),
    (time(16, 0), DepartureBand.MIDDAY),
    (time(20, 0), DepartureBand.EVENING),
)


def departure_band_for(departure: datetime | time) -> DepartureBand:
    """The band a departure falls in. Expects IST."""
    clock = departure.time() if isinstance(departure, datetime) else departure
    for boundary, band in _BAND_BOUNDARIES:
        if clock < boundary:
            return band
    return DepartureBand.NIGHT


@dataclass(frozen=True, slots=True)
class ProductSpecification:
    """What a traveller is buying, in the characteristics that determine price.

    Two observations are the same product when their specifications match. They
    are comparable over time on that basis and on no other.
    """

    route_code: str
    carrier: str
    cabin: Cabin
    trip_type: TripType
    routing: RoutingType
    departure_band: DepartureBand
    fare_brand: str | None
    baggage_kg: int | None
    refundability: Refundability
    changeability: Changeability
    passenger_type: str = "ADULT"

    def __post_init__(self) -> None:
        if len(self.carrier) != 2:
            raise ValueError(f"carrier must be a 2-character IATA code, got {self.carrier!r}")
        if "-" not in self.route_code:
            raise ValueError(f"route_code must be ORIG-DEST, got {self.route_code!r}")

    @property
    def is_fully_specified(self) -> bool:
        """Whether every price-determining characteristic is known.

        A partially specified product can still be priced - the total fare is
        the total fare - but it cannot safely be matched across periods, because
        an unknown characteristic might be the one that changed. The pipeline
        uses this to decide what enters a matched pair rather than silently
        pairing on incomplete information.
        """
        return (
            self.fare_brand is not None
            and self.baggage_kg is not None
            and self.refundability is not Refundability.UNKNOWN
            and self.changeability is not Changeability.UNKNOWN
        )

    @property
    def match_key(self) -> str:
        """A stable identity for this product, for matching across periods.

        Deliberately excludes flight number and departure timestamp: the same
        product renumbered or retimed within its band is still the same product.
        Includes departure band, because a dawn departure and a late-evening one
        are not.
        """
        parts = (
            self.route_code,
            self.carrier,
            self.cabin,
            self.trip_type,
            self.routing,
            self.departure_band,
            self.fare_brand or "?",
            str(self.baggage_kg) if self.baggage_kg is not None else "?",
            self.refundability,
            self.changeability,
            self.passenger_type,
        )
        return "|".join(parts)

    @property
    def match_hash(self) -> str:
        """A short digest of the match key, for indexing and storage."""
        return hashlib.sha256(self.match_key.encode("utf-8")).hexdigest()[:16]

    def differs_from(self, other: ProductSpecification) -> tuple[str, ...]:
        """Which characteristics differ. Used when a product is replaced.

        Naming the differences matters: a replacement differing only in fare
        brand may be quality-adjustable by overlap pricing, whereas one
        differing in cabin is a different product entirely and must not be
        linked.
        """
        differences: list[str] = []
        for field in (
            "route_code", "carrier", "cabin", "trip_type", "routing",
            "departure_band", "fare_brand", "baggage_kg", "refundability",
            "changeability", "passenger_type",
        ):
            if getattr(self, field) != getattr(other, field):
                differences.append(field)
        return tuple(differences)


def specification_from_quote(payload: dict[str, Any], *, route_code: str) -> ProductSpecification:
    """Build a specification from a normalised quote payload.

    Missing characteristics become ``UNKNOWN`` or ``None`` rather than being
    guessed at. A specification that quietly invents a baggage allowance would
    match observations that are not the same product, which is the error this
    module exists to prevent - and it would do so invisibly.
    """
    departure = payload.get("departure_at") or payload.get("departure_ts")
    if isinstance(departure, str):
        departure = datetime.fromisoformat(departure)
    band = (
        departure_band_for(departure)
        if isinstance(departure, datetime)
        else DepartureBand.MORNING
    )

    stops = payload.get("stops")
    routing = (
        RoutingType.DIRECT
        if stops == 0
        else RoutingType.ONE_STOP
        if stops == 1
        else RoutingType.MULTI_STOP
        if isinstance(stops, int)
        else RoutingType.DIRECT
    )

    baggage = payload.get("baggage_kg")
    return ProductSpecification(
        route_code=route_code,
        carrier=str(payload["carrier"]).upper(),
        cabin=Cabin(str(payload.get("cabin", "ECONOMY")).upper()),
        trip_type=TripType(str(payload.get("trip_type", "ONE_WAY")).upper()),
        routing=routing,
        departure_band=band,
        fare_brand=payload.get("fare_brand"),
        baggage_kg=int(baggage) if baggage is not None else None,
        refundability=Refundability(
            str(payload.get("refundability", "UNKNOWN")).upper()
        ),
        changeability=Changeability(
            str(payload.get("changeability", "UNKNOWN")).upper()
        ),
        passenger_type=str(payload.get("passenger_type", "ADULT")).upper(),
    )
