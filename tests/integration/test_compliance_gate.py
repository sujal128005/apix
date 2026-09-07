"""The gate, against a real PostgreSQL.

Each of the six checks is failed in isolation, and every outcome is asserted to
write exactly one compliance_decision row - the count matters, not merely the
existence, because a gate that double-writes would corrupt the daily budget it
computes from those same rows.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest import mock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from compliance.config import ComplianceConfig
from compliance.errors import UnknownSourceError
from compliance.gate import Allowed, ComplianceGate, Refused
from compliance.robots import RobotsCache
from schemas.enums import ComplianceDecisionCode, ReviewVerdict
from schemas.models.collection import ComplianceDecision
from schemas.models.reference import Source, SourceReview
from tests.support.builders import SeedRefs

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)

PERMISSIVE = "User-agent: *\nAllow: /\n"
RESTRICTIVE = "User-agent: *\nDisallow: /air/*\nDisallow: /pwa/\n"


class StubFetcher:
    def __init__(self, status: int | None = 200, body: str | None = PERMISSIVE) -> None:
        self.status, self.body, self.calls = status, body, 0

    def fetch(self, base_url: str, *, user_agent: str, timeout: float):
        self.calls += 1
        return self.status, self.body


def _gate(status: int | None = 200, body: str | None = PERMISSIVE, contact: str = "https://example.org"):
    with mock.patch.dict(os.environ, {"APIX_CONTACT_URL": contact}, clear=False):
        config = ComplianceConfig.from_env()
    fetcher = StubFetcher(status, body)
    cache = RobotsCache(config, fetcher, write_snapshots=False)
    return ComplianceGate(config, cache), fetcher


def _decisions(session: Session, source_id: UUID) -> list[ComplianceDecision]:
    return list(
        session.execute(
            sa.select(ComplianceDecision).where(ComplianceDecision.source_id == source_id)
        ).scalars()
    )


@pytest.fixture
def ready_source(app_session: Session, refs: SeedRefs) -> UUID:
    """A source that is enabled, reviewed APPROVED and has a base_url."""
    source_id = refs.sources["indigo_web"]
    source = app_session.get(Source, source_id)
    assert source is not None
    source.enabled = True
    source.base_url = "https://example.com"
    app_session.add(
        SourceReview(
            source_id=source_id,
            reviewer="architect",
            reviewed_at=NOW,
            robots_decision="Allow: / for our UA",
            tos_note="Reviewed for Phase 4A test",
            verdict=ReviewVerdict.APPROVED,
        )
    )
    app_session.flush()
    return source_id


# -- check 1: enabled ------------------------------------------------------


def test_a_disabled_source_is_skipped(app_session: Session, refs: SeedRefs) -> None:
    gate, fetcher = _gate()
    source_id = refs.sources["makemytrip"]  # seeded disabled
    result = gate.evaluate(app_session, source_id=source_id, path="/air/search", now=NOW)

    assert isinstance(result, Refused)
    assert result.code == ComplianceDecisionCode.SKIPPED_DISABLED
    assert fetcher.calls == 0, "a disabled source must not cause a robots.txt fetch"


def test_an_unknown_source_raises_rather_than_forging_evidence(app_session: Session) -> None:
    """An unknown source_id is a caller fault, not a compliance decision.

    Writing a decision row for a source that does not exist would put
    unattributable evidence in the audit trail. The compliance_decision foreign
    key forbids it, and the gate agrees rather than working around it.
    """
    gate, _ = _gate()
    with pytest.raises(UnknownSourceError):
        gate.evaluate(app_session, source_id=uuid4(), path="/x", now=NOW)


# -- check 2: human review -------------------------------------------------


def test_an_enabled_but_unreviewed_source_is_blocked(
    app_session: Session, refs: SeedRefs
) -> None:
    gate, fetcher = _gate()
    source_id = refs.sources["indigo_web"]
    source = app_session.get(Source, source_id)
    assert source is not None
    source.enabled = True
    source.base_url = "https://example.com"
    app_session.flush()

    result = gate.evaluate(app_session, source_id=source_id, path="/search", now=NOW)
    assert isinstance(result, Refused)
    assert result.code == ComplianceDecisionCode.BLOCKED_UNREVIEWED
    assert fetcher.calls == 0


def test_a_rejected_review_does_not_count_as_approval(
    app_session: Session, refs: SeedRefs
) -> None:
    gate, _ = _gate()
    source_id = refs.sources["indigo_web"]
    source = app_session.get(Source, source_id)
    assert source is not None
    source.enabled = True
    source.base_url = "https://example.com"
    app_session.add(
        SourceReview(
            source_id=source_id,
            reviewer="architect",
            reviewed_at=NOW,
            verdict=ReviewVerdict.REQUIRES_LEGAL_REVIEW,
        )
    )
    app_session.flush()

    result = gate.evaluate(app_session, source_id=source_id, path="/search", now=NOW)
    assert isinstance(result, Refused)
    assert result.code == ComplianceDecisionCode.BLOCKED_UNREVIEWED


def test_no_contact_url_means_no_crawling(app_session: Session, ready_source: UUID) -> None:
    """APIx does not crawl anonymously."""
    gate, fetcher = _gate(contact="")
    result = gate.evaluate(app_session, source_id=ready_source, path="/search", now=NOW)
    assert isinstance(result, Refused)
    assert result.code == ComplianceDecisionCode.BLOCKED_UNREVIEWED
    assert "anonymously" in result.reason
    assert fetcher.calls == 0


# -- check 4: robots -------------------------------------------------------


def test_a_disallowed_path_is_blocked_and_terminal(
    app_session: Session, ready_source: UUID
) -> None:
    gate, _ = _gate(body=RESTRICTIVE)
    result = gate.evaluate(app_session, source_id=ready_source, path="/air/search", now=NOW)

    assert isinstance(result, Refused)
    assert result.code == ComplianceDecisionCode.BLOCKED_ROBOTS
    assert result.is_terminal is True
    assert result.retry_after is None, "BLOCKED_ROBOTS is terminal: retrying cannot help"


def test_the_blocking_rule_is_recorded_for_audit(
    app_session: Session, ready_source: UUID
) -> None:
    gate, _ = _gate(body=RESTRICTIVE)
    gate.evaluate(app_session, source_id=ready_source, path="/air/search", now=NOW)
    row = _decisions(app_session, ready_source)[0]
    assert row.decision == ComplianceDecisionCode.BLOCKED_ROBOTS
    assert row.matched_rule is not None and "disallowed" in row.matched_rule
    assert row.user_agent.startswith("APIx-Research/")


def test_an_allowed_path_on_the_same_source_still_passes(
    app_session: Session, ready_source: UUID
) -> None:
    gate, _ = _gate(body=RESTRICTIVE)
    assert isinstance(
        gate.evaluate(app_session, source_id=ready_source, path="/airport-info", now=NOW),
        Allowed,
    )


# -- allowed ---------------------------------------------------------------


def test_a_permitted_fetch_mints_a_token_matching_its_row(
    app_session: Session, ready_source: UUID
) -> None:
    gate, _ = _gate()
    result = gate.evaluate(app_session, source_id=ready_source, path="/search", now=NOW)

    assert isinstance(result, Allowed)
    assert result.token.decision_id == result.decision_id
    assert result.token.source_id == ready_source
    assert result.token.path == "/search"
    assert result.token.expires_at == NOW + timedelta(seconds=300)
    assert result.crawl_delay == 5.0

    row = app_session.get(ComplianceDecision, result.decision_id)
    assert row is not None and row.decision == ComplianceDecisionCode.ALLOWED


# -- check 5: crawl-delay --------------------------------------------------


def test_a_second_fetch_inside_the_crawl_delay_is_deferred(
    app_session: Session, ready_source: UUID
) -> None:
    gate, _ = _gate()
    gate.evaluate(app_session, source_id=ready_source, path="/a", now=NOW)
    result = gate.evaluate(
        app_session, source_id=ready_source, path="/b", now=NOW + timedelta(seconds=2)
    )
    assert isinstance(result, Refused)
    assert result.code == ComplianceDecisionCode.DEFERRED_RATE_LIMIT
    assert result.retry_after == NOW + timedelta(seconds=5)


def test_a_fetch_after_the_crawl_delay_proceeds(
    app_session: Session, ready_source: UUID
) -> None:
    gate, _ = _gate()
    gate.evaluate(app_session, source_id=ready_source, path="/a", now=NOW)
    assert isinstance(
        gate.evaluate(
            app_session, source_id=ready_source, path="/b", now=NOW + timedelta(seconds=6)
        ),
        Allowed,
    )


# -- check 6: daily budget -------------------------------------------------


def test_the_daily_budget_is_enforced(app_session: Session, ready_source: UUID) -> None:
    with mock.patch.dict(
        os.environ,
        {"APIX_DAILY_REQUEST_BUDGET": "3", "APIX_CONTACT_URL": "https://example.org"},
        clear=False,
    ):
        config = ComplianceConfig.from_env()
    gate = ComplianceGate(config, RobotsCache(config, StubFetcher(), write_snapshots=False))

    for i in range(3):
        assert isinstance(
            gate.evaluate(
                app_session,
                source_id=ready_source,
                path=f"/p{i}",
                now=NOW + timedelta(seconds=10 * i),
            ),
            Allowed,
        )

    result = gate.evaluate(
        app_session, source_id=ready_source, path="/p3", now=NOW + timedelta(seconds=40)
    )
    assert isinstance(result, Refused)
    assert result.code == ComplianceDecisionCode.DEFERRED_RATE_LIMIT
    assert result.retry_after is not None and result.retry_after.date() == NOW.date() + timedelta(
        days=1
    )


def test_refusals_do_not_consume_budget(app_session: Session, ready_source: UUID) -> None:
    """Only ALLOWED decisions count. A blocked path must not exhaust the day."""
    with mock.patch.dict(
        os.environ,
        {"APIX_DAILY_REQUEST_BUDGET": "2", "APIX_CONTACT_URL": "https://example.org"},
        clear=False,
    ):
        config = ComplianceConfig.from_env()
    gate = ComplianceGate(
        config, RobotsCache(config, StubFetcher(body=RESTRICTIVE), write_snapshots=False)
    )

    for i in range(5):
        gate.evaluate(
            app_session, source_id=ready_source, path="/air/x", now=NOW + timedelta(seconds=10 * i)
        )
    assert isinstance(
        gate.evaluate(
            app_session, source_id=ready_source, path="/ok", now=NOW + timedelta(seconds=100)
        ),
        Allowed,
    )


# -- invariants ------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "body", "expected"),
    [
        ("/search", PERMISSIVE, ComplianceDecisionCode.ALLOWED),
        ("/air/search", RESTRICTIVE, ComplianceDecisionCode.BLOCKED_ROBOTS),
    ],
)
def test_every_outcome_writes_exactly_one_row(
    app_session: Session, ready_source: UUID, path: str, body: str, expected: str
) -> None:
    gate, _ = _gate(body=body)
    gate.evaluate(app_session, source_id=ready_source, path=path, now=NOW)
    rows = _decisions(app_session, ready_source)
    assert len(rows) == 1, f"expected exactly one decision row, got {len(rows)}"
    assert rows[0].decision == expected


def test_the_gate_never_raises_on_refusal(app_session: Session, refs: SeedRefs) -> None:
    """A blocked source is a normal outcome, returned as data."""
    gate, _ = _gate(body=RESTRICTIVE)
    for source_code in ("makemytrip", "yatra", "goibibo"):
        result = gate.evaluate(
            app_session, source_id=refs.sources[source_code], path="/air/x", now=NOW
        )
        assert isinstance(result, Refused)


def test_a_refusal_is_still_auditable(app_session: Session, refs: SeedRefs) -> None:
    gate, _ = _gate()
    source_id = refs.sources["makemytrip"]
    result = gate.evaluate(app_session, source_id=source_id, path="/air/search", now=NOW)
    row = app_session.get(ComplianceDecision, result.decision_id)
    assert row is not None
    assert row.path == "/air/search"
    assert row.decided_at == NOW
