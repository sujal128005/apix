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
