"""Online travel aggregators (Tier 4) — built, registered, and never run.

PS 26056 names MakeMyTrip, Yatra, EaseMyTrip, Cleartrip, Ixigo and Goibibo.
Research established that MakeMyTrip's robots.txt disallows `/air/*`, and the
others are treated as restricted by default pending a runtime check. So these
six sources exist in the registry, have adapters, and are refused by the
compliance gate every time.

**Why build an adapter that cannot run.** Three reasons, in increasing order of
importance. It keeps the source visible and auditable rather than quietly
dropped. It means the day a source's terms change, enabling it is a
configuration decision rather than a development project. And demonstrating a
built adapter that the gate refuses is stronger evidence of engineering
judgement than a scraper that quietly ignores a site's terms.

**Why the parser is deliberately unvalidated.** A parser is only correct
relative to real output, and we have never lawfully obtained any. Writing one
against guessed markup would produce code that looks tested, passes its own
fixtures, and is worth nothing - the fixtures would encode our guess rather than
the site's behaviour. So :meth:`parse` raises, loudly, naming what is missing.

That is not an unfinished adapter. It is an adapter that refuses to pretend.
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

__all__ = ["OtaAdapter", "OtaExecutionRefusedError", "OtaParserNotValidatedError"]


class OtaParserNotValidatedError(RuntimeError):
    """No parser has been validated against this source's real output.

    Raised instead of returning a plausible-looking empty list, because an empty
    list would flow silently into the pipeline and be indistinguishable from
    "this route had no flights today".
    """


class OtaExecutionRefusedError(RuntimeError):
    """An OTA adapter was asked to fetch. It must not be.

    The compliance gate should have refused long before reaching here. If this
    is raised, something upstream is wrong - a source was enabled that should
    not have been, or an adapter was called outside the runner. Raising is the
    correct response: this is a safety property failing, not an error to log and
    continue past.
    """


class OtaAdapter(SourceAdapter):
    """Contract-complete adapter for an OTA flight-search page. Never executes."""

    adapter_key: ClassVar[str] = "ota_web_v1"

    #: Documented robots restrictions, recorded from research on 6 September 2026.
    #: Advisory only - the gate re-fetches robots.txt at runtime and decides from
    #: what the site says today, never from this table.
    KNOWN_RESTRICTIONS: ClassVar[dict[str, str]] = {
        "makemytrip": "robots.txt: Disallow: /air/*, /pwa/, /flights/get-fare-calendar-block.html",
        "goibibo": "same corporate group as MakeMyTrip; treated as restricted pending check",
        "yatra": "restricted by default pending a runtime robots.txt check",
        "easemytrip": "restricted by default pending a runtime robots.txt check",
        "cleartrip": "restricted by default pending a runtime robots.txt check",
        "ixigo": "restricted by default pending a runtime robots.txt check",
    }

    def __init__(self, source_code: str) -> None:
        self.source_code = source_code

    def validate_source(self, *, source_code: str, base_url: str | None) -> SourceValidation:
        """Always invalid for collection, with the reason stated.

        Reported as a validation failure rather than a health warning so that
        any attempt to enable one of these sources fails at the earliest
        possible point, with an explanation.
        """
        return SourceValidation.invalid(
            f"{source_code} is a Tier 4 source: automated collection from its flight "
            "search is not permitted. "
            + self.KNOWN_RESTRICTIONS.get(source_code, "Restricted by default."),
            "The adapter exists so the source stays visible and auditable, and so "
            "that enabling it later is a configuration decision rather than a "
            "development project.",
        )

    def build_request(self, spec: CollectionSpec) -> AdapterRequest:
        """Build the request the gate will evaluate - and refuse.

        Real, not a placeholder. The gate must evaluate the path this adapter
        would genuinely fetch, or the refusal recorded in the audit trail would
        be about a different request from the one that was declined.
        """
        return AdapterRequest(
            path="/air/search",
            params={
                "itinerary": f"{spec.origin}-{spec.destination}-{spec.travel_date:%d/%m/%Y}",
                "paxType": "A-1_C-0_I-0",
                "cabinClass": "E",
                "tripType": "O",
            },
        )

    def execute(
        self,
        request: AdapterRequest,
        token: ComplianceToken,
        *,
        base_url: str,
    ) -> AdapterResponse:
        del request, token, base_url  # never used: this adapter does not fetch
        raise OtaExecutionRefusedError(
            f"{self.source_code} must not be fetched. Automated collection from this "
            "source's flight search is disallowed, and the compliance gate should "
            "have refused before an adapter was reached. Holding a valid token does "
            "not make the fetch permitted - the token proves the gate ran, not that "
            "the source allows collection."
        )

    def parse(self, response: AdapterResponse) -> list[ParsedQuote]:
        del response
        raise OtaParserNotValidatedError(
            f"No parser has been validated against {self.source_code} output, because "
            "no response has ever been lawfully obtained from it. Writing one against "
            "guessed markup would produce code that passes its own fixtures and means "
            "nothing. If this source becomes permitted, capture real output first, "
            "freeze it as a fixture, then write the parser against it."
        )

    def normalize(self, quote: ParsedQuote) -> dict[str, Any]:
        del quote
        raise OtaParserNotValidatedError(
            f"Nothing to normalise: {self.source_code} has no validated parser."
        )

    def health_check(self) -> HealthReport:
        """Reports healthy. A correctly-blocked source is not a broken one.

        Marking these unhealthy would fill the operations console with red for a
        system behaving exactly as designed, and a console that is always red is
        a console nobody reads.
        """
        return HealthReport(
            healthy=True,
            detail=(
                f"{self.source_code}: adapter registered, execution withheld. "
                + self.KNOWN_RESTRICTIONS.get(self.source_code, "Restricted by default.")
            ),
            checked_at=datetime.now(UTC),
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            **super().diagnostics(),
            "source_code": self.source_code,
            "tier": 4,
            "executes": False,
            "parser_validated": False,
            "known_restriction": self.KNOWN_RESTRICTIONS.get(self.source_code),
            "note": (
                "Built so the source stays visible and auditable, and so that a "
                "change in its terms is a config decision rather than a project."
            ),
        }
