"""The Akasa adapter — the first source in this project that collects a real fare.

The fixture is a real response, captured on 13 September 2026 and frozen. Most
of these tests are about what the adapter refuses to include.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from collector.adapter import AdapterResponse, CollectionSpec
from collector.adapters import AkasaAdapter

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "adapters" / "akasa_del_bom.json"
)


def spec(origin: str = "DEL", destination: str = "BOM") -> CollectionSpec:
    return CollectionSpec(
        source_id=uuid4(), source_code="akasa_ibe", route_id=uuid4(),
        route_code=f"{origin}-{destination}", origin=origin, destination=destination,
        bucket_id=uuid4(), bucket_code="T7", lead_time_days=7,
        travel_date=date(2026, 9, 19), collected_date=date(2026, 9, 12),
    )


def response() -> AdapterResponse:
    return AdapterResponse(
        body=FIXTURE.read_text(encoding="utf-8"),
        http_status=200,
        fetched_at=datetime.now(UTC),
    )


def parsed(origin: str = "DEL") -> list[dict[str, object]]:
    adapter = AkasaAdapter()
    adapter.build_request(spec(origin))
    return [adapter.normalize(q) for q in adapter.parse(response())]


# -- the metropolitan-area trap --------------------------------------------


def test_a_neighbouring_airport_is_not_pooled_into_the_route() -> None:
    """The failure this adapter was nearly written with.

    Akasa's site sends `searchOriginMacs: true`, which expands DEL to the Delhi
    metropolitan area and returns departures from DXN — Noida International —
    alongside Delhi's. The captured fixture contains both. Pooled into a DEL-BOM
    index those are a different airport with a different catchment, and the
    index would measure two products as one.
    """
    origins = {f["origin"] for f in parsed("DEL")}
    assert origins == {"DEL"}, f"a non-requested airport leaked in: {origins}"


def test_the_fixture_really_does_contain_the_other_airport() -> None:
    """Otherwise the test above passes for the wrong reason."""
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    markets = raw["data"]["results"][0]["trips"][0]["journeysAvailableByMarket"]
    assert any(m["key"].startswith("DXN") for m in markets)


def test_the_request_also_disables_metropolitan_expansion() -> None:
    """Belt and braces: the filter above catches what the request should prevent.

    Relying on the filter alone would fetch inventory we then discard; relying
    on the request alone trusts a parameter we cannot verify was honoured.
    """
    adapter = AkasaAdapter()
    payload = json.loads(adapter.build_request(spec()).body or "{}")
    stations = payload["criteria"][0]["stations"]

    assert stations["searchOriginMacs"] is False
    assert stations["searchDestinationMacs"] is False
    assert stations["originStationCodes"] == ["DEL"]


# -- constant quality ------------------------------------------------------


def test_only_non_stop_journeys_are_collected() -> None:
    """A connection is a different product from a direct flight."""
    adapter = AkasaAdapter()
    payload = json.loads(adapter.build_request(spec()).body or "{}")
    assert payload["criteria"][0]["filters"]["maxConnections"] == 0

    for fields in parsed():
        assert fields["stops"] == 0


def test_every_quote_identifies_its_flight() -> None:
    """Without a flight number and departure time there is no product to match."""
    for fields in parsed():
        assert fields["carrier"] == "QP"
        assert str(fields["flight_no"]).startswith("QP")
        assert fields["departure_at"]
        assert fields["fare_brand"]


# -- fare decomposition ----------------------------------------------------


def test_the_fare_is_decomposed_as_the_problem_statement_requires() -> None:
    """PS 26056 asks for base fare, taxes, UDF and other charges separately.

    Akasa itemises all of them, so nothing here is estimated.
    """
    fields = parsed()[0]
    for component in ("base_fare", "taxes", "udf", "convenience_fee"):
        assert fields.get(component) is not None, f"{component} missing"


def test_the_components_sum_to_the_total_exactly() -> None:
    """If they did not, one of them is being dropped."""
    for fields in parsed():
        total = Decimal(str(fields["total_fare"]))
        parts = sum(
            Decimal(str(fields[c]))
            for c in ("base_fare", "taxes", "udf", "convenience_fee")
            if fields.get(c) is not None
        )
        assert parts == total, f"components {parts} do not sum to total {total}"


def test_the_user_development_fee_is_separated_from_other_charges() -> None:
    """Named explicitly by PS 26056, and reported separately from airport levies."""
    fields = parsed()[0]
    assert Decimal(str(fields["udf"])) > 0
    assert Decimal(str(fields["convenience_fee"])) > 0
    assert fields["udf"] != fields["convenience_fee"]


def test_money_is_never_rendered_as_a_float() -> None:
    for fields in parsed():
        for component in ("total_fare", "base_fare", "taxes", "udf"):
            value = fields.get(component)
            if value is not None:
                assert isinstance(value, str), f"{component} is {type(value).__name__}"


def test_fares_are_in_rupees() -> None:
    assert all(f["currency"] == "INR" for f in parsed())


# -- the contract ----------------------------------------------------------


def test_the_adapter_declares_it_is_not_fit_for_an_official_statistic() -> None:
    """The booking-engine host serves no robots.txt, which the gate reads as
    unrestricted. That is correct and is not the same as permission: absence on
    a backend host means nobody contemplated crawling it.
    """
    diagnostics = AkasaAdapter().diagnostics()
    assert diagnostics["fit_for_official_statistic"] is False
    assert "not as permission granted" in diagnostics["robots_txt"]


def test_the_source_must_be_the_booking_engine_host() -> None:
    """Fares are not served from the marketing site."""
    adapter = AkasaAdapter()
    assert adapter.validate_source(
        source_code="akasa_ibe", base_url="https://prod-bl.qp.akasaair.com"
    ).ok

    wrong = adapter.validate_source(
        source_code="akasa_ibe", base_url="https://www.akasaair.com"
    )
    assert wrong.ok is False
    assert any("booking engine" in p for p in wrong.problems)


def test_the_gate_evaluates_the_path_that_is_fetched() -> None:
    """An adapter that evaluates one path and fetches another defeats the gate."""
    from collector.adapters.akasa import AVAILABILITY_PATH

    assert AkasaAdapter().build_request(spec()).path == AVAILABILITY_PATH


def test_an_empty_response_yields_nothing_rather_than_raising() -> None:
    adapter = AkasaAdapter()
    adapter.build_request(spec())
    empty = AdapterResponse(
        body='{"data":{"faresAvailable":[],"results":[]}}',
        http_status=200,
        fetched_at=datetime.now(UTC),
    )
    assert adapter.parse(empty) == []


@pytest.mark.parametrize("origin", ["BOM", "BLR"])
def test_a_response_for_a_different_route_is_rejected_entirely(origin: str) -> None:
    """If the response does not match what was asked for, nothing is collected."""
    assert parsed(origin) == []
