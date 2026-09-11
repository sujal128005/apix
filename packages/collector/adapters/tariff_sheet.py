"""Airline published tariff sheets (Tier 2, regulatory disclosure).

The sleeper asset of this project, and the one almost nobody looks for.

**Rule 135(2), Aircraft Rules 1937** requires that an airline's established
tariff be published on its website. **DGCA Air Transport Circular 02 of 2010**
further requires scheduled domestic airlines to display route-wise tariff sheets
across their network in various fare categories, and to furnish the same to
DGCA.

That is a statutory public-disclosure obligation. The document exists in order
to be read, which makes collecting it materially more defensible than crawling a
booking funnel - and it does not depend on a site's goodwill.

**What it is not.** A declared tariff is a fare *band*, not the transacted price
a consumer pays on a given day. It cannot substitute for observed quotes, and
this adapter must never silently feed the index as though it could. Its uses
are: validating that observed fares fall within declared bands, carrier-level
context, and anomaly detection when an observed fare sits outside its band.

Provenance is therefore ``OFFICIAL_STATISTIC``, and ``is_transacted_price`` is
False on every record it produces - a flag the pipeline can act on rather than a
caveat in a docstring nobody reads.

**Status: URLs unresolved (open item O-4).** Each airline's current tariff-sheet
location must be found by inspection, per carrier, and recorded in configuration.
The adapter is structured so that finding them is a config change, not a code
change.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
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

__all__ = ["TariffSheetAdapter", "TariffSheetNotLocatedError"]


class TariffSheetNotLocatedError(RuntimeError):
    """No tariff-sheet path is configured for this carrier (open item O-4).

    Raised rather than defaulted. A guessed URL would either 404 or, worse,
    fetch some other document and parse it as a tariff.
    """


class TariffSheetAdapter(SourceAdapter):
    """Retrieve and parse a carrier's published route-wise tariff sheet."""

    adapter_key: ClassVar[str] = "airline_tariff_doc_v1"

    #: Filled from configuration once O-4 is resolved by inspection. Deliberately
    #: empty: an invented path is worse than a missing one.
    TARIFF_PATHS: ClassVar[dict[str, str]] = {}

    def __init__(self, tariff_paths: dict[str, str] | None = None) -> None:
        self._paths = dict(tariff_paths or self.TARIFF_PATHS)

    def validate_source(self, *, source_code: str, base_url: str | None) -> SourceValidation:
        problems: list[str] = []
        if not base_url:
            problems.append(f"{source_code} has no base_url")
        if source_code not in self._paths:
            problems.append(
                f"No tariff-sheet path configured for {source_code}. Open item O-4: "
                "each carrier's current tariff-sheet URL must be located by "
                "inspection under DGCA Circular 02/2010 and recorded in config."
            )
        return SourceValidation.valid() if not problems else SourceValidation.invalid(*problems)

    def build_request(self, spec: CollectionSpec) -> AdapterRequest:
        path = self._paths.get(spec.source_code)
        if path is None:
            raise TariffSheetNotLocatedError(
                f"No tariff-sheet path for {spec.source_code!r} (open item O-4)."
            )
        return AdapterRequest(path=path)

    def execute(
        self, request: AdapterRequest, token: ComplianceToken, *, base_url: str
    ) -> AdapterResponse:
        import httpx

        if token.path != request.path:
            raise AssertionError(
                f"token authorises {token.path!r}, adapter is fetching {request.path!r}"
            )
        with httpx.Client(timeout=30.0, verify=True, follow_redirects=True) as client:
            response = client.get(
                f"{base_url.rstrip('/')}{request.path}",
                headers={"User-Agent": token.user_agent},
            )
        return AdapterResponse(
            body=response.text,
            http_status=response.status_code,
            fetched_at=datetime.now(UTC),
            content_type=response.headers.get("Content-Type"),
        )

    def parse(self, response: AdapterResponse) -> list[ParsedQuote]:
        """Extract route/fare-category bands from a tariff table.

        Handles the common shape: an HTML table with a route column and one
        column per fare category. Per-carrier deviations are handled by
        subclassing rather than by a growing thicket of conditionals here -
        each airline's markup is that airline's problem, not the framework's.
        """
        import re

        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", response.body, re.S | re.I)
        if not rows:
            return []

        header = [_strip(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", rows[0], re.S | re.I)]
        quotes: list[ParsedQuote] = []

        for row in rows[1:]:
            cells = [_strip(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S | re.I)]
            if len(cells) < 2 or not cells[0]:
                continue
            sector = cells[0]
            for index, value in enumerate(cells[1:], start=1):
                amount = _amount(value)
                if amount is None:
                    continue
                category = header[index] if index < len(header) else f"col{index}"
                quotes.append(
                    ParsedQuote(
                        ordinal=len(quotes),
                        payload={
                            "sector": sector,
                            "fare_category": category,
                            "declared_fare": amount,
                        },
                    )
                )
        return quotes

    def normalize(self, quote: ParsedQuote) -> dict[str, Any]:
        """Canonical shape, flagged as a declared band rather than a paid price."""
        payload = quote.payload
        return {
            "sector": payload.get("sector"),
            "fare_brand": payload.get("fare_category"),
            "declared_fare": payload.get("declared_fare"),
            "currency": "INR",
            # Load-bearing. A declared tariff is a ceiling an airline has filed,
            # not a fare anyone paid. The pipeline uses this to keep tariff
            # records out of the index while still using them for validation.
            "is_transacted_price": False,
            "basis": "Rule 135(2) Aircraft Rules 1937; DGCA Air Transport Circular 02/2010",
        }

    def health_check(self) -> HealthReport:
        return HealthReport(
            healthy=bool(self._paths),
            detail=(
                f"{len(self._paths)} carrier tariff path(s) configured."
                if self._paths
                else "No tariff-sheet paths configured (open item O-4). Locate each "
                "carrier's published route-wise tariff sheet and record it in config."
            ),
            checked_at=datetime.now(UTC),
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            **super().diagnostics(),
            "carriers_configured": sorted(self._paths),
            "produces_transacted_prices": False,
            "regulatory_basis": (
                "Rule 135(2) Aircraft Rules 1937; "
                "DGCA Air Transport Circular 02 of 2010"
            ),
        }


def _strip(cell: str) -> str:
    """Tags out, entities decoded, whitespace collapsed.

    Entity decoding is not cosmetic. A rupee sign written as ``&#8377;`` leaves
    the digits 8377 behind if only tags are stripped, so "&#8377; 4,500" parses
    as 83,774,500 - a fare four orders of magnitude wrong, and wrong in a way
    that still looks like a number.
    """
    import html
    import re

    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", cell)).split())


#: Below this a "fare" is a parse artefact - a footnote marker, a column index,
#: or a fragment that survived the tag stripper.
MIN_PLAUSIBLE_FARE = Decimal("500")
#: And above it likewise: no domestic economy tariff band reaches here.
MAX_PLAUSIBLE_FARE = Decimal("2000000")


def _amount(value: str) -> str | None:
    """Parse a rupee amount from a cell, or return None. Never guesses.

    Decimal, not float. This parses money, and the project's no-float rule
    covers it for the same reason it covers the index engine: a fare should not
    pass through binary floating point on its way into the system.

    Amounts outside a plausible band are rejected rather than passed on. A
    mangled cell that yields a number is more dangerous than one that yields
    nothing, because nothing is visibly missing and a wrong number is not.
    """
    import re

    # The first number-shaped run only. Taking every digit in the cell would let
    # a stray marker elsewhere glue itself onto the amount - which is precisely
    # how "&#8377; 4,500" became 83,774,500 before entities were decoded.
    match = re.search(r"\d[\d,]*(?:\.\d+)?", value)
    if match is None:
        return None
    try:
        amount = Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return None
    if not MIN_PLAUSIBLE_FARE <= amount <= MAX_PLAUSIBLE_FARE:
        return None
    return str(amount.quantize(Decimal("0.01")))
