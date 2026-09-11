"""Amadeus Self-Service — Flight Offers Search (Tier 1, licensed API).

The preferred source under ADR-001: a contracted API, so there is no robots.txt
question and no ambiguity about whether collection is permitted. Structured fare
data with a tax breakdown also solves fare decomposition cleanly, which HTML
scraping rarely does.

**Status: parser written against Amadeus' published response schema, validated
against fixtures, and not yet run against the live API.** Open item O-3 - whether
Amadeus carries Indian low-cost-carrier content for IndiGo, SpiceJet and Akasa -
is unresolved, and GDS coverage of LCCs is historically uneven. Until a live
production call confirms otherwise, treat this adapter as ready rather than
proven, and treat carrier coverage as unknown rather than assumed.

Two things to know before enabling it:

**Use production credentials, not test.** The test tier serves cached, limited
data. A test-tier response would answer a different question from the one O-3
asks, and answer it misleadingly.

**The token is still required.** A licensed API is exempt from robots.txt, not
from the compliance gate (ADR-019). Tier 1 still needs an APPROVED source review
citing the developer terms, and ``execute`` still needs a ``ComplianceToken``.
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

__all__ = ["AmadeusAdapter"]

FLIGHT_OFFERS_PATH = "/v2/shopping/flight-offers"


class AmadeusAdapter(SourceAdapter):
    """Fetch and parse Amadeus flight offers."""

    adapter_key: ClassVar[str] = "amadeus_flight_offers_v2"

    def __init__(self, access_token: str | None = None, *, max_offers: int = 50) -> None:
        # The OAuth token is supplied by the caller from the environment. It is
        # never read here and never logged: a credential that appears in an
        # adapter's constructor default has a way of ending up in a traceback.
        self._access_token = access_token
        self._max_offers = max_offers

    # -- contract ---------------------------------------------------------
    def validate_source(self, *, source_code: str, base_url: str | None) -> SourceValidation:
        problems: list[str] = []
        if not base_url:
            problems.append(f"{source_code} has no base_url")
        if not self._access_token:
            problems.append(
                "No Amadeus access token. Set AMADEUS_ACCESS_TOKEN; the adapter does "
                "not fall back to unauthenticated access."
            )
        return SourceValidation.valid() if not problems else SourceValidation.invalid(*problems)

    def build_request(self, spec: CollectionSpec) -> AdapterRequest:
        """Economy, one-way, direct, one adult — the constant-quality scope (PA-2)."""
        return AdapterRequest(
            path=FLIGHT_OFFERS_PATH,
            params={
                "originLocationCode": spec.origin,
                "destinationLocationCode": spec.destination,
                "departureDate": spec.travel_date.isoformat(),
                "adults": "1",
                "travelClass": "ECONOMY",
                "nonStop": "true",
                "currencyCode": "INR",
                "max": str(self._max_offers),
            },
        )

    def execute(
        self,
        request: AdapterRequest,
        token: ComplianceToken,
        *,
        base_url: str,
    ) -> AdapterResponse:
        import httpx

        if token.path != request.path:
            raise AssertionError(
                f"token authorises {token.path!r} but the adapter is fetching "
                f"{request.path!r}; the gate evaluated a different request"
            )
        if not self._access_token:
            raise RuntimeError("No Amadeus access token configured.")

        with httpx.Client(timeout=30.0, verify=True) as client:
            response = client.get(
                f"{base_url.rstrip('/')}{request.path}",
                params=request.params,
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Accept": "application/json",
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
        """Extract offers. Pure, so any real response can be frozen as a fixture.

        Multi-segment itineraries are skipped rather than flattened. A one-stop
        itinerary is a different product from a direct flight, and folding the
        two together would let a product substitution register as a price
        change - the failure mode matched-pair construction exists to prevent.
        """
        payload = json.loads(response.body)
        offers = payload.get("data", [])

        quotes: list[ParsedQuote] = []
        for offer in offers:
            itineraries = offer.get("itineraries", [])
            if len(itineraries) != 1:
                continue
            segments = itineraries[0].get("segments", [])
            if len(segments) != 1:
                continue  # not a direct flight

            segment = segments[0]
            price = offer.get("price", {})
            branded = _branded_fare(offer)

            quotes.append(
                ParsedQuote(
                    ordinal=len(quotes),
                    payload={
                        "carrierCode": segment.get("carrierCode"),
                        "number": segment.get("number"),
                        "departureAt": segment.get("departure", {}).get("at"),
                        "arrivalAt": segment.get("arrival", {}).get("at"),
                        "brandedFare": branded,
                        "currency": price.get("currency"),
                        "total": price.get("grandTotal") or price.get("total"),
                        "base": price.get("base"),
                        "fees": price.get("fees", []),
                    },
                )
            )
        return quotes

    def normalize(self, quote: ParsedQuote) -> dict[str, Any]:
        """Map Amadeus field names onto the canonical shape. Naming only.

        Taxes are derived as total minus base minus itemised fees, because
        Amadeus reports a base and a grand total but does not always itemise tax
        separately. Where the arithmetic cannot be completed the component is
        omitted rather than guessed, and the pipeline marks the quote PARTIAL.
        """
        payload = quote.payload
        result: dict[str, Any] = {
            "carrier": payload.get("carrierCode"),
            "flight_no": (
                f"{payload.get('carrierCode')}{payload.get('number')}"
                if payload.get("carrierCode") and payload.get("number")
                else None
            ),
            "fare_brand": payload.get("brandedFare"),
            "total_fare": payload.get("total"),
            "currency": payload.get("currency"),
            "departure_at": payload.get("departureAt"),
        }

        total, base = payload.get("total"), payload.get("base")
        if total is not None and base is not None:
            from decimal import Decimal, InvalidOperation

            try:
                fee_total = sum(
                    (Decimal(str(f.get("amount", "0"))) for f in payload.get("fees", [])),
                    Decimal(0),
                )
                taxes = Decimal(str(total)) - Decimal(str(base)) - fee_total
            except (InvalidOperation, TypeError, ValueError):
                return result
            result["base_fare"] = str(base)
            if taxes >= 0:
                result["taxes"] = str(taxes)
            if fee_total > 0:
                result["convenience_fee"] = str(fee_total)
        return result

    def health_check(self) -> HealthReport:
        configured = bool(self._access_token)
        return HealthReport(
            healthy=configured,
            detail=(
                "Amadeus adapter configured. Carrier coverage for Indian LCCs is "
                "unverified (open item O-3)."
                if configured
                else "No AMADEUS_ACCESS_TOKEN configured; adapter cannot run."
            ),
            checked_at=datetime.now(UTC),
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            **super().diagnostics(),
            "token_configured": bool(self._access_token),
            "max_offers": self._max_offers,
            "coverage_verified": False,
            "coverage_note": (
                "O-3 unresolved: GDS coverage of IndiGo, SpiceJet and Akasa is "
                "historically uneven and has not been confirmed for this account."
            ),
        }


def _branded_fare(offer: dict[str, Any]) -> str | None:
    """The branded fare name, where the traveller pricing carries one."""
    for pricing in offer.get("travelerPricings", []):
        for segment in pricing.get("fareDetailsBySegment", []):
            branded = segment.get("brandedFare") or segment.get("fareBasis")
            if branded:
                return str(branded)
    return None
