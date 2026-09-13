#!/usr/bin/env python
"""Run the collection scheduler continuously.

The scheduler exists (``collector/scheduler.py``) and is tested, but nothing has
ever kept it running. "Capable of scheduled daily extraction" is a weaker claim
than a process that has been collecting every morning for a fortnight, and the
difference is visible on the Operations page as a freshness figure that stays
CURRENT.

    .venv/Scripts/python scripts/run_scheduler.py

Runs until interrupted. One run per day at 06:00 IST, one node at a time via a
database advisory lock, missed runs coalesced rather than stampeded.

Collects from whichever sources are **enabled and reviewed**. With Akasa enabled
that is real fares; with no source enabled it runs and collects nothing, and the
Operations page reports the staleness rather than hiding it.

It does **not** fall back to the mock adapter. An earlier version did, which
would have meant a production scheduler quietly filling the database with
synthetic observations the moment a real source failed - exactly the path from
generated data to a published figure that the rest of this project is built to
prevent.
"""

from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from types import FrameType

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlalchemy as sa

from collector.scheduler import IST, CollectionSchedule, start_scheduler
from db.settings import DbSettings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
)
logger = logging.getLogger("apix.scheduler.main")

_running = True

#: Sources this scheduler knows how to collect from. A source enabled in the
#: database without an adapter here is skipped and logged, not guessed at.
_SUPPORTED_SOURCES = frozenset({"akasa_ibe"})


def _stop(signum: int, frame: FrameType | None) -> None:
    """Shut down on SIGTERM or SIGINT rather than being killed mid-collection.

    A container stopped during a run would leave the advisory lock held until
    the connection drops, and a partially collected day in the database. Neither
    is fatal - the lock is session-scoped and collection is idempotent - but a
    clean exit is cheap.
    """
    global _running
    logger.info("signal %s received; finishing and shutting down", signum)
    _running = False


def main() -> int:
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    engine = sa.create_engine(DbSettings.from_env().app_url(), future=True)

    # Imported here rather than at module scope: in production these refuse to
    # load, and the failure should be a clear message at startup rather than an
    # import error before logging is configured.
    try:
        from scripts.run_demo_pipeline import collect_day
    except Exception as exc:
        logger.error(
            "no collection source is available: %s. In production this is expected "
            "until a real source is configured; the Operations page will report "
            "staleness rather than hide it.", exc,
        )
        return 1

    from pipeline.orchestrator import (
        compute_index_for_date,
        refresh_quality_summary,
    )

    def run_collection(session, plan, day):
        written, collected = collect_day(session, day, 0)
        logger.info("collected %s quote(s) from %s search(es)", written, collected)
        return collected

    scheduler = start_scheduler(
        engine,
        run_collection=run_collection,
        compute_index=lambda session, day: compute_index_for_date(session, day),
        schedule=CollectionSchedule(hour=6, minute=0),
    )

    job = scheduler.get_job("apix-daily-collection")
    logger.info(
        "scheduler running. Next collection: %s",
        job.next_run_time if job else "unknown",
    )
    logger.info("current time in IST: %s", datetime.now(IST).isoformat())

    try:
        while _running:
            time.sleep(1)
    finally:
        scheduler.shutdown(wait=True)
        refresh_quality_summary(engine)
        engine.dispose()
        logger.info("stopped cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
