"""The compliance gate: six checks between the scheduler and any network request.

Nothing reaches an adapter without passing through :func:`evaluate`. That is
enforced structurally rather than by convention - ``evaluate`` is the only
caller of :func:`compliance.token.mint`, and every fetch requires the token it
returns. See ADR-018.

Order matters. The checks are arranged cheapest-and-most-decisive first, so a
disabled source never causes a network fetch of robots.txt, and an unreviewed
source never gets as far as consuming its request budget.

    1. source exists and is enabled          -> SKIPPED_DISABLED
    2. a human review recorded APPROVED      -> BLOCKED_UNREVIEWED
    3. robots.txt fetched or cached (<24h)
    4. path allowed for our user agent       -> BLOCKED_ROBOTS   (terminal)
    5. crawl-delay elapsed                   -> DEFERRED_RATE_LIMIT
    6. daily request budget remaining        -> DEFERRED_RATE_LIMIT
       all pass                              -> ALLOWED + token

**BLOCKED_ROBOTS is terminal.** There is no retry path, no override argument, no
environment variable and no configuration key that produces a different answer.
The absence of such an escape is the security property; a safeguard that can be
switched off under deadline pressure is not a safeguard. ``tests/unit/
test_no_bypass_path_exists.py`` scans this package to keep it that way.

Refusal is never an exception. Every outcome - allowed or refused - is returned
as data and written as exactly one ``compliance_decision`` row, because a
blocked source is the system working correctly, not an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from compliance.config import ComplianceConfig
from compliance.errors import UnknownSourceError
from compliance.robots import RobotsCache, RobotsOutcome
from compliance.token import ComplianceToken, mint
from schemas.enums import ComplianceDecisionCode, ReviewVerdict
from schemas.models.collection import ComplianceDecision
from schemas.models.reference import Source, SourceReview

# ADR-019: the governing compliance document depends on what kind of access this
# is. For an API consumed under a published contract, robots.txt is not the
# governing document - it addresses crawlers. For anything fetched as a web
# page, robots.txt governs absolutely and BLOCKED_ROBOTS stays terminal.
#
# This is a property of the source row, not a call-time argument. There is no
# flag that moves a source between these sets, and no web-scraped source is in
# the API set. tests/integration/test_compliance_basis.py enforces both.
API_CONTRACT_TIERS: frozenset[int] = frozenset({1, 5})

__all__ = ["Allowed", "ComplianceGate", "GateResult", "Refused", "evaluate"]


@dataclass(frozen=True, slots=True)
class Allowed:
    """The fetch is authorised. The token is the proof."""

    token: ComplianceToken
    decision_id: UUID
    crawl_delay: float

    @property
    def is_allowed(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class Refused:
    """The fetch is refused, with the reason and whether it is worth retrying."""

    decision_id: UUID
    code: str
    reason: str
    retry_after: datetime | None

    @property
    def is_allowed(self) -> bool:
        return False

    @property
    def is_terminal(self) -> bool:
        """True when no later retry can change the answer."""
        return self.code == ComplianceDecisionCode.BLOCKED_ROBOTS


GateResult = Allowed | Refused


class ComplianceGate:
    """Evaluates fetches against source state, human review, robots and budget."""

    def __init__(
        self,
        config: ComplianceConfig | None = None,
        robots: RobotsCache | None = None,
    ) -> None:
        self._config = config or ComplianceConfig.from_env()
        self._robots = robots or RobotsCache(self._config)
        self._last_fetch: dict[UUID, datetime] = {}

    # -- persistence ------------------------------------------------------
    def _record(
        self,
        session: Session,
        *,
        source_id: UUID,
        request_id: UUID | None,
        path: str,
        code: str,
        decided_at: datetime,
        robots_sha256: str | None = None,
        matched_rule: str | None = None,
    ) -> UUID:
        row = ComplianceDecision(
            source_id=source_id,
            request_id=request_id,
            path=path,
            user_agent=self._config.user_agent,
            robots_sha256=robots_sha256,
            matched_rule=matched_rule,
            decision=code,
            decided_at=decided_at,
        )
        session.add(row)
        session.flush()
        return row.id

    # -- the gate ---------------------------------------------------------
    def evaluate(
        self,
        session: Session,
        *,
        source_id: UUID,
        path: str,
        request_id: UUID | None = None,
        now: datetime | None = None,
    ) -> GateResult:
        """Run the six checks and return the verdict. Never raises on refusal."""
        now = now or datetime.now(UTC)

        def refuse(code: str, reason: str, retry_after: datetime | None, **kw: object) -> Refused:
            decision_id = self._record(
                session,
                source_id=source_id,
                request_id=request_id,
                path=path,
                code=code,
                decided_at=now,
                **kw,  # type: ignore[arg-type]
            )
            return Refused(
                decision_id=decision_id, code=code, reason=reason, retry_after=retry_after
            )

        # --- 1. the source exists and is switched on ----------------------
        source = session.get(Source, source_id)
        if source is None:
            # Not a refusal: there is no source to refuse. Writing a decision row
            # here would be unattributable evidence, which the compliance_decision
            # foreign key correctly forbids.
            raise UnknownSourceError(
                f"No source with id {source_id}. The caller must resolve a real "
                "source before asking the gate to evaluate a fetch."
            )
        if not source.enabled:
            return refuse(
                ComplianceDecisionCode.SKIPPED_DISABLED,
                f"Source {source.code} is not enabled. Sources are opt-in.",
                None,
            )

        # --- 2. a human reviewed it and said yes --------------------------
        approved = session.execute(
            sa.select(SourceReview.id)
            .where(SourceReview.source_id == source_id)
            .where(SourceReview.verdict == ReviewVerdict.APPROVED)
            .limit(1)
        ).first()
        if approved is None:
            return refuse(
                ComplianceDecisionCode.BLOCKED_UNREVIEWED,
                f"Source {source.code} has no APPROVED source_review. "
                "A human must review robots and terms before collection.",
                None,
            )

        # We never crawl without identifying ourselves.
        if not self._config.has_contact:
            return refuse(
                ComplianceDecisionCode.BLOCKED_UNREVIEWED,
                "APIX_CONTACT_URL is not configured. APIx does not crawl anonymously.",
                None,
            )

        if not source.base_url:
            return refuse(
                ComplianceDecisionCode.BLOCKED_UNREVIEWED,
                f"Source {source.code} has no base_url, so robots.txt cannot be located.",
                None,
            )

        # --- 3 & 4. robots.txt, then the path ------------------------------
        # Fetched for every source, including API sources, because the record of
        # what a site published is worth having even when it does not govern.
        document = self._robots.get(source.code, source.base_url, now=now)
        allowed, matched_rule = document.allows(path, self._config.user_agent)

        if source.tier in API_CONTRACT_TIERS:
            matched_rule = (
                f"api terms (tier {source.tier}): robots.txt is not the governing "
                f"document for API access; robots said: {matched_rule}"
            )
            allowed = True

        if not allowed:
            return refuse(
                ComplianceDecisionCode.BLOCKED_ROBOTS,
                f"{path} is disallowed for {source.code}: {matched_rule}",
                None,  # terminal: retrying cannot change this
                robots_sha256=document.sha256,
                matched_rule=matched_rule,
            )

        # --- 5. crawl-delay ------------------------------------------------
        declared = document.crawl_delay(self._config.user_agent)
        crawl_delay = self._config.effective_crawl_delay(declared)
        last = self._last_fetch.get(source_id)
        if last is not None:
            due = last + timedelta(seconds=crawl_delay)
            if now < due:
                return refuse(
                    ComplianceDecisionCode.DEFERRED_RATE_LIMIT,
                    f"Crawl-delay of {crawl_delay}s has not elapsed for {source.code}.",
                    due,
                    robots_sha256=document.sha256,
                    matched_rule=matched_rule,
                )

        # --- 6. daily budget -----------------------------------------------
        used = self._requests_today(session, source_id=source_id, today=now.date())
        if used >= self._config.daily_request_budget:
            tomorrow = datetime.combine(
                now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC
            )
            return refuse(
                ComplianceDecisionCode.DEFERRED_RATE_LIMIT,
                f"Daily budget of {self._config.daily_request_budget} exhausted "
                f"for {source.code} ({used} allowed today).",
                tomorrow,
                robots_sha256=document.sha256,
                matched_rule=matched_rule,
            )

        # --- allowed --------------------------------------------------------
        decision_id = self._record(
            session,
            source_id=source_id,
            request_id=request_id,
            path=path,
            code=ComplianceDecisionCode.ALLOWED,
            decided_at=now,
            robots_sha256=document.sha256,
            matched_rule=matched_rule,
        )
        self._last_fetch[source_id] = now
        token = mint(
            decision_id=decision_id,
            source_id=source_id,
            path=path,
            user_agent=self._config.user_agent,
            issued_at=now,
            expires_at=now + timedelta(seconds=self._config.token_ttl_seconds),
            crawl_delay=crawl_delay,
        )
        return Allowed(token=token, decision_id=decision_id, crawl_delay=crawl_delay)

    @staticmethod
    def _requests_today(session: Session, *, source_id: UUID, today: date) -> int:
        """Count ALLOWED decisions for this source today. Refusals cost no budget."""
        start = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
        end = start + timedelta(days=1)
        return int(
            session.execute(
                sa.select(sa.func.count())
                .select_from(ComplianceDecision)
                .where(ComplianceDecision.source_id == source_id)
                .where(ComplianceDecision.decision == ComplianceDecisionCode.ALLOWED)
                .where(ComplianceDecision.decided_at >= start)
                .where(ComplianceDecision.decided_at < end)
            ).scalar_one()
        )

    def note_robots_outcome(self, source_code: str) -> str:
        """Expose the last robots outcome for a source, for the Sources page."""
        entry = self._robots._entries.get(source_code)
        return entry.outcome if entry else RobotsOutcome.UNAVAILABLE


_DEFAULT_GATE: ComplianceGate | None = None


def evaluate(
    session: Session,
    *,
    source_id: UUID,
    path: str,
    request_id: UUID | None = None,
    now: datetime | None = None,
) -> GateResult:
    """Module-level convenience wrapper over a lazily built default gate."""
    global _DEFAULT_GATE
    if _DEFAULT_GATE is None:
        _DEFAULT_GATE = ComplianceGate()
    return _DEFAULT_GATE.evaluate(
        session, source_id=source_id, path=path, request_id=request_id, now=now
    )
