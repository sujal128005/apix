"""Akasa Air — availability search (Tier 3, permitted crawl).

The first adapter in this project that collects a real fare.

Discovered on 13 September 2026 by driving the site once in a browser and
watching what it did (``scripts/discover_source.py``). Fares come from a JSON
endpoint on a **separate host** from the marketing site:

    POST https://prod-bl.qp.akasaair.com/api/ibe/availability/search

Two things that capture changed, both of which would have produced a wrong index
if the adapter had been written from a guess.

**The metropolitan-area flag.** The site sends ``searchOriginMacs: true``, which
expands ``DEL`` to the Delhi metropolitan area and returns departures from
**DXN — Noida International** alongside Delhi's. Pooled into a DEL-BOM index
those are a different airport with a different catchment, and the index would
have been measuring two products as one.

This adapter sends the flag **false** *and* rejects any journey whose stations
differ from those requested. Both, because a request parameter is only a
request: the first version of this module claimed the second guarantee in a
comment and did not implement it, and a fixture replay showed DXN fares passing
straight through.

**The fare join.** A journey carries fare *keys*; the amounts live in a separate
``faresAvailable`` map. Reading the journey alone gives flights with no prices;
reading ``faresAvailable`` alone gives prices attached to nothing.

**Permission.** ``prod-bl.qp.akasaair.com`` serves **no robots.txt**, which our
gate reads as unrestricted (RFC 9309). That is correct as far as it goes and
worth being uncomfortable about: absence on a backend host means nobody
contemplated crawling it, not that anyone allowed it. This adapter is therefore
fit for a prototype and **not** a basis for an official statistic without an
agreement with Akasa. See ``docs/DATA-REQUEST.md``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, ClassVar

from collector.adapter import (
    AdapterRequest,
    AdapterResponse,
    CollectionSpec,
    HealthReport,
    ParsedQuote,
    SourceAdapter,
    SourceValidation,
)
from compliance.token import ComplianceToken

__all__ = ["AVAILABILITY_PATH", "AkasaAdapter"]

AVAILABILITY_PATH = "/api/ibe/availability/search"

#: Service-charge codes seen in live responses, grouped as PS 26056 asks for
#: fares to be decomposed: base fare, taxes, user development fee, and other
#: charges. Codes not listed here are summed into ``other_fees`` rather than
#: dropped - an unrecognised charge is still money the traveller paid.
UDF_CODES = frozenset({"UDF", "DUDF"})
"""User development fee, and the domestic variant. Named explicitly by PS 26056."""

OTHER_FEE_CODES = frozenset({"ASF", "CUTE", "RCS", "WFE", "PSF", "AAI"})
"""Aviation security fee, common-user terminal equipment, regional connectivity
levy, and similar. Statutory or airport charges rather than the carrier's fare."""


class AkasaAdapter(SourceAdapter):
    """Collect Akasa Air fares for one route, date and cabin."""

    adapter_key: ClassVar[str] = "akasa_ibe_v1"

    #: Product classes and fare types the site itself requests. Kept identical
    #: so the adapter sees the same inventory a traveller would; narrowing them
    #: would silently change which products the index prices.
    PRODUCT_CLASSES: ClassVar[list[str]] = ["NB", "LB", "EC", "AV"]
    FARE_TYPES: ClassVar[list[str]] = ["NB", "LB", "R", "V"]

    def __init__(self) -> None:
        # The stations this adapter last asked for. `parse` is pure of network
        # but not of context: it has to know which airport was requested in
        # order to reject one that was not. Set in `build_request`, which the
        # runner always calls first.
        self._expected: tuple[str, str] | None = None

    def validate_source(self, *, source_code: str, base_url: str | None) -> SourceValidation:
        problems: list[str] = []
        if not base_url:
            problems.append(f"{source_code} has no base_url")
        elif "qp.akasaair.com" not in base_url:
            problems.append(
                f"base_url {base_url!r} is not the Akasa booking engine. Fares are "
                "served from prod-bl.qp.akasaair.com, not the marketing site."
            )
        return SourceValidation.valid() if not problems else SourceValidation.invalid(*problems)

    def build_request(self, spec: CollectionSpec) -> AdapterRequest:
        """One availability search: exact airports, one adult, economy, one way.

        ``searchOriginMacs`` and ``searchDestinationMacs`` are **false**. The
        site sends true, which expands a station to its metropolitan area - so a
        DEL search returns Noida (DXN) departures too. For a route-level index
        those are a different product and must not be pooled.
        """
        self._expected = (spec.origin.upper(), spec.destination.upper())
        payload = {
            "criteria": [
                {
                    "stations": {
                        "originStationCodes": [spec.origin],
                        "destinationStationCodes": [spec.destination],
                        "searchOriginMacs": False,
                        "searchDestinationMacs": False,
                    },
                    "dates": {"beginDate": f"{spec.travel_date.isoformat()}T00:00:00"},
                    "filters": {
                        "compressionType": 1,
                        "maxConnections": 0,  # direct only: a connection is a different product
                        "productClasses": self.PRODUCT_CLASSES,
                        "fareTypes": self.FARE_TYPES,
                    },
                }
            ],
            "passengers": {"types": [{"type": "ADT", "count": 1}], "residentCountry": ""},
            "codes": {"currencyCode": "INR", "promotionCode": ""},
            "offerCode": None,
            "numberOfFaresPerJourney": 10,
            "taxesAndFees": 1,
        }
        return AdapterRequest(path=AVAILABILITY_PATH, method="POST", body=json.dumps(payload))

    def execute(
        self, request: AdapterRequest, token: ComplianceToken, *, base_url: str
    ) -> AdapterResponse:
        import httpx

        if token.path != request.path:
            raise AssertionError(
                f"token authorises {token.path!r} but the adapter is fetching "
                f"{request.path!r}; the gate evaluated a different request"
            )

        with httpx.Client(timeout=45.0, verify=True) as client:
            response = client.post(
                f"{base_url.rstrip('/')}{request.path}",
                content=request.body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    # Identifies itself honestly. Presenting a browser's user
                    # agent would be the beginning of evasion, and this project
                    # does not do that.
                    "User-Agent": token.user_agent,
                },
            )
        return AdapterResponse(
            body=response.text,
            http_status=response.status_code,
            fetched_at=datetime.now(UTC),
            content_type=response.headers.get("Content-Type"),
        )

    def parse(self, response: AdapterResponse) -> list[ParsedQuote]:
        """Join journeys to their fares, keeping only non-stop exact-airport flights.

        Pure, so a real response can be frozen as a fixture and replayed offline.
        """
        payload = json.loads(response.body)
        data = payload.get("data") or {}

        # fareAvailabilityKey -> the fare record carrying the amounts.
        fares_by_key: dict[str, Any] = {
            entry["key"]: entry["value"]
            for entry in data.get("faresAvailable", [])
            if entry.get("key")
        }

        quotes: list[ParsedQuote] = []
        for result in data.get("results", []):
            for trip in result.get("trips", []):
                for market in trip.get("journeysAvailableByMarket", []):
                    quotes.extend(
                        self._parse_market(market, fares_by_key, len(quotes))
                    )
        return quotes

    def _parse_market(
        self, market: dict[str, Any], fares_by_key: dict[str, Any], offset: int
    ) -> list[ParsedQuote]:
        quotes: list[ParsedQuote] = []

        for journey in market.get("value", []):
            # Belt and braces against the metropolitan-area expansion: the
            # request asks for exact stations, and this checks the response
            # agreed. A request parameter is a request; the response is the
            # authority, and DXN arriving in a DEL search is exactly the failure
            # this guards.
            designator = journey.get("designator") or {}

            # Reject any station other than the one requested. The request asks
            # for exact airports, but a request is a request and the response is
            # the authority: with the metropolitan flag on, a DEL search returns
            # DXN (Noida International) departures, and pooling those into a
            # DEL-BOM index would measure two airports as one product.
            if self._expected is not None:
                origin = str(designator.get("origin") or "").upper()
                destination = str(designator.get("destination") or "").upper()
                if (origin, destination) != self._expected:
                    continue

            if journey.get("flightType") != "NonStop" or journey.get("stops", 1) != 0:
                continue

            segments = journey.get("segments") or []
            if len(segments) != 1:
                continue
            identifier = segments[0].get("identifier") or {}
            carrier = identifier.get("carrierCode")
            number = identifier.get("identifier")
            if not carrier or not number:
                continue

            for fare_ref in journey.get("fares", []):
                key = fare_ref.get("fareAvailabilityKey")
                fare_record = fares_by_key.get(key)
                if not fare_record:
                    continue

                for fare in fare_record.get("fares", []):
                    for passenger_fare in fare.get("passengerFares", []):
                        if passenger_fare.get("passengerType") != "ADT":
                            continue
                        quotes.append(
                            ParsedQuote(
                                ordinal=offset + len(quotes),
                                payload={
                                    "origin": designator.get("origin"),
                                    "destination": designator.get("destination"),
                                    "departure": designator.get("departure"),
                                    "arrival": designator.get("arrival"),
                                    "carrierCode": carrier,
                                    "flightNumber": str(number).strip(),
                                    "classOfService": fare.get("classOfService"),
                                    "productClass": fare.get("productClass"),
                                    "fareAmount": passenger_fare.get("fareAmount"),
                                    "serviceCharges": passenger_fare.get(
                                        "serviceCharges", []
                                    ),
                                },
                            )
                        )
        return quotes

    def normalize(self, quote: ParsedQuote) -> dict[str, Any]:
        """Map onto the canonical shape, decomposing the fare by charge code.

        PS 26056 asks for base fare, taxes, user development fee and other
        charges separately. Akasa itemises all of them, so nothing here is
        estimated. Charges with an unrecognised code are summed into
        ``other_fees`` rather than dropped: an unfamiliar levy is still money
        the traveller paid, and silently discarding it would understate the fare.
        """
        payload = quote.payload
        charges = payload.get("serviceCharges") or []

        base = taxes = udf = other = None
        for charge in charges:
            amount = charge.get("amount")
            if amount is None:
                continue
            kind, code = charge.get("type"), (charge.get("code") or "").upper()

            if kind == "FarePrice":
                base = _add(base, amount)
            elif kind == "Tax":
                taxes = _add(taxes, amount)
            elif code in UDF_CODES:
                udf = _add(udf, amount)
            else:
                other = _add(other, amount)

        fields: dict[str, Any] = {
            "carrier": payload.get("carrierCode"),
            "flight_no": (
                f"{payload.get('carrierCode')}{payload.get('flightNumber')}"
                if payload.get("carrierCode") and payload.get("flightNumber")
                else None
            ),
            "fare_brand": payload.get("classOfService"),
            "cabin": "ECONOMY",
            "trip_type": "ONE_WAY",
            "stops": 0,
            "total_fare": _money(payload.get("fareAmount")),
            "currency": "INR",
            "departure_at": payload.get("departure"),
            "origin": payload.get("origin"),
            "destination": payload.get("destination"),
        }
        if base is not None:
            fields["base_fare"] = _money(base)
        if taxes is not None:
            fields["taxes"] = _money(taxes)
        if udf is not None:
            fields["udf"] = _money(udf)
        if other is not None:
            fields["convenience_fee"] = _money(other)
        return fields

    def health_check(self) -> HealthReport:
        return HealthReport(
            healthy=True,
            detail=(
                "Akasa availability adapter. The booking-engine host serves no "
                "robots.txt, which the gate reads as unrestricted. Adequate for a "
                "prototype; an official statistic needs an agreement with Akasa."
            ),
            checked_at=datetime.now(UTC),
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            **super().diagnostics(),
            "host": "prod-bl.qp.akasaair.com",
            "robots_txt": "absent - read as unrestricted, not as permission granted",
            "metropolitan_search": False,
            "direct_only": True,
            "fit_for_official_statistic": False,
            "note": (
                "Metropolitan-area search is disabled and journeys are filtered to "
                "non-stop: a DEL search with the flag on returns Noida (DXN) "
                "departures, which are a different airport and must not be pooled."
            ),
        }


def _add(current: Any, amount: Any) -> Any:
    from decimal import Decimal

    value = Decimal(str(amount))
    return value if current is None else current + value


def _money(value: Any) -> str | None:
    """Render an amount as a string. Money never becomes a float, here or anywhere."""
    if value is None:
        return None
    from decimal import Decimal

    return str(Decimal(str(value)).quantize(Decimal("0.01")))
