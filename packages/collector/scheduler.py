"""Scheduled daily collection.

PS 26056 requires a scraping engine "capable of scheduled daily extraction". Up
to this point the project had an adapter framework, a runner and a documented
intention to use APScheduler - which is not the same thing as a scheduler, and
`docs/AUDIT.md` was more generous about it than the code deserved. This module
closes that gap.

What it does each day, in one job:

    plan the day's searches -> compliance gate -> adapters -> raw storage
    -> normalise -> matched pairs -> index -> record the run

Four properties that matter more than the scheduling itself:

**One run at a time, across every node.** ``max_instances=1`` prevents a job
overlapping itself *within* a process. It does nothing about a second process:
run two API instances behind a load balancer and both schedulers fire, doubling
the request volume every source sees. Production therefore takes a **PostgreSQL
advisory lock** before collecting, and a node that cannot acquire it stands down
quietly. The lock is held for the duration of the run and released automatically
if the node dies, which is the property a heartbeat table would have to
reimplement badly.

**Missed runs are not stampeded.** ``coalesce=True`` with a bounded
``misfire_grace_time``. If the process was down for three days, the scheduler
runs *once* on restart rather than firing three catch-up jobs at a source that
has just seen us disappear.

**A failed run does not kill the schedule.** Exceptions are caught, recorded and
logged; tomorrow's run still happens. A scheduler that dies on the first bad day
is worse than a cron line.

**Collection is idempotent anyway.** ``query_hash`` uniqueness means a repeated
search is refused at the database rather than re-issued, so the worst case of a
double trigger is a wasted loop, not duplicate load on an airline.

The schedule runs in **IST**, because the collection date and the T+N travel
dates are defined in IST. Scheduling in UTC would silently shift which day a
"daily" run belongs to for half the year's worth of edge cases.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session, sessionmaker

from collector.adapter import CollectionSpec
from schemas.models.reference import LeadTimeBucket, Route, Source

__all__ = [
    "COLLECTION_LOCK_KEY",
    "IST",
    "CollectionSchedule",
    "DailyCollectionJob",
    "build_daily_plan",
    "collection_lock",
    "start_scheduler",
]

#: Identifier for the advisory lock guarding the daily run. Arbitrary but fixed:
#: every node must ask for the same one. Spelled "APIX" in hex, to be unlikely to
#: collide with another application sharing the cluster.
COLLECTION_LOCK_KEY: Final[int] = 0x41504958

logger = logging.getLogger("apix.scheduler")

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True, slots=True)
class CollectionSchedule:
    """When the daily job runs, and how forgiving it is about missing one."""

    hour: int = 6
    minute: int = 0
    #: Two hours. Long enough to survive a restart, short enough that a run
    #: which fires at 3pm for a 6am slot is skipped rather than mislabelled -
    #: a "daily" fare collected nine hours late is a different observation.
    misfire_grace_seconds: int = 7200

    def trigger(self) -> CronTrigger:
        return CronTrigger(
            hour=self.hour, minute=self.minute, timezone=IST, jitter=120
        )


@contextmanager
def collection_lock(session: Session) -> Iterator[bool]:
    """Hold the cluster-wide collection lock, or yield False.

    ``pg_try_advisory_lock`` returns immediately rather than queuing: a node
    that loses the race should stand down, not wait to run the same day a second
    time. The lock is session-scoped, so a node that crashes releases it when its
    connection drops - no stale-lock cleanup to get wrong.
    """
    acquired = bool(
        session.execute(
            sa.text("SELECT pg_try_advisory_lock(:key)"), {"key": COLLECTION_LOCK_KEY}
        ).scalar_one()
    )
    try:
        yield acquired
    finally:
        if acquired:
            session.execute(
                sa.text("SELECT pg_advisory_unlock(:key)"), {"key": COLLECTION_LOCK_KEY}
            )


def build_daily_plan(session: Session, collected_date: date) -> list[CollectionSpec]:
    """Every enabled source x active route x lead-time bucket for one day.

    Disabled sources are excluded here as well as refused by the gate. That is
    deliberate redundancy: the gate is the guarantee, but there is no reason to
    generate thousands of requests we know will be refused, and a plan that is
    mostly refusals makes the run log unreadable.
    """
    sources = session.execute(
        sa.select(Source).where(Source.enabled.is_(True))
    ).scalars().all()
    routes = session.execute(
        sa.select(Route).where(Route.active.is_(True))
    ).scalars().all()
    buckets = session.execute(sa.select(LeadTimeBucket)).scalars().all()

    return [
        CollectionSpec(
            source_id=source.id,
            source_code=source.code,
            route_id=route.id,
            route_code=route.code,
            origin=route.code.split("-")[0],
            destination=route.code.split("-")[1],
            bucket_id=bucket.id,
            bucket_code=bucket.code,
            lead_time_days=bucket.days,
            travel_date=collected_date + timedelta(days=bucket.days),
            collected_date=collected_date,
        )
        for source in sources
        for route in routes
        for bucket in buckets
    ]


class DailyCollectionJob:
    """The unit of work the scheduler triggers. Separated so it can be tested
    without a scheduler, and run by hand without one."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        run_collection: Callable[[Session, list[CollectionSpec], date], int],
        compute_index: Callable[[Session, date], object],
    ) -> None:
        self._session_factory = session_factory
        self._run_collection = run_collection
        self._compute_index = compute_index

    def __call__(self, *, collected_date: date | None = None) -> None:
        """Run one day. Never raises: tomorrow's run must still happen."""
        day = collected_date or datetime.now(IST).date()
        started = datetime.now(UTC)
        logger.info("daily collection starting", extra={"collected_date": str(day)})

        try:
            with self._session_factory() as session, collection_lock(session) as held:
                if not held:
                    # Another node is already collecting today. Standing down is
                    # correct: a second run would double the request volume every
                    # source sees, and that is a compliance problem before it is
                    # a performance one.
                    logger.info(
                        "another node holds the collection lock; standing down",
                        extra={"collected_date": str(day)},
                    )
                    return

                plan = build_daily_plan(session, day)
                if not plan:
                    logger.warning(
                        "no work planned: no source is enabled, or no route is active",
                        extra={"collected_date": str(day)},
                    )
                    return

                collected = self._run_collection(session, plan, day)
                self._compute_index(session, day)
                session.commit()

            logger.info(
                "daily collection finished",
                extra={
                    "collected_date": str(day),
                    "planned": len(plan),
                    "collected": collected,
                    "seconds": round((datetime.now(UTC) - started).total_seconds(), 1),
                },
            )
        except Exception:
            # Deliberately broad. A scheduler that dies on the first bad day is
            # worse than a cron line; the failure is recorded and the next run
            # still happens.
            logger.exception(
                "daily collection failed", extra={"collected_date": str(day)}
            )


def start_scheduler(
    engine: sa.Engine,
    run_collection: Callable[[Session, list[CollectionSpec], date], int],
    compute_index: Callable[[Session, date], object],
    schedule: CollectionSchedule | None = None,
) -> BackgroundScheduler:
    """Start the background scheduler and return it so it can be inspected.

    Returned rather than hidden so ``/api/v1/operations`` can report the next
    fire time. An operator asking "when does it next run?" should not have to
    read the source.
    """
    schedule = schedule or CollectionSchedule()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    job = DailyCollectionJob(factory, run_collection, compute_index)

    scheduler = BackgroundScheduler(timezone=IST)
    scheduler.add_job(
        job,
        trigger=schedule.trigger(),
        id="apix-daily-collection",
        name="Daily airfare collection and index computation",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=schedule.misfire_grace_seconds,
        replace_existing=True,
    )
    scheduler.start()

    next_run = scheduler.get_job("apix-daily-collection").next_run_time
    logger.info("scheduler started", extra={"next_run": str(next_run)})
    return scheduler
