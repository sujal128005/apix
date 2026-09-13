"""Ingestion of ministry-supplied price quotes.

Most of these are about refusal. Ingesting official data is exactly where a
silent default becomes a wrong published figure, because nobody downstream
thinks to question a number that came from the ministry.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from collector.supply import (
    REQUIRED_FIELDS,
    SupplyFormatError,
    SupplySource,
    parse_supplied_quotes,
)

HEADER = ",".join((*REQUIRED_FIELDS, "flight_number", "fare_brand", "base_fare", "taxes"))


def csv_of(*rows: str) -> str:
    return HEADER + "\n" + "\n".join(rows) + "\n"


GOOD = "2026-09-13,2026-09-20,DEL,BOM,6E,5499.00,INR,6E2134,SAVER,4200.00,1150.00"


# -- the happy path --------------------------------------------------------


def test_a_well_formed_row_is_accepted() -> None:
    report = parse_supplied_quotes(csv_of(GOOD), SupplySource.MOSPI_RO_COLLECTION)

    assert report.rows_read == 1
    assert len(report.accepted) == 1
    quote = report.accepted[0]
    assert quote.route_code == "DEL-BOM"
    assert quote.lead_time_days == 7
    assert quote.total_fare == Decimal("5499.00")
    assert quote.optional["fare_brand"] == "SAVER"


def test_indian_date_and_money_formats_are_accepted() -> None:
    """A ministry file is unlikely to arrive in ISO 8601 with plain decimals."""
    row = "13/09/2026,20/09/2026,DEL,BOM,6E,\"₹5,499.00\",INR,,,,"
    report = parse_supplied_quotes(csv_of(row), SupplySource.DGCA_TMU)

    assert len(report.accepted) == 1
    assert report.accepted[0].total_fare == Decimal("5499.00")
    assert report.accepted[0].collected_date == date(2026, 9, 13)


# -- what the source label means -------------------------------------------


def test_a_tariff_sheet_record_is_not_a_transacted_price() -> None:
    """A declared band is a ceiling an airline filed, not a fare anyone paid.

    The pipeline acts on this flag rather than on a comment, so tariff records
    stay out of the index while remaining available for validation.
    """
    report = parse_supplied_quotes(csv_of(GOOD), SupplySource.AIRLINE_TARIFF_SHEET)
    assert report.accepted[0].is_transacted_price is False

    for source in (SupplySource.MOSPI_RO_COLLECTION, SupplySource.DGCA_TMU):
        assert parse_supplied_quotes(csv_of(GOOD), source).accepted[0].is_transacted_price


# -- refusals --------------------------------------------------------------


@pytest.mark.parametrize("field_index", range(len(REQUIRED_FIELDS)))
def test_a_row_missing_any_required_field_is_rejected(field_index: int) -> None:
    values = GOOD.split(",")
    values[field_index] = ""
    report = parse_supplied_quotes(
        csv_of(",".join(values)), SupplySource.MOSPI_RO_COLLECTION
    )

    assert report.accepted == ()
    assert len(report.rejected) == 1
    assert REQUIRED_FIELDS[field_index] in report.rejected[0][1]


def test_a_foreign_currency_is_refused_rather_than_converted() -> None:
    row = GOOD.replace(",INR,", ",USD,")
    report = parse_supplied_quotes(csv_of(row), SupplySource.MOSPI_RO_COLLECTION)
    assert "out of scope" in report.rejected[0][1]


@pytest.mark.parametrize("fare", ["0", "-500", "abc", ""])
def test_a_non_positive_or_unparseable_fare_is_refused(fare: str) -> None:
    row = GOOD.replace(",5499.00,", f",{fare},")
    report = parse_supplied_quotes(csv_of(row), SupplySource.MOSPI_RO_COLLECTION)
    assert report.accepted == ()


def test_travel_before_collection_is_refused() -> None:
    """Usually a day/month transposition rather than a real observation."""
    row = "2026-09-20,2026-09-13,DEL,BOM,6E,5499.00,INR,,,,"
    report = parse_supplied_quotes(csv_of(row), SupplySource.DGCA_TMU)
    assert "precedes" in report.rejected[0][1]


def test_an_unrecognised_date_format_is_refused_not_guessed() -> None:
    """A date read the wrong way round moves a fare into a different window."""
    row = "September 13 2026,2026-09-20,DEL,BOM,6E,5499.00,INR,,,,"
    report = parse_supplied_quotes(csv_of(row), SupplySource.DGCA_TMU)
    assert "not a recognised date" in report.rejected[0][1]


@pytest.mark.parametrize("origin", ["DELHI", "DE", "1EL", ""])
def test_a_malformed_airport_code_is_refused(origin: str) -> None:
    row = GOOD.replace(",DEL,BOM,", f",{origin},BOM,")
    report = parse_supplied_quotes(csv_of(row), SupplySource.MOSPI_RO_COLLECTION)
    assert report.accepted == ()


def test_a_route_to_itself_is_refused() -> None:
    row = GOOD.replace(",DEL,BOM,", ",DEL,DEL,")
    report = parse_supplied_quotes(csv_of(row), SupplySource.MOSPI_RO_COLLECTION)
    assert "both" in report.rejected[0][1]


# -- file-level problems ---------------------------------------------------


def test_a_file_missing_a_required_column_is_refused_entirely() -> None:
    """Not a row problem: there is nothing to report on."""
    header = ",".join(f for f in REQUIRED_FIELDS if f != "total_fare")
    with pytest.raises(SupplyFormatError, match="total_fare"):
        parse_supplied_quotes(header + "\n", SupplySource.DGCA_TMU)


def test_the_error_points_at_the_mapping_not_the_contract() -> None:
    """If the ministry's format differs, the fix is a field mapping - not
    relaxing a contract the rest of the pipeline depends on."""
    with pytest.raises(SupplyFormatError, match="map it in this function"):
        parse_supplied_quotes("wrong,columns\n", SupplySource.MOSPI_RO_COLLECTION)


def test_an_empty_file_is_refused() -> None:
    with pytest.raises(SupplyFormatError, match="no header row"):
        parse_supplied_quotes("", SupplySource.DGCA_TMU)


# -- the report ------------------------------------------------------------


def test_rejections_are_itemised_by_row() -> None:
    """"1,204 of 50,000 rejected" with no detail is not something anyone can act
    on. A ministry supplying data is entitled to know which rows and why."""
    bad = GOOD.replace(",INR,", ",USD,")
    report = parse_supplied_quotes(
        csv_of(GOOD, bad, GOOD), SupplySource.MOSPI_RO_COLLECTION
    )

    assert len(report.accepted) == 2
    assert report.rejected[0][0] == 3, "the row number, counting the header as row 1"
    assert "USD" in report.rejected[0][1]


def test_a_mostly_rejected_file_is_marked_unusable() -> None:
    """A file rejecting most rows signals a format mismatch, not dirty data.

    Ingesting the remainder would publish an index built on whichever rows
    happened to parse.
    """
    bad = GOOD.replace(",INR,", ",USD,")
    report = parse_supplied_quotes(
        csv_of(GOOD, bad, bad, bad, bad), SupplySource.MOSPI_RO_COLLECTION
    )

    assert report.accepted, "some rows did parse"
    assert report.rejection_rate == Decimal("0.800")
    assert report.is_usable is False


def test_a_clean_file_is_usable() -> None:
    report = parse_supplied_quotes(csv_of(GOOD, GOOD, GOOD), SupplySource.DGCA_TMU)
    assert report.is_usable is True
    assert report.rejection_rate == Decimal("0.000")


def test_an_entirely_rejected_file_is_not_usable() -> None:
    bad = GOOD.replace(",INR,", ",USD,")
    assert parse_supplied_quotes(csv_of(bad), SupplySource.DGCA_TMU).is_usable is False
