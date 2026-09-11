"""The daily scheduler.

Tests the properties that matter operationally: that a run cannot overlap
itself, that a failure does not kill the schedule, and that missed runs do not
stampede a source we have just stopped talking to.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from collector.scheduler import (
    IST,
    CollectionSchedule,
    DailyCollectionJob,
    build_daily_plan,
    start_scheduler,
)
from schemas.enums import ReviewVerdict
from schemas.models.reference import Source, SourceReview
from tests.support.builders import SeedRefs

DAY = date(2026, 9, 15)


def test_the_plan_is_empty_when_no_source_is_enabled(
    app_session: Session, refs: SeedRefs
) -> None:
    """Sources ship disabled, so a fresh install plans nothing. That is correct."""
    assert build_daily_plan(app_session, DAY) == []


def test_the_plan_covers_every_route_and_bucket_for_an_enabled_source(
    app_session: Session, refs: SeedRefs
) -> None:
    source = app_session.get(Source, refs.sources["indigo_web"])
    assert source is not None
    source.enabled = True
    app_session.flush()

    plan = build_daily_plan(app_session, DAY)
    routes = app_session.execute(sa.select(sa.func.count()).select_from(sa.text("route"))).scalar_one()
    assert len(plan) == routes * 6, "every route x six lead-time buckets"


def test_travel_dates_follow_the_lead_time_buckets(
    app_session: Session, refs: SeedRefs
) -> None:
    """T+21 must be 21 days out, not 'about three weeks'."""
    source = app_session.get(Source, refs.sources["indigo_web"])
    assert source is not None
    source.enabled = True
    app_session.flush()

    plan = build_daily_plan(app_session, DAY)
    for spec in plan:
        assert spec.travel_date == DAY + timedelta(days=spec.lead_time_days)
        assert spec.collected_date == DAY

    assert {s.lead_time_days for s in plan} == {1, 7, 15, 21, 30, 45}


def test_a_disabled_source_is_excluded_from_the_plan(
    app_session: Session, refs: SeedRefs
) -> None:
    """Redundant with the gate, and deliberately so.

    The gate is the guarantee. But generating thousands of requests we know will
    be refused makes the run log unreadable and wastes the loop.
    """
    enabled = app_session.get(Source, refs.sources["indigo_web"])
    assert enabled is not None
    enabled.enabled = True
    app_session.add(
        SourceReview(
            source_id=enabled.id, reviewer="test", reviewed_at=sa.func.now(),
            verdict=ReviewVerdict.APPROVED,
        )
    )
    app_session.flush()

    plan = build_daily_plan(app_session, DAY)
    assert {s.source_code for s in plan} == {"indigo_web"}
    assert "makemytrip" not in {s.source_code for s in plan}


# -- the job -------------------------------------------------------------


def test_a_failing_run_does_not_propagate(app_session: Session) -> None:
    """A scheduler that dies on the first bad day is worse than a cron line."""
    def explode(*args: object, **kwargs: object) -> int:
        raise RuntimeError("source is on fire")

    job = DailyCollectionJob(
        session_factory=lambda: app_session,
        run_collection=explode,
        compute_index=lambda session, day: None,
    )
    job(collected_date=DAY)  # must not raise


def test_a_job_with_nothing_to_do_returns_quietly(app_session: Session) -> None:
    calls: list[str] = []
    job = DailyCollectionJob(
        session_factory=lambda: app_session,
        run_collection=lambda s, p, d: calls.append("collected") or 0,
        compute_index=lambda s, d: calls.append("indexed"),
    )
    job(collected_date=DAY)
    assert calls == [], "no enabled source means no collection and no index"


# -- the schedule --------------------------------------------------------


def test_the_schedule_runs_in_ist() -> None:
    """Collection dates and T+N travel dates are defined in IST.

    Scheduling in UTC would shift which day a "daily" run belongs to.
    """
    assert CollectionSchedule().trigger().timezone.key == "Asia/Kolkata"
    assert IST.key == "Asia/Kolkata"


def test_only_one_run_may_be_in_flight(app_session: Session) -> None:
    """Two runners would double the load on every source and race on query_hash."""
    engine = app_session.get_bind()
    scheduler = start_scheduler(
        engine,  # type: ignore[arg-type]
        run_collection=lambda s, p, d: 0,
        compute_index=lambda s, d: None,
    )
    try:
        job = scheduler.get_job("apix-daily-collection")
        assert job is not None
        assert job.max_instances == 1
        assert job.coalesce is True, "missed runs coalesce rather than stampede"
        assert job.next_run_time is not None
    finally:
        scheduler.shutdown(wait=False)


def test_the_misfire_grace_is_bounded() -> None:
    """A fare collected nine hours late is a different observation.

    Long enough to survive a restart, short enough that a badly-late run is
    skipped rather than recorded as though it were on time.
    """
    schedule = CollectionSchedule()
    assert 0 < schedule.misfire_grace_seconds <= 4 * 3600


@pytest.mark.parametrize("hour", [0, 6, 23])
def test_the_run_hour_is_configurable(hour: int) -> None:
    assert CollectionSchedule(hour=hour).trigger() is not None
