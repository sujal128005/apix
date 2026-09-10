"""API contract tests.

The assertions worth reading are the ones about *absence*: an endpoint that
cannot honestly serve a number must say so rather than serve one anyway.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps"))


@pytest.fixture(scope="module")
def client() -> TestClient:
    from api.main import app

    return TestClient(app)


def test_health_does_not_need_the_database(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_reports_the_database(client: TestClient) -> None:
    response = client.get("/api/v1/ready")
    assert response.status_code in (200, 503)
    assert "status" in response.json()


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/index/latest",
        "/api/v1/index/routes",
        "/api/v1/quotes",
        "/api/v1/sources",
        "/api/v1/methodology",
    ],
)
def test_every_response_carries_its_methodology(client: TestClient, path: str) -> None:
    """A consumer must be able to tell which method produced a number.

    Putting the version in `meta` means a response is self-describing without
    anyone reading our documentation.
    """
    payload = client.get(path).json()
    assert "meta" in payload, f"{path} has no meta block"
    assert "methodology_version" in payload["meta"]
    assert "provenance" in payload["meta"]
    assert "mode" in payload["meta"]


def test_an_uncomputed_headline_says_so_rather_than_serving_a_number(
    client: TestClient,
) -> None:
    """No index yet is a fact to report, not a zero to invent."""
    data = client.get("/api/v1/index/latest").json()["data"]
    if data["headline"] is None:
        assert data["headline_unavailable_reason"], (
            "a missing headline must be explained, not left silently null"
        )


def test_sources_expose_their_compliance_state(client: TestClient) -> None:
    rows = client.get("/api/v1/sources").json()["data"]
    assert rows, "sources should be seeded"
    for row in rows:
        assert "tier" in row and "enabled" in row and "last_decision" in row


def test_ota_sources_ship_disabled(client: TestClient) -> None:
    """Tier-4 adapters exist and are refused. That is the design, not a gap."""
    rows = {r["code"]: r for r in client.get("/api/v1/sources").json()["data"]}
    for code in ("makemytrip", "yatra", "goibibo", "cleartrip", "ixigo", "easemytrip"):
        assert rows[code]["enabled"] is False, f"{code} must not ship enabled"
        assert rows[code]["tier"] == 4


def test_methodology_names_its_formulae_and_its_assumptions(client: TestClient) -> None:
    data = client.get("/api/v1/methodology").json()["data"]
    assert "Jevons short" in data["elementary_formula"]
    assert "Young" in data["higher_level_formula"]
    assert "Expert Group Report" in data["source"]
    assert len(data["labelled_assumptions"]) >= 4


def test_the_cpi_comparable_bucket_is_flagged(client: TestClient) -> None:
    """T+21 exists because CPI 2024 collects domestic airfare at 21 days."""
    buckets = {b["code"]: b for b in client.get("/api/v1/methodology").json()["data"]["lead_time_buckets"]}
    assert buckets["T21"]["cpi_comparable"] is True
    assert buckets["T21"]["days"] == 21
    assert sum(1 for b in buckets.values() if b["cpi_comparable"]) == 1


def test_the_dashboard_is_served(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "APIx" in response.text
    assert "Ministry of Statistics" in response.text


def test_openapi_is_generated(client: TestClient) -> None:
    spec = client.get("/api/v1/openapi.json").json()
    assert spec["info"]["title"].startswith("APIx")
    assert "/api/v1/index/latest" in spec["paths"]


def test_backtest_reports_a_shortfall_rather_than_inventing_metrics(
    client: TestClient,
) -> None:
    """A validation endpoint that always returns a number is decoration.

    APIx began after the published CPI series ends, so nothing aligns. The
    endpoint must say so and withhold metrics rather than compute an MAE over
    an overlap that does not exist.
    """
    response = client.get("/api/v1/backtest")
    if response.status_code == 404:
        pytest.skip("benchmark file not fetched in this environment")

    data = response.json()["data"]
    assert data.get("limitation")
    if not data["sufficient"]:
        assert data["metrics"] is None, "no metrics without sufficient overlap"


def test_backtest_states_the_ps_requirement_gap(client: TestClient) -> None:
    """The PS assumes a DGCA series that research could not find.

    Stating that in the response itself means the gap travels with the data,
    rather than living only in a document nobody opens.
    """
    response = client.get("/api/v1/backtest")
    if response.status_code == 404:
        pytest.skip("benchmark file not fetched in this environment")
    note = response.json()["data"]["ps_requirement_note"]
    assert "DGCA" in note and "no such public series" in note.lower()


# -- route explorer and lead-time profile (Phases 13-14) -------------------


def test_a_route_weight_is_never_returned_without_its_evidence(
    client: TestClient,
) -> None:
    """A weight and its provenance travel together or not at all.

    An unlabelled weight looks identical to a sourced one. Ours are currently
    rung 4 - equal weights, not derived from traffic - and the response has to
    say so wherever the number appears.
    """
    response = client.get("/api/v1/routes/DEL-BOM")
    if response.status_code == 404:
        pytest.skip("route not seeded in this environment")

    weight = response.json()["data"]["weight"]
    if weight is not None:
        assert weight["evidence_rung"] in (1, 2, 3, 4)
        assert weight["evidence_ref"], "a weight must cite where it came from"
        assert weight["rung_meaning"], "the rung must be explained, not just numbered"
        assert isinstance(weight["is_proxy"], bool)


def test_an_unknown_route_is_a_404_not_an_empty_series(client: TestClient) -> None:
    assert client.get("/api/v1/routes/XXX-YYY").status_code == 404


def test_the_lead_time_profile_flags_exactly_one_cpi_comparable_bucket(
    client: TestClient,
) -> None:
    """T+21 and only T+21. It is the horizon CPI 2024 collects domestic airfare at."""
    buckets = client.get("/api/v1/lead-time-profile").json()["data"]["buckets"]
    if not buckets:
        pytest.skip("no observations collected in this environment")

    flagged = [b for b in buckets if b["cpi_comparable"]]
    assert len(flagged) == 1
    assert flagged[0]["bucket"] == "T21"
    assert flagged[0]["days"] == 21


def test_the_lead_time_profile_is_ordered_by_horizon(client: TestClient) -> None:
    buckets = client.get("/api/v1/lead-time-profile").json()["data"]["buckets"]
    if not buckets:
        pytest.skip("no observations collected in this environment")
    assert [b["days"] for b in buckets] == sorted(b["days"] for b in buckets)


def test_fares_fall_as_the_booking_horizon_lengthens(client: TestClient) -> None:
    """The finding the whole problem statement rests on.

    If booking further ahead were not cheaper, a lead-time-aware index would
    have nothing to add over a single monthly price collection.
    """
    buckets = {b["bucket"]: b for b in client.get("/api/v1/lead-time-profile").json()["data"]["buckets"]}
    if not buckets:
        pytest.skip("no observations collected in this environment")
    assert buckets["T1"]["mean_fare"] > buckets["T45"]["mean_fare"]


def test_the_profile_is_never_called_an_elasticity(client: TestClient) -> None:
    """No causal elasticity is estimated, so the word is not used.

    The problem statement says "lead-time elasticity curves". Using that term
    for a descriptive price curve would overclaim, and it is the kind of
    overclaim a methodologist notices immediately.
    """
    for path in ("/lead-time", "/api/v1/lead-time-profile"):
        assert "elasticity" not in client.get(path).text.lower().replace(
            "not an elasticity", ""
        ).replace("calling it elasticity", "").replace("causal elasticity", "")


@pytest.mark.parametrize("path", ["/", "/routes", "/lead-time"])
def test_every_page_is_served(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert "APIx" in response.text


@pytest.mark.parametrize("asset", ["/static/style.css", "/static/apix.js"])
def test_shared_assets_are_served_locally(client: TestClient, asset: str) -> None:
    """No CDN. A demo must not be able to fail because a stylesheet didn't load."""
    assert client.get(asset).status_code == 200


def test_no_page_loads_a_remote_asset(client: TestClient) -> None:
    """Every stylesheet, script and font is served from this process.

    Checked against actual `src`/`href` values rather than by searching for the
    word "CDN" - the first version of this test failed on a comment explaining
    why we avoid them, which punishes writing the reasoning down.
    """
    import re

    for path in ("/", "/routes", "/lead-time"):
        html = client.get(path).text
        remote = re.findall(r'(?:src|href)\s*=\s*"(https?://[^"]+)"', html)
        assert not remote, f"{path} loads remote assets: {remote}"

        for asset in re.findall(r'(?:src|href)\s*=\s*"(/static/[^"]+)"', html):
            assert client.get(asset).status_code == 200, f"{asset} is missing"
