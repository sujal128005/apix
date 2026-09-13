"""Ingestion of price quotes supplied by MoSPI or DGCA.

Three sources of Indian airfare data exist that this project cannot reach and
the ministry already holds:

1. **MoSPI's own online collection.** Regional Offices already collect airfares
   from online platforms for CPI 2024 (FAQ Q27). APIx consuming those quotes
   aligns it with CPI by construction rather than by argument, and raises no new
   legal ground at all.
2. **The DGCA Tariff Monitoring Unit feed.** 78 routes, monthly, already
   collected. Monthly frequency suits validation better than a daily index.
3. **Airline tariff sheets furnished to DGCA** monthly under ATC 02/2010. Fare
   *bands*, not transacted prices - useful for bounds and anomaly detection.

None of their file formats are known here, and **this module does not guess at
them**. It defines the interchange contract APIx needs - which fields, in which
units, with what meaning - and validates supplied data against it strictly. If
the ministry's format differs, :func:`parse_supplied_quotes` is the one place
that changes; everything downstream is untouched.

That is the point of writing it now. The contract is a document the ministry can
review and object to before anyone builds against it, and the moment a file
arrives the work is a field mapping rather than a project.

**Refusal is the default.** A supplied row missing a price-determining field is
rejected, not defaulted. Ingesting official data is exactly where a silent
default becomes a wrong published figure, because nobody downstream will think
to question a number that came from the ministry.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

__all__ = [
    "REQUIRED_FIELDS",
    "SuppliedQuote",
    "SupplyFormatError",
    "SupplySource",
    "ValidationReport",
    "parse_supplied_quotes",
]


class SupplySource(StrEnum):
    """Which ministry channel a file came from. Determines how it may be used."""

    MOSPI_RO_COLLECTION = "MOSPI_RO_COLLECTION"
    """Price quotes collected by MoSPI Regional Offices. Transacted prices:
    these may enter the index."""

    DGCA_TMU = "DGCA_TMU"
    """Tariff Monitoring Unit observations. Monthly, 78 routes. Transacted
    prices, but at a frequency that suits validation rather than a daily index."""

    AIRLINE_TARIFF_SHEET = "AIRLINE_TARIFF_SHEET"
    """Declared tariff bands under ATC 02/2010. **Not transacted prices.** These
    may bound and validate the index; they must never feed it."""


#: Fields every supplied row must carry. Each is price-determining or needed for
#: matching, so a row missing one cannot be placed in the index and is rejected.
REQUIRED_FIELDS: tuple[str, ...] = (
    "collected_date",
    "travel_date",
    "origin",
    "destination",
    "carrier",
    "total_fare",
    "currency",
)

#: Requested but not required. Their absence degrades a quote rather than
#: invalidating it: a total fare with no tax breakdown is still a usable price.
OPTIONAL_FIELDS: tuple[str, ...] = (
    "flight_number",
    "departure_time",
    "cabin",
    "fare_brand",
    "base_fare",
    "taxes",
    "udf",
    "convenience_fee",
    "baggage_kg",
    "refundability",
    "changeability",
    "source_platform",
)


class SupplyFormatError(ValueError):
    """A supplied file cannot be read at all - wrong columns, not a CSV."""


@dataclass(frozen=True, slots=True)
class SuppliedQuote:
    """One validated price observation from a ministry channel."""

    source: SupplySource
    collected_date: date
    travel_date: date
    origin: str
    destination: str
    carrier: str
    total_fare: Decimal
    currency: str
    row_number: int
    optional: dict[str, Any] = field(default_factory=dict)

    @property
    def route_code(self) -> str:
        return f"{self.origin}-{self.destination}"

    @property
    def lead_time_days(self) -> int:
        return (self.travel_date - self.collected_date).days

    @property
    def is_transacted_price(self) -> bool:
        """A declared tariff band is a ceiling an airline filed, not a fare paid.

        The pipeline acts on this rather than on a comment: tariff-sheet records
        are kept out of the index while remaining available for validation.
        """
        return self.source is not SupplySource.AIRLINE_TARIFF_SHEET


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """What a supplied file contained, and what was refused.

    Rejections are itemised with their row number and reason. A ministry
    supplying data is entitled to know precisely which rows were not used and
    why - "1,204 of 50,000 rows rejected" with no detail is not something anyone
    can act on.
    """

    source: SupplySource
    rows_read: int
    accepted: tuple[SuppliedQuote, ...]
    rejected: tuple[tuple[int, str], ...]

    @property
    def rejection_rate(self) -> Decimal:
        if self.rows_read == 0:
            return Decimal("0.000")
        return (Decimal(len(self.rejected)) / Decimal(self.rows_read)).quantize(
            Decimal("0.001")
        )

    @property
    def is_usable(self) -> bool:
        """Whether the file is fit to ingest at all.

        A file rejecting more than a fifth of its rows signals a format
        mismatch rather than dirty data, and ingesting the remainder would
        silently publish an index built on whichever rows happened to parse.
        """
        return bool(self.accepted) and self.rejection_rate <= Decimal("0.200")


def _parse_date(value: str, label: str) -> date:
    text = value.strip()
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise ValueError(
        f"{label} {text!r} is not a recognised date. Supply ISO 8601 (YYYY-MM-DD); "
        "DD/MM/YYYY, DD-MM-YYYY and DD-Mon-YYYY are also accepted. Ambiguous "
        "formats are refused rather than guessed - a date read the wrong way "
        "round moves a fare into a different advance-purchase window."
    )


def _parse_money(value: str, label: str) -> Decimal:
    text = value.strip().replace(",", "").replace("\u20b9", "").replace("INR", "").strip()
    if not text:
        raise ValueError(f"{label} is empty")
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{label} {value!r} is not a parseable amount") from exc
    if amount <= 0:
        raise ValueError(
            f"{label} is {amount}. A zero or negative fare is a data error, not a "
            "free flight, and is refused rather than carried into the index."
        )
    return amount


def _parse_row(
    row: dict[str, str], source: SupplySource, row_number: int
) -> SuppliedQuote:
    missing = [f for f in REQUIRED_FIELDS if not (row.get(f) or "").strip()]
    if missing:
        raise ValueError(
            f"missing required field(s): {', '.join(missing)}. Required fields are "
            "price-determining or needed for matching; a row without them cannot be "
            "placed in the index."
        )

    currency = row["currency"].strip().upper()
    if currency != "INR":
        raise ValueError(
            f"currency {currency!r} is out of scope. APIx covers domestic fares in "
            "INR; converting would introduce an exchange-rate series into a price "
            "index."
        )

    origin = row["origin"].strip().upper()
    destination = row["destination"].strip().upper()
    for code, label in ((origin, "origin"), (destination, "destination")):
        if len(code) != 3 or not code.isalpha():
            raise ValueError(f"{label} {code!r} is not a 3-letter IATA airport code")
    if origin == destination:
        raise ValueError(f"origin and destination are both {origin!r}")

    carrier = row["carrier"].strip().upper()
    if len(carrier) != 2:
        raise ValueError(f"carrier {carrier!r} is not a 2-character IATA code")

    collected = _parse_date(row["collected_date"], "collected_date")
    travel = _parse_date(row["travel_date"], "travel_date")
    if travel < collected:
        raise ValueError(
            f"travel_date {travel} precedes collected_date {collected}. Most often "
            "this is a day/month transposition rather than a real observation."
        )

    return SuppliedQuote(
        source=source,
        collected_date=collected,
        travel_date=travel,
        origin=origin,
        destination=destination,
        carrier=carrier,
        total_fare=_parse_money(row["total_fare"], "total_fare"),
        currency=currency,
        row_number=row_number,
        optional={
            name: row[name].strip()
            for name in OPTIONAL_FIELDS
            if (row.get(name) or "").strip()
        },
    )


def parse_supplied_quotes(content: str, source: SupplySource) -> ValidationReport:
    """Validate a supplied CSV against the interchange contract.

    Returns a report rather than raising on bad rows: one malformed row in fifty
    thousand should not discard the file, and the ministry needs to be told which
    rows were refused. A file that cannot be read *at all* - wrong columns, not a
    CSV - does raise, because there is nothing to report on.
    """
    try:
        reader = csv.DictReader(io.StringIO(content))
        fieldnames = reader.fieldnames
    except csv.Error as exc:
        raise SupplyFormatError(f"not readable as CSV: {exc}") from exc

    if not fieldnames:
        raise SupplyFormatError("the file has no header row")

    present = {name.strip() for name in fieldnames}
    absent = [f for f in REQUIRED_FIELDS if f not in present]
    if absent:
        raise SupplyFormatError(
            f"the header is missing required column(s): {', '.join(absent)}. "
            f"Expected at least: {', '.join(REQUIRED_FIELDS)}. "
            "If the supplied format differs, map it in this function rather than "
            "relaxing the contract - the rest of the pipeline depends on these "
            "fields meaning what they say."
        )

    accepted: list[SuppliedQuote] = []
    rejected: list[tuple[int, str]] = []
    rows_read = 0

    for row_number, row in enumerate(reader, start=2):  # row 1 is the header
        rows_read += 1
        try:
            accepted.append(_parse_row(row, source, row_number))
        except ValueError as exc:
            rejected.append((row_number, str(exc)))

    return ValidationReport(
        source=source,
        rows_read=rows_read,
        accepted=tuple(accepted),
        rejected=tuple(rejected),
    )
