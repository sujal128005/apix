"""Source adapters: what they parse, and what they refuse to do."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from collector.adapter import AdapterResponse, CollectionSpec
from collector.adapters import AmadeusAdapter, OtaAdapter, TariffSheetAdapter
from collector.adapters.ota import OtaExecutionRefusedError, OtaParserNotValidatedError
from collector.adapters.tariff_sheet import TariffSheetNotLocatedError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "adapters"


def response(name: str) -> AdapterResponse:
    return AdapterResponse(
        body=(FIXTURES / name).read_text(encoding="utf-8"),
        http_status=200,
        fetched_at=datetime.now(UTC),
    )


def spec(source_code: str = "amadeus") -> CollectionSpec:
    return CollectionSpec(
        source_id=uuid4(), source_code=source_code,
        route_id=uuid4(), route_code="DEL-BOM", origin="DEL", destination="BOM",
        bucket_id=uuid4(), bucket_code="T7", lead_time_days=7,
        travel_date=date(2026, 9, 15), collected_date=date(2026, 9, 8),
    )


# -- Amadeus ---------------------------------------------------------------


def test_amadeus_parses_direct_offers() -> None:
    quotes = AmadeusAdapter("token").parse(response("amadeus_del_bom.json"))
    assert len(quotes) == 2
    assert {q.payload["carrierCode"] for q in quotes} == {"6E", "AI"}


def test_amadeus_skips_connecting_itineraries() -> None:
    """A one-stop flight is a different product from a direct one.

    Folding them together would let a product substitution register as a price
    change - the failure mode matched-pair construction exists to prevent. The
    fixture's cheapest offer is the one-stop, so a parser that kept it would
    also depress the index.
    """
    quotes = AmadeusAdapter("token").parse(response("amadeus_del_bom.json"))
    assert all(q.payload["carrierCode"] != "SG" for q in quotes)


def test_amadeus_derives_taxes_from_total_base_and_fees() -> None:
    """5499 total - 4200 base - 149 ticketing fee = 1150 tax."""
    adapter = AmadeusAdapter("token")
    quote = adapter.parse(response("amadeus_del_bom.json"))[0]
    fields = adapter.normalize(quote)
    assert fields["total_fare"] == "5499.00"
    assert fields["base_fare"] == "4200.00"
    assert fields["taxes"] == "1150.00"
    assert fields["convenience_fee"] == "149.00"


def test_amadeus_omits_components_it_cannot_derive() -> None:
    """Missing is better than guessed; the pipeline marks such quotes PARTIAL."""
    from collector.adapter import ParsedQuote

    adapter = AmadeusAdapter("token")
    fields = adapter.normalize(
        ParsedQuote(ordinal=0, payload={"carrierCode": "6E", "number": "1", "total": "5000"})
    )
    assert "base_fare" not in fields
    assert "taxes" not in fields


def test_amadeus_requests_the_constant_quality_scope() -> None:
    """Economy, one-way, direct, one adult, INR (PA-2)."""
    params = AmadeusAdapter("token").build_request(spec()).params
    assert params["travelClass"] == "ECONOMY"
    assert params["nonStop"] == "true"
    assert params["adults"] == "1"
    assert params["currencyCode"] == "INR"


def test_amadeus_refuses_to_run_without_a_token() -> None:
    result = AmadeusAdapter(None).validate_source(source_code="amadeus", base_url="https://x")
    assert result.ok is False
    assert any("access token" in p for p in result.problems)


def test_amadeus_reports_its_coverage_as_unverified() -> None:
    """O-3 is open. The adapter must not imply carrier coverage it has not seen."""
    diagnostics = AmadeusAdapter("token").diagnostics()
    assert diagnostics["coverage_verified"] is False
    assert "O-3" in diagnostics["coverage_note"]


# -- tariff sheets ---------------------------------------------------------


def test_tariff_sheet_parses_route_and_fare_category() -> None:
    adapter = TariffSheetAdapter({"indigo_tariff": "/tariff"})
    quotes = adapter.parse(response("tariff_sheet_sample.html"))
    sectors = {q.payload["sector"] for q in quotes}
    assert sectors == {"DEL-BOM", "DEL-BLR", "BOM-BLR"}


def test_a_rupee_entity_does_not_corrupt_the_amount() -> None:
    """&#8377; leaves the digits 8377 behind if only tags are stripped.

    "&#8377; 4,500" would parse as 83,774,500 - four orders of magnitude wrong,
    and wrong in a way that still looks like a number.
    """
    adapter = TariffSheetAdapter({"indigo_tariff": "/tariff"})
    quotes = adapter.parse(response("tariff_sheet_sample.html"))
    saver = next(
        q for q in quotes
        if q.payload["sector"] == "DEL-BOM" and q.payload["fare_category"] == "Saver"
    )
    assert saver.payload["declared_fare"] == "4500.00"


def test_implausible_amounts_are_rejected_rather_than_passed_on() -> None:
    """A mangled cell yielding a number is worse than one yielding nothing."""
    from collector.adapters.tariff_sheet import _amount

    assert _amount("&#8377; 4,500") is not None
    assert _amount("12") is None            # a column index, not a fare
    assert _amount("N/A") is None
    assert _amount("") is None
    assert _amount("99999999999") is None   # beyond any domestic tariff band


def test_a_tariff_record_is_never_a_transacted_price() -> None:
    """A declared band is a ceiling an airline filed, not a fare anyone paid."""
    adapter = TariffSheetAdapter({"indigo_tariff": "/tariff"})
    quote = adapter.parse(response("tariff_sheet_sample.html"))[0]
    fields = adapter.normalize(quote)
    assert fields["is_transacted_price"] is False
    assert "Rule 135(2)" in fields["basis"]


def test_a_missing_tariff_path_raises_rather_than_guessing() -> None:
    """A guessed URL either 404s or fetches something else and parses it."""
    with pytest.raises(TariffSheetNotLocatedError, match="O-4"):
        TariffSheetAdapter().build_request(spec("indigo_tariff"))


def test_tariff_paths_ship_empty() -> None:
    """O-4 is unresolved. An invented path is worse than a missing one."""
    assert TariffSheetAdapter.TARIFF_PATHS == {}


# -- OTAs: built, never run ------------------------------------------------


@pytest.mark.parametrize(
    "code", ["makemytrip", "yatra", "easemytrip", "cleartrip", "ixigo", "goibibo"]
)
def test_every_ota_refuses_validation_for_collection(code: str) -> None:
    result = OtaAdapter(code).validate_source(source_code=code, base_url="https://x")
    assert result.ok is False
    assert any("Tier 4" in p for p in result.problems)


def test_an_ota_refuses_to_execute_even_holding_a_valid_token() -> None:
    """A token proves the gate ran, not that the source permits collection."""
    from datetime import timedelta

    from compliance.token import mint

    adapter = OtaAdapter("makemytrip")
    request = adapter.build_request(spec("makemytrip"))
    now = datetime.now(UTC)
    token = mint(
        decision_id=uuid4(), source_id=uuid4(), path=request.path, user_agent="ua",
        issued_at=now, expires_at=now + timedelta(seconds=300), crawl_delay=5.0,
    )
    with pytest.raises(OtaExecutionRefusedError, match="must not be fetched"):
        adapter.execute(request, token, base_url="https://x")


def test_an_ota_parser_refuses_rather_than_returning_an_empty_list() -> None:
    """An empty list is indistinguishable from "no flights today"."""
    empty = AdapterResponse(body="<html></html>", http_status=200, fetched_at=datetime.now(UTC))
    with pytest.raises(OtaParserNotValidatedError, match="lawfully obtained"):
        OtaAdapter("makemytrip").parse(empty)


def test_an_ota_builds_the_real_path_it_would_fetch() -> None:
    """The gate must evaluate the actual request, not a placeholder.

    Otherwise the refusal in the audit trail is about a different request from
    the one that was declined.
    """
    assert OtaAdapter("makemytrip").build_request(spec("makemytrip")).path == "/air/search"


def test_a_blocked_ota_reports_healthy() -> None:
    """A correctly-blocked source is not a broken one.

    Marking these unhealthy would fill the operations console with red for a
    system behaving as designed, and a console that is always red is unread.
    """
    report = OtaAdapter("makemytrip").health_check()
    assert report.healthy is True
    assert "execution withheld" in report.detail


def test_an_ota_declares_that_it_does_not_execute() -> None:
    diagnostics = OtaAdapter("goibibo").diagnostics()
    assert diagnostics["executes"] is False
    assert diagnostics["parser_validated"] is False
    assert diagnostics["tier"] == 4
