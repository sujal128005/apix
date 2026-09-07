"""The collection runner.

Walks a plan of searches, and for each one: records the intent, asks the gate,
fetches only if the gate allowed it, stores the raw payload, and advances the
job counters. It is the only component that calls an adapter, and it cannot call
one without a token, so every fetch in the system is gated by construction.

Three properties are worth stating because they are easy to lose later.

**The request row is written before the gate runs.** A search we intended but
were refused is evidence - it is how the Sources page can say "we tried, and
robots said no". Writing the intent only on success would erase every refusal
from the record.

**Refusals are not failures.** A ``BLOCKED_ROBOTS`` outcome advances the blocked
counter, not the failure counter, and does not degrade the job. A run in which
every restricted OTA was correctly refused is a *successful* run.

**No silent fallback.** If a source is unavailable the runner records that and
moves on. It never quietly substitutes another source for the one that failed,
because a quote's provenance is part of its meaning.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from collector.adapter import AdapterResponse, CollectionSpec, SourceAdapter
from collector.retry import RetryPolicy, TransportOutcome
from compliance.gate import Allowed, ComplianceGate, Refused
from compliance.token import TokenRegistry
from schemas.enums import ComplianceDecisionCode, JobStatus
from schemas.hashing import compute_query_hash
from schemas.models.collection import CollectionJob, CollectionRequest, RawQuote, RawResponse
from schemas.models.reference import Source

__all__ = ["CollectionRunner", "RunResult", "SpecOutcome"]

logger = logging.getLogger("apix.collector")


@dataclass(frozen=True, slots=True)
class SpecOutcome:
    """What became of one planned search."""

    spec: CollectionSpec
    status: str  # COLLECTED | BLOCKED | DEFERRED | SKIPPED | FAILED | DUPLICATE
    decision_code: str | None = None
    quotes: int = 0
    detail: str = ""
    request_id: UUID | None = None
    raw_response_id: UUID | None = None


@dataclass(slots=True)
class RunResult:
    """Everything that happened in one job, in a shape the Command Center can render."""

    job_id: UUID
    started_at: datetime
    finished_at: datetime | None = None
    outcomes: list[SpecOutcome] = field(default_factory=list)

    @property
    def collected(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "COLLECTED")

    @property
    def blocked(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "BLOCKED")

    @property
    def deferred(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "DEFERRED")

    @property
    def failed(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "FAILED")

    @property
    def quotes(self) -> int:
        return sum(o.quotes for o in self.outcomes)

    @property
    def status(self) -> str:
        """A run where everything was correctly refused still succeeded.

        Only a *failure* - a source that broke rather than declined - makes a
        run partial. Conflating the two would make the compliance layer look
        like an outage.
        """
        if not self.outcomes:
            return JobStatus.SUCCESS
        if self.failed and self.collected:
            return JobStatus.PARTIAL
        if self.failed and not self.collected:
            return JobStatus.FAILED
        return JobStatus.SUCCESS


class CollectionRunner:
    """Executes a collection plan through the gate and into raw storage."""

    def __init__(
        self,
        gate: ComplianceGate,
        adapters: dict[str, SourceAdapter],
        *,
        retry: RetryPolicy | None = None,
        sleep: Any = time.sleep,
        clock: Any = None,
        max_wait_seconds: float = 120.0,
    ) -> None:
        self._gate = gate
        self._adapters = adapters
        self._retry = retry or RetryPolicy()
        self._sleep = sleep
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_wait = max_wait_seconds
        self._tokens = TokenRegistry()

    # -- public ------------------------------------------------------------
    def run(
        self,
        session: Session,
        plan: list[CollectionSpec],
        *,
        now: datetime | None = None,
    ) -> RunResult:
        started = now or datetime.now(UTC)
        job = CollectionJob(started_at=started, status=JobStatus.RUNNING)
        session.add(job)
        session.flush()

        result = RunResult(job_id=job.id, started_at=started)
        for spec in plan:
            # Each spec is timed when it runs, not when the job began. A single
            # frozen timestamp would make the gate defer every request after the
            # first on crawl-delay, and a job would collect exactly one quote.
            result.outcomes.append(self._run_one(session, job, spec, now=self._clock()))

        job.requests_total = len(result.outcomes)
        job.requests_ok = result.collected
        job.requests_blocked = result.blocked
        job.parse_failures = result.failed
        job.status = result.status
        job.finished_at = datetime.now(UTC) if now is None else now
        result.finished_at = job.finished_at
        session.flush()

        logger.info(
            "collection job finished",
            extra={
                "job_id": str(job.id),
                "status": job.status,
                "collected": result.collected,
                "blocked": result.blocked,
                "deferred": result.deferred,
                "failed": result.failed,
                "quotes": result.quotes,
            },
        )
        return result

    # -- one spec ----------------------------------------------------------
    def _run_one(
        self,
        session: Session,
        job: CollectionJob,
        spec: CollectionSpec,
        *,
        now: datetime,
    ) -> SpecOutcome:
        query_hash = compute_query_hash(
            source_code=spec.source_code,
            route_code=spec.route_code,
            bucket_code=spec.bucket_code,
            travel_date=spec.travel_date,
            collected_date=spec.collected_date,
        )

        existing = session.execute(
            select(CollectionRequest.id).where(CollectionRequest.query_hash == query_hash)
        ).first()
        if existing is not None:
            return SpecOutcome(
                spec=spec,
                status="DUPLICATE",
                detail="This exact search was already issued; not repeating it.",
                request_id=existing[0],
            )

        request_row = CollectionRequest(
            job_id=job.id,
            source_id=spec.source_id,
            route_id=spec.route_id,
            bucket_id=spec.bucket_id,
            travel_date=spec.travel_date,
            collected_date=spec.collected_date,
            query_hash=query_hash,
        )
        session.add(request_row)
        session.flush()

        adapter = self._adapters.get(self._adapter_key(session, spec.source_id))
        if adapter is None:
            return SpecOutcome(
                spec=spec,
                status="SKIPPED",
                detail=f"No adapter registered for source {spec.source_code}.",
                request_id=request_row.id,
            )

        request = adapter.build_request(spec)

        # The gate evaluates the path the adapter will actually fetch.
        verdict = self._gate.evaluate(
            session,
            source_id=spec.source_id,
            path=request.path,
            request_id=request_row.id,
            now=now,
        )

        # A crawl-delay deferral is an instruction to wait, and waiting a few
        # seconds is exactly the right response. A daily-budget deferral says
        # "come back tomorrow", which is not something to sleep through, so the
        # wait is bounded and anything longer is simply reported.
        if (
            isinstance(verdict, Refused)
            and verdict.code == ComplianceDecisionCode.DEFERRED_RATE_LIMIT
            and verdict.retry_after is not None
        ):
            wait = (verdict.retry_after - now).total_seconds()
            if 0 < wait <= self._max_wait:
                self._sleep(wait)
                now = self._clock()
                verdict = self._gate.evaluate(
                    session,
                    source_id=spec.source_id,
                    path=request.path,
                    request_id=request_row.id,
                    now=now,
                )

        if isinstance(verdict, Refused):
            status = (
                "BLOCKED"
                if verdict.code
                in (
                    ComplianceDecisionCode.BLOCKED_ROBOTS,
                    ComplianceDecisionCode.BLOCKED_UNREVIEWED,
                )
                else "DEFERRED"
                if verdict.code == ComplianceDecisionCode.DEFERRED_RATE_LIMIT
                else "SKIPPED"
            )
            logger.info(
                "fetch refused",
                extra={
                    "job_id": str(job.id),
                    "source": spec.source_code,
                    "path": request.path,
                    "decision": verdict.code,
                },
            )
            return SpecOutcome(
                spec=spec,
                status=status,
                decision_code=verdict.code,
                detail=verdict.reason,
                request_id=request_row.id,
            )

        assert isinstance(verdict, Allowed)
        source = session.get(Source, spec.source_id)
        assert source is not None and source.base_url is not None

        token = self._tokens.redeem(
            verdict.token, source_id=spec.source_id, path=request.path, now=now
        )

        response, outcome = self._fetch_with_retry(adapter, request, token, source.base_url)
        if response is None or not outcome.succeeded:
            return SpecOutcome(
                spec=spec,
                status="FAILED",
                decision_code=ComplianceDecisionCode.ALLOWED,
                detail=self._failure_detail(outcome),
                request_id=request_row.id,
            )

        try:
            quotes = adapter.parse(response)
        except Exception as exc:
            logger.warning(
                "parse failure",
                extra={"source": spec.source_code, "error": repr(exc)},
            )
            return SpecOutcome(
                spec=spec,
                status="FAILED",
                detail=f"Parse failed: {exc!r}. Payload retained for a fixture.",
                request_id=request_row.id,
            )

        raw_response = RawResponse(
            request_id=request_row.id,
            payload_ref=f"inline:{spec.source_code}/{query_hash[:16]}",
            sha256=hashlib.sha256(response.body.encode("utf-8")).hexdigest(),
            http_status=response.http_status,
            fetched_at=response.fetched_at,
        )
        session.add(raw_response)
        session.flush()

        for quote in quotes:
            session.add(
                RawQuote(
                    raw_response_id=raw_response.id,
                    ordinal=quote.ordinal,
                    payload=adapter.normalize(quote),
                )
            )
        session.flush()

        return SpecOutcome(
            spec=spec,
            status="COLLECTED",
            decision_code=ComplianceDecisionCode.ALLOWED,
            quotes=len(quotes),
            request_id=request_row.id,
            raw_response_id=raw_response.id,
        )

    # -- helpers -----------------------------------------------------------
    def _fetch_with_retry(
        self,
        adapter: SourceAdapter,
        request: Any,
        token: Any,
        base_url: str,
    ) -> tuple[AdapterResponse | None, TransportOutcome]:
        """Attempt the fetch, retrying only transport failures.

        A refusal never reaches here: the gate has already returned Allowed, and
        the only thing being retried is the wire.
        """
        outcome = TransportOutcome(http_status=None, connection_error=True)
        for attempt in range(1, self._retry.max_attempts + 1):
            delay = self._retry.delay_for(attempt)
            if delay:
                self._sleep(delay)
            try:
                response = adapter.execute(request, token, base_url=base_url)
            except TimeoutError:
                outcome = TransportOutcome(http_status=None, timed_out=True)
            except Exception:
                outcome = TransportOutcome(http_status=None, connection_error=True)
            else:
                outcome = TransportOutcome(http_status=response.http_status)
                if outcome.succeeded:
                    return response, outcome
            if not self._retry.should_retry(outcome, attempt):
                return None, outcome
        return None, outcome

    @staticmethod
    def _failure_detail(outcome: TransportOutcome) -> str:
        if outcome.timed_out:
            return "Source timed out. Recorded as unavailable; no other source substituted."
        if outcome.connection_error:
            return "Could not reach the source. Recorded as unavailable."
        return f"Source returned HTTP {outcome.http_status}."

    @staticmethod
    def _adapter_key(session: Session, source_id: UUID) -> str:
        source = session.get(Source, source_id)
        return source.adapter_key if source else ""
