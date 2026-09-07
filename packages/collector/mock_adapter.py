"""A fixture-backed adapter for tests and for exercising the pipeline offline.

It implements the full contract without a network, so the runner, the gate and
the persistence path can all be tested end to end with no site involved. It is
also the reference implementation an adapter author should read first.

Every quote it produces carries ``provenance = SIMULATED_DEMO``. That is not a
detail: the database trigger installed in Phase 3 refuses to let a headline
index value be computed for any date on which a SIMULATED_DEMO quote exists, so
this adapter is structurally incapable of contaminating a published number, no
matter how it is wired up by mistake.
"""

from __future__ import annotations

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
from schemas.enums import Provenance

__all__ = ["MockAdapter", "MockBehaviour"]


class MockBehaviour:
    """How the mock should respond, so failure paths are testable."""

    OK = "OK"
    HTTP_ERROR = "HTTP_ERROR"
    TIMEOUT = "TIMEOUT"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    UNPARSEABLE = "UNPARSEABLE"
    EMPTY = "EMPTY"


class MockAdapter(SourceAdapter):
    """Returns canned fares. Never touches the network."""

    adapter_key: ClassVar[str] = "mock_v1"

    def __init__(
        self,
        *,
        behaviour: str = MockBehaviour.OK,
        quote_count: int = 3,
        recover_after: int | None = None,
    ) -> None:
        self.behaviour = behaviour
        self.quote_count = quote_count
        self.recover_after = recover_after
        self.attempts = 0
        self.executed_paths: list[str] = []
        self.tokens_seen: list[ComplianceToken] = []

    # -- contract ----------------------------------------------------------
    def validate_source(self, *, source_code: str, base_url: str | None) -> SourceValidation:
        if not base_url:
            return SourceValidation.invalid(f"{source_code} has no base_url")
        return SourceValidation.valid()

    def build_request(self, spec: CollectionSpec) -> AdapterRequest:
        return AdapterRequest(
            path=f"/search/{spec.origin}-{spec.destination}",
            params={
                "departure": spec.travel_date.isoformat(),
                "adults": "1",
                "cabin": "economy",
                "nonstop": "true",
            },
        )

    def execute(
        self,
        request: AdapterRequest,
        token: ComplianceToken,
        *,
        base_url: str,
    ) -> AdapterResponse:
        self.attempts += 1
        self.tokens_seen.append(token)
        self.executed_paths.append(request.path)

        # The token authorises one specific path. Fetching a different one would
        # make the gate's evaluation meaningless, so it is checked here too.
        if token.path != request.path:
            raise AssertionError(
                f"token authorises {token.path!r} but the adapter is fetching {request.path!r}"
            )

        behaviour = self.behaviour
        if self.recover_after is not None and self.attempts > self.recover_after:
            behaviour = MockBehaviour.OK

        now = datetime.now(UTC)
        if behaviour == MockBehaviour.TIMEOUT:
            raise TimeoutError("mock timeout")
        if behaviour == MockBehaviour.CONNECTION_ERROR:
            raise ConnectionError("mock connection failure")
        if behaviour == MockBehaviour.HTTP_ERROR:
            return AdapterResponse(body="", http_status=503, fetched_at=now)
        if behaviour == MockBehaviour.UNPARSEABLE:
            return AdapterResponse(body="<<<not json>>>", http_status=200, fetched_at=now)
        if behaviour == MockBehaviour.EMPTY:
            return AdapterResponse(body='{"offers": []}', http_status=200, fetched_at=now)

        offers = ",".join(
            f'{{"carrier":"6E","flightNumber":"6E{100 + i}",'
            f'"totalAmount":"{5000 + i * 500}.00","currencyCode":"INR",'
            f'"fareBrand":"SAVER","stops":0}}'
            for i in range(self.quote_count)
        )
        return AdapterResponse(
            body=f'{{"offers": [{offers}]}}',
            http_status=200,
            fetched_at=now,
            content_type="application/json",
        )

    def parse(self, response: AdapterResponse) -> list[ParsedQuote]:
        import json

        offers = json.loads(response.body)["offers"]
        return [ParsedQuote(ordinal=i, payload=offer) for i, offer in enumerate(offers)]

    def normalize(self, quote: ParsedQuote) -> dict[str, Any]:
        """Rename source fields to the common shape. No cleaning here."""
        payload = quote.payload
        return {
            "carrier": payload["carrier"],
            "flight_no": payload["flightNumber"],
            "total_fare": payload["totalAmount"],
            "currency": payload["currencyCode"],
            "fare_brand": payload["fareBrand"],
            "stops": payload["stops"],
            "provenance": Provenance.SIMULATED_DEMO,
        }

    def health_check(self) -> HealthReport:
        healthy = self.behaviour == MockBehaviour.OK
        return HealthReport(
            healthy=healthy,
            detail=f"mock adapter behaving as {self.behaviour}",
            checked_at=datetime.now(UTC),
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            **super().diagnostics(),
            "behaviour": self.behaviour,
            "attempts": self.attempts,
            "paths_fetched": list(self.executed_paths),
        }
