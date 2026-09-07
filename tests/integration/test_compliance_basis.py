"""ADR-019: the right compliance document for the right kind of access.

An API consumed under a published contract is not crawling, so robots.txt does
not govern it. That is a real distinction - and exactly the kind that becomes a
loophole if nobody guards it. These tests are the guard.

The load-bearing assertions are the negative ones: no web-scraped source can be
in the API set, no OTA can reach it, and there is no argument anywhere that
moves a source between sets at call time.
"""

from __future__ import annotations

import ast
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from compliance.config import ComplianceConfig
from compliance.gate import API_CONTRACT_TIERS, Allowed, ComplianceGate, Refused
from compliance.robots import RobotsCache
from schemas.enums import ComplianceDecisionCode, ReviewVerdict, SourceTier
from schemas.models.collection import ComplianceDecision
from schemas.models.reference import Source, SourceReview
from tests.support.builders import SeedRefs

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[2]

BLOCK_EVERYTHING = "User-agent: *\nDisallow: /\n"


class StubFetcher:
    def __init__(self, body: str = BLOCK_EVERYTHING) -> None:
        self.body = body

    def fetch(self, base_url: str, *, user_agent: str, timeout: float):
        return 200, self.body


def _gate(body: str = BLOCK_EVERYTHING) -> ComplianceGate:
    with mock.patch.dict(os.environ, {"APIX_CONTACT_URL": "https://example.org"}, clear=False):
        config = ComplianceConfig.from_env()
    return ComplianceGate(config, RobotsCache(config, StubFetcher(body), write_snapshots=False))


def _prepare(session: Session, source_id: UUID, *, tier: int, tos_note: str | None) -> Source:
    source = session.get(Source, source_id)
    assert source is not None
    source.enabled = True
    source.base_url = "https://example.com"
    source.tier = tier
    session.add(
        SourceReview(
            source_id=source_id,
            reviewer="architect",
            reviewed_at=NOW,
            robots_decision="Disallow: / for all agents",
            tos_note=tos_note,
            verdict=ReviewVerdict.APPROVED,
        )
    )
    session.flush()
    return source


# -- the distinction works -------------------------------------------------


def test_an_official_api_source_is_not_blocked_by_a_crawler_directive(
    app_session: Session, refs: SeedRefs
) -> None:
    """MoSPI's own API, called with MoSPI's own client, is not crawling."""
    _prepare(
        app_session,
        refs.sources["mospi_cpi"],
        tier=int(SourceTier.OFFICIAL_STATISTICS),
        tos_note="Official open API; consumed via documented endpoints.",
    )
    result = _gate().evaluate(
        app_session, source_id=refs.sources["mospi_cpi"], path="/api/cpi/getCpiBaseYear", now=NOW
    )
    assert isinstance(result, Allowed)


def test_the_basis_is_recorded_on_the_decision_row(
    app_session: Session, refs: SeedRefs
) -> None:
    """The audit trail must say *why* it was allowed, not merely that it was."""
    _prepare(app_session, refs.sources["mospi_cpi"], tier=5, tos_note="Official open API.")
    result = _gate().evaluate(
        app_session, source_id=refs.sources["mospi_cpi"], path="/api/cpi/getCPIData", now=NOW
    )
    row = app_session.get(ComplianceDecision, result.decision_id)
    assert row is not None
    assert row.matched_rule is not None
    assert "api terms (tier 5)" in row.matched_rule
    assert "robots said" in row.matched_rule, "the robots verdict is still recorded"


# -- the distinction cannot be abused --------------------------------------


@pytest.mark.parametrize("source_code", ["makemytrip", "yatra", "goibibo", "cleartrip"])
def test_a_restricted_ota_is_still_blocked(
    app_session: Session, refs: SeedRefs, source_code: str
) -> None:
    """No OTA reaches the API set. Tier 4 means robots.txt governs, absolutely."""
    _prepare(app_session, refs.sources[source_code], tier=4, tos_note=None)
    result = _gate().evaluate(
        app_session, source_id=refs.sources[source_code], path="/air/search", now=NOW
    )
    assert isinstance(result, Refused)
    assert result.code == ComplianceDecisionCode.BLOCKED_ROBOTS
    assert result.is_terminal is True


@pytest.mark.parametrize("tier", [2, 3, 4])
def test_every_web_tier_is_governed_by_robots(
    app_session: Session, refs: SeedRefs, tier: int
) -> None:
    _prepare(app_session, refs.sources["indigo_web"], tier=tier, tos_note="reviewed")
    result = _gate().evaluate(
        app_session, source_id=refs.sources["indigo_web"], path="/search", now=NOW
    )
    assert isinstance(result, Refused)
    assert result.code == ComplianceDecisionCode.BLOCKED_ROBOTS


def test_no_browser_transport_source_may_claim_an_api_basis(app_session: Session) -> None:
    """A scraped page can never be tier 1 or 5, in seed data or at runtime."""
    offenders = app_session.execute(
        sa.select(Source.code, Source.tier, Source.transport).where(
            Source.transport == "browser", Source.tier.in_(tuple(API_CONTRACT_TIERS))
        )
    ).all()
    assert not offenders, f"browser sources claiming an API compliance basis: {offenders}"


def test_an_api_source_still_needs_a_human_review(
    app_session: Session, refs: SeedRefs
) -> None:
    """Tier alone authorises nothing. A person must still have approved it."""
    source = app_session.get(Source, refs.sources["mospi_cpi"])
    assert source is not None
    source.enabled = True
    source.base_url = "https://example.com"
    source.tier = 5
    app_session.flush()  # deliberately no SourceReview

    result = _gate().evaluate(
        app_session, source_id=refs.sources["mospi_cpi"], path="/api/cpi/getCpiBaseYear", now=NOW
    )
    assert isinstance(result, Refused)
    assert result.code == ComplianceDecisionCode.BLOCKED_UNREVIEWED


def test_the_tier_set_is_a_constant_not_a_parameter() -> None:
    """No function anywhere accepts a tier or basis argument at call time.

    ADR-019 is only defensible because the basis is a column on a row, set by a
    migration and visible in the database. If it could be passed to evaluate(),
    it would be the override flag ADR-006 forbids, wearing a different name.
    """
    gate_source = (REPO_ROOT / "packages" / "compliance" / "gate.py").read_text(encoding="utf-8")
    tree = ast.parse(gate_source)
    banned = {"tier", "compliance_basis", "basis", "api_tier", "ignore_robots"}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            names = {a.arg for a in (*node.args.args, *node.args.kwonlyargs)}
            assert not (names & banned), f"{node.name}() accepts {sorted(names & banned)}"


def test_the_api_tier_set_is_exactly_licensed_and_official() -> None:
    assert frozenset({1, 5}) == API_CONTRACT_TIERS, (
        "Widening this set is an architecture decision, not a bug fix. "
        "Amend ADR-019 first."
    )
