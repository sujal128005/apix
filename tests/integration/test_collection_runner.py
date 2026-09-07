"""The runner, end to end against a real PostgreSQL.

Covers the property the whole phase exists for: an adapter is never executed for
a request the gate refused, and no code path reaches the network without a token.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from unittest import mock
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from collector.adapter import CollectionSpec
from collector.mock_adapter import MockAdapter, MockBehaviour
from collector.retry import RetryPolicy
from collector.runner import CollectionRunner
from compliance.config import ComplianceConfig
from compliance.gate import ComplianceGate
from compliance.robots import RobotsCache
from schemas.enums import ComplianceDecisionCode, JobStatus, ReviewVerdict
from schemas.models.collection import CollectionJob, CollectionRequest, RawQuote, RawResponse
from schemas.models.reference import Source, SourceReview
from tests.support.builders import SeedRefs

NOW = datetime(2026, 9, 7, 6, 0, tzinfo=UTC)
COLLECTED = date(2026, 9, 7)

PERMISSIVE = "User-agent: *\nAllow: /\n"
RESTRICTIVE = "User-agent: *\nDisallow: /search/*\n"


class StubFetcher:
    def __init__(self, body: str = PERMISSIVE) -> None:
        self.body = body

    def fetch(self, base_url: str, *, user_agent: str, timeout: float):
        return 200, self.body


def _advancing_clock(start: datetime = NOW, step_seconds: int = 30):
    """A clock that moves 30s per call, so crawl-delay behaves as it would live."""
    state = {"t": start}

    def clock() -> datetime:
        current = state["t"]
        state["t"] = current + timedelta(seconds=step_seconds)
        return current

    return clock


def _runner(
    adapter: MockAdapter,
    *,
    robots_body: str = PERMISSIVE,
    retry: RetryPolicy | None = None,
    clock=None,
) -> CollectionRunner:
    with mock.patch.dict(os.environ, {"APIX_CONTACT_URL": "https://example.org"}, clear=False):
        config = ComplianceConfig.from_env()
    gate = ComplianceGate(config, RobotsCache(config, StubFetcher(robots_body), write_snapshots=False))
    return CollectionRunner(
        gate,
        {"mock_v1": adapter},
        retry=retry or RetryPolicy(max_attempts=3, base_delay_seconds=0.0, multiplier=1.0),
        sleep=lambda _s: None,
        clock=clock or _advancing_clock(),
    )


def _spec(refs: SeedRefs, route: str = "DEL-BOM", bucket: str = "T7") -> CollectionSpec:
    origin, destination = route.split("-")
    return CollectionSpec(
        source_id=refs.sources["indigo_web"],
        source_code="indigo_web",
        route_id=refs.routes[route],
        route_code=route,
        origin=origin,
        destination=destination,
        bucket_id=refs.buckets[bucket],
        bucket_code=bucket,
        lead_time_days=refs.bucket_days[bucket],
        travel_date=COLLECTED + timedelta(days=refs.bucket_days[bucket]),
        collected_date=COLLECTED,
    )


@pytest.fixture
def ready_source(app_session: Session, refs: SeedRefs) -> UUID:
    source_id = refs.sources["indigo_web"]
    source = app_session.get(Source, source_id)
    assert source is not None
    source.enabled = True
    source.base_url = "https://example.com"
    source.adapter_key = "mock_v1"
    app_session.add(
        SourceReview(
            source_id=source_id,
            reviewer="architect",
            reviewed_at=NOW,
            robots_decision="Allow: /",
            verdict=ReviewVerdict.APPROVED,
        )
    )
    app_session.flush()
    return source_id


# -- the happy path --------------------------------------------------------


def test_a_permitted_search_is_collected_and_stored(
    app_session: Session, refs: SeedRefs, ready_source: UUID
) -> None:
    adapter = MockAdapter(quote_count=3)
    result = _runner(adapter).run(app_session, [_spec(refs)], now=NOW)

    assert result.collected == 1
    assert result.quotes == 3
    assert result.status == JobStatus.SUCCESS

    outcome = result.outcomes[0]
    raw = app_session.get(RawResponse, outcome.raw_response_id)
    assert raw is not None and raw.http_status == 200
    assert len(raw.sha256) == 64

    quotes = app_session.execute(
        sa.select(RawQuote).where(RawQuote.raw_response_id == raw.id)
    ).scalars().all()
    assert len(quotes) == 3
    assert quotes[0].payload["carrier"] == "6E"
    assert quotes[0].payload["total_fare"] == "5000.00"


def test_the_adapter_receives_the_token_for_the_path_the_gate_evaluated(
    app_session: Session, refs: SeedRefs, ready_source: UUID
) -> None:
    adapter = MockAdapter()
    _runner(adapter).run(app_session, [_spec(refs)], now=NOW)

    assert len(adapter.tokens_seen) == 1
    token = adapter.tokens_seen[0]
    assert token.path == adapter.executed_paths[0] == "/search/DEL-BOM"
    assert token.source_id == ready_source


def test_job_counters_and_lineage_are_recorded(
    app_session: Session, refs: SeedRefs, ready_source: UUID
) -> None:
    result = _runner(MockAdapter()).run(app_session, [_spec(refs)], now=NOW)

    job = app_session.get(CollectionJob, result.job_id)
    assert job is not None
    assert job.requests_total == 1
    assert job.requests_ok == 1
    assert job.requests_blocked == 0
    assert job.status == JobStatus.SUCCESS
    assert job.finished_at is not None

    request = app_session.get(CollectionRequest, result.outcomes[0].request_id)
    assert request is not None and request.job_id == job.id


# -- the property this phase exists for ------------------------------------


def test_a_blocked_search_never_reaches_the_adapter(
    app_session: Session, refs: SeedRefs, ready_source: UUID
) -> None:
    """The whole point: robots said no, so no fetch happened at all."""
    adapter = MockAdapter()
    result = _runner(adapter, robots_body=RESTRICTIVE).run(app_session, [_spec(refs)], now=NOW)

    assert result.collected == 0
    assert result.blocked == 1
    assert adapter.attempts == 0, "the adapter must not have been executed"
    assert adapter.tokens_seen == []
    assert result.outcomes[0].decision_code == ComplianceDecisionCode.BLOCKED_ROBOTS


def test_a_disabled_source_never_reaches_the_adapter(
    app_session: Session, refs: SeedRefs
) -> None:
    adapter = MockAdapter()
    source = app_session.get(Source, refs.sources["makemytrip"])
    assert source is not None
    source.adapter_key = "mock_v1"
    app_session.flush()

    spec = replace(_spec(refs), source_id=source.id, source_code="makemytrip")
    result = _runner(adapter).run(app_session, [spec], now=NOW)

    assert adapter.attempts == 0
    assert result.outcomes[0].decision_code == ComplianceDecisionCode.SKIPPED_DISABLED


def test_a_run_of_only_refusals_is_a_success_not_a_failure(
    app_session: Session, refs: SeedRefs, ready_source: UUID
) -> None:
    """Correctly refusing every restricted source is the system working."""
    result = _runner(MockAdapter(), robots_body=RESTRICTIVE).run(
        app_session, [_spec(refs), _spec(refs, bucket="T21")], now=NOW
    )
    assert result.blocked == 2
    assert result.failed == 0
    assert result.status == JobStatus.SUCCESS


# -- failure handling ------------------------------------------------------


def test_a_transport_failure_is_retried_then_recorded(
    app_session: Session, refs: SeedRefs, ready_source: UUID
) -> None:
    adapter = MockAdapter(behaviour=MockBehaviour.TIMEOUT)
    result = _runner(adapter).run(app_session, [_spec(refs)], now=NOW)

    assert adapter.attempts == 3, "one attempt plus two retries"
    assert result.failed == 1
    assert result.status == JobStatus.FAILED
    assert "timed out" in result.outcomes[0].detail


def test_a_recovering_source_succeeds_on_a_retry(
    app_session: Session, refs: SeedRefs, ready_source: UUID
) -> None:
    adapter = MockAdapter(behaviour=MockBehaviour.CONNECTION_ERROR, recover_after=1)
    result = _runner(adapter).run(app_session, [_spec(refs)], now=NOW)

    assert adapter.attempts == 2
    assert result.collected == 1


def test_a_parse_failure_is_contained(
    app_session: Session, refs: SeedRefs, ready_source: UUID
) -> None:
    """A broken parser fails one spec, it does not kill the run."""
    adapter = MockAdapter(behaviour=MockBehaviour.UNPARSEABLE)
    result = _runner(adapter).run(app_session, [_spec(refs)], now=NOW)

    assert result.failed == 1
    assert "Parse failed" in result.outcomes[0].detail


def test_a_failure_never_substitutes_another_source(
    app_session: Session, refs: SeedRefs, ready_source: UUID
) -> None:
    """No silent fallback: provenance is part of a quote's meaning."""
    adapter = MockAdapter(behaviour=MockBehaviour.HTTP_ERROR)
    result = _runner(adapter).run(app_session, [_spec(refs)], now=NOW)

    assert result.collected == 0
    assert app_session.execute(sa.select(sa.func.count()).select_from(RawQuote)).scalar_one() == 0
    assert "503" in result.outcomes[0].detail


def test_a_mixed_run_is_partial(
    app_session: Session, refs: SeedRefs, ready_source: UUID
) -> None:
    adapter = MockAdapter(behaviour=MockBehaviour.CONNECTION_ERROR, recover_after=3)
    result = _runner(adapter).run(
        app_session, [_spec(refs), _spec(refs, bucket="T21")], now=NOW
    )
    assert result.status == JobStatus.PARTIAL
    assert result.collected == 1
    assert result.failed == 1


# -- idempotency -----------------------------------------------------------


def test_the_same_search_is_not_issued_twice(
    app_session: Session, refs: SeedRefs, ready_source: UUID
) -> None:
    runner = _runner(MockAdapter())
    spec = _spec(refs)
    runner.run(app_session, [spec], now=NOW)
    second = runner.run(app_session, [spec], now=NOW + timedelta(minutes=10))

    assert second.outcomes[0].status == "DUPLICATE"
    assert (
        app_session.execute(sa.select(sa.func.count()).select_from(CollectionRequest)).scalar_one()
        == 1
    )


def test_an_empty_plan_produces_an_empty_successful_job(app_session: Session) -> None:
    result = _runner(MockAdapter()).run(app_session, [], now=NOW)
    job = app_session.get(CollectionJob, result.job_id)
    assert job is not None and job.status == JobStatus.SUCCESS and job.requests_total == 0


def test_a_source_with_no_registered_adapter_is_skipped(
    app_session: Session, refs: SeedRefs, ready_source: UUID
) -> None:
    source = app_session.get(Source, ready_source)
    assert source is not None
    source.adapter_key = "not_registered_v1"
    app_session.flush()

    result = _runner(MockAdapter()).run(app_session, [_spec(refs)], now=NOW)
    assert result.outcomes[0].status == "SKIPPED"
    assert "No adapter registered" in result.outcomes[0].detail


# -- crawl-delay across a multi-spec plan ----------------------------------


def test_a_plan_honours_crawl_delay_by_waiting_not_by_skipping(
    app_session: Session, refs: SeedRefs, ready_source: UUID
) -> None:
    """Several searches in one job should all be collected, politely.

    A frozen clock would defer every request after the first, so a job would
    collect one quote and call it a day. The runner times each spec when it
    runs and waits out a crawl-delay deferral, which is what a well-behaved
    crawler does.
    """
    slept: list[float] = []
    adapter = MockAdapter()
    with mock.patch.dict(os.environ, {"APIX_CONTACT_URL": "https://example.org"}, clear=False):
        config = ComplianceConfig.from_env()
    gate = ComplianceGate(config, RobotsCache(config, StubFetcher(), write_snapshots=False))

    # A clock that barely moves, so the crawl-delay genuinely bites.
    state = {"t": NOW}

    def clock() -> datetime:
        state["t"] = state["t"] + timedelta(seconds=1)
        return state["t"]

    def sleeper(seconds: float) -> None:
        slept.append(seconds)
        state["t"] = state["t"] + timedelta(seconds=seconds)

    runner = CollectionRunner(
        gate,
        {"mock_v1": adapter},
        retry=RetryPolicy(max_attempts=1),
        sleep=sleeper,
        clock=clock,
    )
    plan = [_spec(refs, bucket=b) for b in ("T1", "T7", "T15")]
    result = runner.run(app_session, plan, now=NOW)

    assert result.collected == 3, "every permitted search should be collected"
    assert slept, "the runner should have waited out the crawl delay"
    assert all(s <= 5.0 for s in slept)


def test_a_daily_budget_deferral_is_reported_not_slept_through(
    app_session: Session, refs: SeedRefs, ready_source: UUID
) -> None:
    """"Come back tomorrow" is not something to sleep on."""
    slept: list[float] = []
    with mock.patch.dict(
        os.environ,
        {"APIX_DAILY_REQUEST_BUDGET": "1", "APIX_CONTACT_URL": "https://example.org"},
        clear=False,
    ):
        config = ComplianceConfig.from_env()
    gate = ComplianceGate(config, RobotsCache(config, StubFetcher(), write_snapshots=False))
    runner = CollectionRunner(
        gate,
        {"mock_v1": MockAdapter()},
        retry=RetryPolicy(max_attempts=1),
        sleep=lambda s: slept.append(s),
        clock=_advancing_clock(step_seconds=30),
    )

    result = runner.run(app_session, [_spec(refs, bucket="T1"), _spec(refs, bucket="T7")], now=NOW)

    assert result.collected == 1
    assert result.deferred == 1
    assert not slept, "the runner must not sleep until tomorrow"
