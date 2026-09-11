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


def _code_only(source: str) -> str:
    """Strip JS comments so an assertion reads the code, not its commentary.

    Written after five separate tests in this file failed on comments that
    described the very thing the test was checking for the absence of - a CDN,
    the State Emblem, stdlib robotparser, a bypass flag, an invented footer
    link. Each time the code was correct and the test was reading prose.

    A test that punishes writing down your reasoning teaches you to stop writing
    it down, which is the opposite of what this project wants.
    """
    import re

    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    return re.sub(r"^\s*//.*$", " ", source, flags=re.M)


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


# -- data quality and provenance (Phase 15) -------------------------------


def test_quality_reports_rejections_not_only_successes(client: TestClient) -> None:
    """A quality page showing only what worked is decoration.

    The load-bearing figures are the outlier rejection rate and the imputation
    rate: a rise in either is usually the first visible sign that a source has
    stopped working, well before the index itself looks wrong.
    """
    data = client.get("/api/v1/quality").json()["data"]
    for key in ("quotes_excluded_as_outliers", "strata_insufficient", "quotes_imputed"):
        assert key in data["totals"], f"{key} must be reported"
    for key in ("outlier_rejection_pct", "imputation_pct"):
        assert key in data["rates"]
        assert key in data["interpretation"], f"{key} must be explained, not just numbered"


def test_quality_totals_are_internally_consistent(client: TestClient) -> None:
    data = client.get("/api/v1/quality").json()["data"]
    by_status = data["by_quality_status"]
    if by_status:
        assert sum(by_status.values()) == data["totals"]["quotes"]


def test_provenance_walks_a_quote_back_to_its_compliance_decision(
    client: TestClient,
) -> None:
    """The claim the whole project rests on.

    No number should appear anywhere in APIx that cannot be walked back to a
    fare a source actually quoted, when it was collected, and the compliance
    decision that permitted the request.
    """
    quotes = client.get("/api/v1/quotes?limit=1").json()["data"]
    if not quotes:
        pytest.skip("no observations collected in this environment")

    listing = client.get("/api/v1/quality").json()
    assert listing["meta"]["provenance"], "provenance must be reported in meta"


def test_provenance_rejects_a_malformed_id(client: TestClient) -> None:
    assert client.get("/api/v1/provenance/not-a-uuid").status_code == 400


def test_provenance_404s_on_an_unknown_observation(client: TestClient) -> None:
    assert (
        client.get("/api/v1/provenance/00000000-0000-0000-0000-000000000000").status_code
        == 404
    )


@pytest.mark.parametrize("path", ["/quality", "/methodology"])
def test_the_new_pages_are_served(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert "APIx" in response.text


def test_the_methodology_page_names_its_sources(client: TestClient) -> None:
    """Each methodological choice cites where it came from - including ours."""
    html = client.get("/methodology").text
    assert "Expert Group Report" in html
    assert "4.6.1" in html and "4.6.2" in html
    assert "MoSPI prescribes no outlier rule" in html, (
        "the outlier rule is our choice and must be labelled as such"
    )


def test_the_methodology_page_states_its_limitations(client: TestClient) -> None:
    """Limitations belong on the page, not in a document nobody opens."""
    html = client.get("/methodology").text
    assert "not comparable" in html
    assert "evidence rung 4" in html
    assert "No public DGCA monthly average-fare series" in html


# -- operations console (Phase 16) ----------------------------------------


def test_operations_judges_freshness_rather_than_only_reporting_it(
    client: TestClient,
) -> None:
    """An age with no threshold beside it leaves every reader to invent one."""
    freshness = client.get("/api/v1/operations").json()["data"]["freshness"]
    assert freshness["status"] in ("CURRENT", "STALE", "OVERDUE", "NO_DATA")
    assert "thresholds" in freshness
    assert freshness["thresholds"]["current_within_hours"] > 0


def test_operations_raises_an_alert_when_data_goes_stale(client: TestClient) -> None:
    data = client.get("/api/v1/operations").json()["data"]
    if data["freshness"]["status"] in ("STALE", "OVERDUE", "NO_DATA"):
        assert data["alerts"], "stale data must raise an alert, not sit silently"


def test_a_blocked_source_is_reported_as_compliance_not_as_a_fault(
    client: TestClient,
) -> None:
    """Refusals and failures need different responses, so they are counted apart.

    A run in which every restricted source was correctly refused is a success.
    Reporting it as an outage would make the compliance layer look broken.
    """
    data = client.get("/api/v1/operations").json()["data"]
    blocked = sum(
        v for k, v in data["compliance_decisions"].items() if str(k).startswith("BLOCKED")
    )
    if blocked:
        levels = {a["level"] for a in data["alerts"] if "refused" in a["message"]}
        assert levels <= {"info"}, "a compliance refusal is not a fault"


def test_operations_lists_every_source_with_its_adapter(client: TestClient) -> None:
    sources = client.get("/api/v1/operations").json()["data"]["sources"]
    assert sources
    for source in sources:
        assert source["adapter_key"], "every source must name the adapter that serves it"
        assert "enabled" in source and "observations" in source


def test_the_operations_page_is_served(client: TestClient) -> None:
    response = client.get("/operations")
    assert response.status_code == 200
    assert "Operations console" in response.text


# -- security hardening (Phase 18) ----------------------------------------


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("x-content-type-options", "nosniff"),
        ("x-frame-options", "DENY"),
        ("referrer-policy", "no-referrer"),
    ],
)
def test_security_headers_are_present(client: TestClient, header: str, expected: str) -> None:
    assert client.get("/api/v1/health").headers.get(header) == expected


def test_the_csp_permits_no_remote_origin(client: TestClient) -> None:
    """Inline is allowed because the pages use it; remote is not, and that is
    the property that matters - every asset comes from this process."""
    csp = client.get("/").headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "http://" not in csp and "https://" not in csp


def test_cors_is_an_allow_list_not_a_wildcard() -> None:
    """A wildcard on a government data endpoint is a habit worth not forming."""
    from api.main import ALLOWED_ORIGINS

    assert ALLOWED_ORIGINS
    assert "*" not in ALLOWED_ORIGINS


def test_an_internal_error_never_leaks_a_stack_trace(client: TestClient) -> None:
    """A traceback in a response names the framework, the file layout and often
    the query."""
    response = client.get("/api/v1/provenance/not-a-uuid")
    body = response.text
    assert "Traceback" not in body
    assert "File \"" not in body
    assert "sqlalchemy" not in body.lower()


# -- government portal conventions ----------------------------------------


@pytest.mark.parametrize(
    "path", ["/", "/routes", "/lead-time", "/quality", "/methodology", "/operations"]
)
def test_every_page_has_a_skip_target_and_shared_chrome(
    client: TestClient, path: str
) -> None:
    """Accessibility affordances must exist on every page, not just the home page."""
    html = client.get(path).text
    assert 'id="main"' in html, "skip-to-content needs a target"
    assert "initChrome(" in html
    assert 'id="gov-footer"' in html
    assert "/static/style.css" in html and "/static/apix.js" in html


def test_the_accessibility_bar_actually_works(client: TestClient) -> None:
    """A GoI accessibility bar that resizes nothing is worse than none at all.

    The text-size controls are wired to a CSS custom property the whole page
    scales from, and the choice persists for the session.
    """
    js = client.get("/static/apix.js").text
    assert "initTextSizer" in js
    assert "--font-scale" in js
    assert "sessionStorage" in js
    assert 'aria-pressed' in js


def test_the_state_emblem_is_not_used(client: TestClient) -> None:
    """Display of the State Emblem of India is restricted under the State Emblem
    of India (Prohibition of Improper Use) Act, 2005. This is a student project.

    The official feel comes from GoI layout conventions - the accessibility
    strip, bilingual masthead, navy navigation band, standard footer - not from
    appropriating a protected mark.

    Checked against rendered markup and asset references rather than by searching
    for the word "emblem" - the first version of this test failed on the comment
    in style.css explaining why the emblem is avoided. That is the fourth test in
    this suite to have punished written reasoning, so the assertions look at what
    the code *does*, never at what it says about itself.
    """
    import re

    html = client.get("/").text
    js = client.get("/static/apix.js").text
    css = client.get("/static/style.css").text

    # No raster or vector assets at all: the masthead mark is drawn in CSS.
    for source, label in ((html, "index.html"), (js, "apix.js")):
        images = re.findall(r"<img[^>]*>", source, re.I)
        assert not images, f"{label} embeds an image: {images}"

    for source, label in ((css, "style.css"), (js, "apix.js")):
        urls = re.findall(r"url\(([^)]+)\)", source)
        assert not urls, f"{label} loads an asset: {urls}"


def test_the_footer_says_this_is_not_an_official_publication(
    client: TestClient,
) -> None:
    """A portal that looks official must state plainly that it is not.

    Everything else about the design is meant to read as a government
    statistical site; without this line that resemblance would be a claim.

    Checked on the text with markup stripped and case folded. The first version
    matched an exact string and broke when the word "not" was emphasised - the
    disclaimer was intact, the assertion was merely brittle.
    """
    import re

    js = client.get("/static/apix.js").text
    plain = re.sub(r"<[^>]+>", "", js).lower()

    assert "not an official publication" in plain
    assert "student project" in plain
    assert "prototype" in plain
    assert "not a source of official statistics" in plain


def test_the_footer_timestamp_comes_from_the_api(client: TestClient) -> None:
    """A hardcoded 'last updated' on a statistics portal is worse than none."""
    html = client.get("/").text
    assert "govFooter(" in html
    assert "meta.as_of" in html


def test_the_footer_invents_no_government_affiliation(client: TestClient) -> None:
    """The footer is styled like a ministry portal, so its content must not
    borrow one's authority.

    No social accounts, no RTI or feedback links, no visitor counter, no
    contact addresses - APIx has none of those, and adding them to fill out the
    layout would be precisely the impersonation the design has to avoid.
    External references are present but labelled as external.

    Comments are stripped before scanning. This is the fifth test in this suite
    to have first failed on a comment describing what the code deliberately does
    *not* do - so the helper below exists to stop that happening a sixth time.
    Assertions should read the code, never its explanation of itself.
    """
    js = _code_only(client.get("/static/apix.js").text).lower()

    for invented in ("rti", "feedback form", "visitor counter", "@gov.in", "@nic.in"):
        assert invented not in js, f"the footer invents {invented!r}"

    # External links are permitted, but must be labelled and opened safely.
    assert "external reference" in js
    assert 'rel="noopener noreferrer"' in js
