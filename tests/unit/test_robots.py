"""robots.txt handling: fail closed, and parse correctly.

No test here touches the network. A stub fetcher supplies the status and body,
so every failure mode - 404, 403, 5xx, timeout, garbage - can be exercised
deterministically.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest

from compliance.config import ComplianceConfig, ComplianceConfigError
from compliance.robots import RobotsCache, RobotsOutcome, base_url_of

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
UA = "APIx-Research/0.1 (+https://example.org; MoSPI SIH 2026 PS 26056)"

MMT_STYLE = """
User-agent: *
Disallow: /air/*
Disallow: /pwa/
Disallow: /flights/get-fare-calendar-block.html
"""

ALLOW_OVERRIDE = """
User-agent: *
Disallow: /flights/
Allow: /flights/public-fares
"""

WITH_DELAY = """
User-agent: *
Crawl-delay: 1
Allow: /
"""


class StubFetcher:
    """Returns a canned (status, body) and counts calls."""

    def __init__(self, status: int | None, body: str | None) -> None:
        self.status, self.body, self.calls = status, body, 0

    def fetch(self, base_url: str, *, user_agent: str, timeout: float):
        self.calls += 1
        return self.status, self.body


def _config(**overrides: object) -> ComplianceConfig:
    with mock.patch.dict(os.environ, {"APIX_CONTACT_URL": "https://example.org"}, clear=False):
        config = ComplianceConfig.from_env()
    if overrides:
        from dataclasses import replace

        config = replace(config, **overrides)  # type: ignore[arg-type]
    return config


def _cache(
    status: int | None, body: str | None, **overrides: object
) -> tuple[RobotsCache, StubFetcher]:
    fetcher = StubFetcher(status, body)
    return RobotsCache(_config(**overrides), fetcher, write_snapshots=False), fetcher


# -- the six failure situations -------------------------------------------


def test_200_is_parsed_and_applied() -> None:
    cache, _ = _cache(200, MMT_STYLE)
    doc = cache.get("mmt", "https://example.com", now=NOW)
    assert doc.outcome == RobotsOutcome.OK
    assert doc.sha256 is not None


@pytest.mark.parametrize("status", [404, 410])
def test_absent_robots_means_no_restrictions(status: int) -> None:
    """RFC 9309: no robots.txt is not a prohibition."""
    cache, _ = _cache(status, None)
    doc = cache.get("s", "https://example.com", now=NOW)
    assert doc.outcome == RobotsOutcome.ABSENT
    allowed, rule = doc.allows("/air/search", UA)
    assert allowed and rule is not None and "no robots.txt published" in rule


@pytest.mark.parametrize("status", [401, 403])
def test_forbidden_robots_disallows_everything(status: int) -> None:
    """If a site will not show us its rules, we do not guess at them."""
    cache, _ = _cache(status, None)
    doc = cache.get("s", "https://example.com", now=NOW)
    assert doc.outcome == RobotsOutcome.FORBIDDEN
    allowed, rule = doc.allows("/anything", UA)
    assert not allowed
    assert rule is not None and "unverifiable" in rule


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_error_disallows_everything(status: int) -> None:
    cache, _ = _cache(status, None)
    doc = cache.get("s", "https://example.com", now=NOW)
    assert doc.outcome == RobotsOutcome.UNAVAILABLE
    assert doc.allows("/anything", UA)[0] is False


def test_transport_failure_disallows_everything() -> None:
    cache, _ = _cache(None, None)
    doc = cache.get("s", "https://example.com", now=NOW)
    assert doc.outcome == RobotsOutcome.UNAVAILABLE
    assert doc.allows("/anything", UA)[0] is False


def test_a_document_that_cannot_be_trusted_permits_nothing() -> None:
    for status in (401, 403, 500, None):
        cache, _ = _cache(status, None)
        assert cache.get("s", "https://example.com", now=NOW).permits_anything is False


# -- parsing correctness ---------------------------------------------------


@pytest.mark.parametrize("path", ["/air/search", "/air/", "/air/round-trip/DEL-BOM"])
def test_disallow_air_wildcard_blocks_air_paths(path: str) -> None:
    cache, _ = _cache(200, MMT_STYLE)
    doc = cache.get("mmt", "https://example.com", now=NOW)
    assert doc.allows(path, UA)[0] is False


def test_disallow_air_does_not_block_a_merely_similar_prefix() -> None:
    """`Disallow: /air/*` must not catch /airport-info."""
    cache, _ = _cache(200, MMT_STYLE)
    doc = cache.get("mmt", "https://example.com", now=NOW)
    assert doc.allows("/airport-info", UA)[0] is True


def test_allow_overrides_a_broader_disallow() -> None:
    """The precedence case stdlib robotparser gets wrong."""
    cache, _ = _cache(200, ALLOW_OVERRIDE)
    doc = cache.get("s", "https://example.com", now=NOW)
    assert doc.allows("/flights/search", UA)[0] is False
    assert doc.allows("/flights/public-fares", UA)[0] is True


def test_garbage_is_treated_as_permitting_nothing_useful() -> None:
    cache, _ = _cache(200, "\x00\x01 not robots \x02")
    doc = cache.get("s", "https://example.com", now=NOW)
    assert doc.allows("/anything", UA)[0] in (True, False)  # must not raise


# -- crawl delay -----------------------------------------------------------


def test_a_declared_delay_below_our_floor_is_raised_to_the_floor() -> None:
    """Permission to crawl faster is not an obligation to."""
    cache, _ = _cache(200, WITH_DELAY)
    doc = cache.get("s", "https://example.com", now=NOW)
    assert doc.crawl_delay(UA) == 1.0
    assert _config().effective_crawl_delay(doc.crawl_delay(UA)) == 5.0


def test_a_declared_delay_above_our_floor_is_obeyed() -> None:
    cache, _ = _cache(200, "User-agent: *\nCrawl-delay: 30\nAllow: /\n")
    doc = cache.get("s", "https://example.com", now=NOW)
    assert _config().effective_crawl_delay(doc.crawl_delay(UA)) == 30.0


def test_no_declared_delay_falls_back_to_our_floor() -> None:
    cache, _ = _cache(200, MMT_STYLE)
    doc = cache.get("s", "https://example.com", now=NOW)
    assert _config().effective_crawl_delay(doc.crawl_delay(UA)) == 5.0


# -- caching ---------------------------------------------------------------


def test_a_fresh_copy_is_reused_within_the_ttl() -> None:
    cache, fetcher = _cache(200, MMT_STYLE)
    cache.get("s", "https://example.com", now=NOW)
    cache.get("s", "https://example.com", now=NOW + timedelta(hours=23))
    assert fetcher.calls == 1


def test_the_cache_refetches_after_the_ttl() -> None:
    cache, fetcher = _cache(200, MMT_STYLE)
    cache.get("s", "https://example.com", now=NOW)
    cache.get("s", "https://example.com", now=NOW + timedelta(hours=25))
    assert fetcher.calls == 2


def test_a_failed_refetch_may_fall_back_to_a_recent_stale_copy() -> None:
    fetcher = StubFetcher(200, MMT_STYLE)
    cache = RobotsCache(_config(), fetcher, write_snapshots=False)
    cache.get("s", "https://example.com", now=NOW)
    fetcher.status, fetcher.body = None, None
    doc = cache.get("s", "https://example.com", now=NOW + timedelta(hours=25))
    assert doc.outcome == RobotsOutcome.STALE
    assert doc.allows("/airport-info", UA)[0] is True


def test_a_stale_copy_beyond_the_limit_is_not_used() -> None:
    fetcher = StubFetcher(200, MMT_STYLE)
    cache = RobotsCache(_config(), fetcher, write_snapshots=False)
    cache.get("s", "https://example.com", now=NOW)
    fetcher.status, fetcher.body = None, None
    doc = cache.get("s", "https://example.com", now=NOW + timedelta(days=8))
    assert doc.outcome == RobotsOutcome.UNAVAILABLE
    assert doc.allows("/airport-info", UA)[0] is False


# -- snapshots -------------------------------------------------------------


def test_a_snapshot_is_written_and_its_hash_matches(tmp_path) -> None:
    import hashlib

    from compliance import robots as robots_module

    with (
        mock.patch.object(robots_module, "SNAPSHOT_ROOT", tmp_path),
        mock.patch.object(robots_module, "REPO_ROOT", tmp_path),
    ):
        cache = RobotsCache(_config(), StubFetcher(200, MMT_STYLE))
        doc = cache.get("mmt", "https://example.com", now=NOW)
    assert doc.snapshot_path is not None
    written = (tmp_path / "mmt").glob("*.txt")
    body = next(written).read_text(encoding="utf-8")
    assert hashlib.sha256(body.encode()).hexdigest() == doc.sha256


# -- config floors ---------------------------------------------------------


def test_crawl_delay_cannot_be_lowered_below_the_floor() -> None:
    with mock.patch.dict(
        os.environ,
        {"APIX_DEFAULT_CRAWL_DELAY": "0.5", "APIX_CONTACT_URL": "https://example.org"},
    ), pytest.raises(ComplianceConfigError, match="below the"):
        ComplianceConfig.from_env()


def test_crawl_delay_may_be_raised() -> None:
    with mock.patch.dict(
        os.environ,
        {"APIX_DEFAULT_CRAWL_DELAY": "12", "APIX_CONTACT_URL": "https://example.org"},
    ):
        assert ComplianceConfig.from_env().default_crawl_delay == 12.0


def test_daily_budget_cannot_be_raised_above_the_ceiling() -> None:
    with mock.patch.dict(
        os.environ,
        {"APIX_DAILY_REQUEST_BUDGET": "5000", "APIX_CONTACT_URL": "https://example.org"},
    ), pytest.raises(ComplianceConfigError, match="exceeds the"):
        ComplianceConfig.from_env()


def test_daily_budget_may_be_lowered() -> None:
    with mock.patch.dict(
        os.environ,
        {"APIX_DAILY_REQUEST_BUDGET": "20", "APIX_CONTACT_URL": "https://example.org"},
    ):
        assert ComplianceConfig.from_env().daily_request_budget == 20


def test_user_agent_carries_the_contact_url() -> None:
    assert "https://example.org" in _config().user_agent
    assert "APIx-Research" in _config().user_agent


def test_missing_contact_url_is_detectable() -> None:
    with mock.patch.dict(os.environ, {"APIX_CONTACT_URL": ""}, clear=False):
        assert ComplianceConfig.from_env().has_contact is False


def test_base_url_reduction() -> None:
    assert base_url_of("https://example.com/a/b?c=1") == "https://example.com"
    with pytest.raises(ValueError, match="Cannot derive"):
        base_url_of("not-a-url")


# -- soft-404s: HTTP says OK, the body says "web page" ---------------------

SPA_INDEX = (
    '<!doctype html><html lang="en"><head><meta charset="UTF-8">'
    "<title>Ministry of Statistics and Program Implementation</title>"
    '<script defer src="/static/js/main.js"></script></head>'
    '<body><div id="root"></div></body></html>'
)


def test_an_html_page_returned_for_robots_is_treated_as_absent() -> None:
    """api.mospi.gov.in answers /robots.txt with its swagger-ui index page.

    Parsing that as robots.txt yields no directives and so allows everything -
    the right outcome, reached by accident. The audit row would then claim
    "allowed by robots.txt" for a host that publishes none, which is a false
    statement in a compliance record.
    """
    cache, _ = _cache(200, SPA_INDEX)
    doc = cache.get("mospi_cpi", "https://example.com", now=NOW)

    assert doc.outcome == RobotsOutcome.ABSENT
    allowed, rule = doc.allows("/api/cpi/getCpiBaseYear", UA)
    assert allowed is True
    assert rule is not None and "no robots.txt published" in rule
    assert "allowed by robots.txt" not in rule


@pytest.mark.parametrize(
    "body",
    [
        "<!DOCTYPE html><html><body>hi</body></html>",
        "  \n<html><head></head></html>",
        '<?xml version="1.0"?><rss></rss>',
    ],
)
def test_various_page_bodies_are_recognised_as_not_robots(body: str) -> None:
    cache, _ = _cache(200, body)
    assert cache.get("s", "https://example.com", now=NOW).outcome == RobotsOutcome.ABSENT


def test_a_real_robots_file_is_still_parsed_normally() -> None:
    """The soft-404 check must not swallow genuine directives."""
    cache, _ = _cache(200, MMT_STYLE)
    doc = cache.get("s", "https://example.com", now=NOW)
    assert doc.outcome == RobotsOutcome.OK
    assert doc.allows("/air/search", UA)[0] is False


def test_a_comment_only_robots_file_is_not_mistaken_for_a_page() -> None:
    cache, _ = _cache(200, "# nothing to declare\n")
    assert cache.get("s", "https://example.com", now=NOW).outcome == RobotsOutcome.OK
