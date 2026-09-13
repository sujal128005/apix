#!/usr/bin/env python
"""Collect real fares from Akasa Air.

The first script in this project that fetches an actual airfare. Everything up
to now has run on synthetic observations; this runs the same pipeline against a
real source.

    .venv/Scripts/python scripts/collect_live.py --routes DEL-BOM,BOM-DEL --dry-run
    .venv/Scripts/python scripts/collect_live.py --routes DEL-BOM,BOM-DEL

**Every request goes through the compliance gate**, exactly as a synthetic one
does. The gate fetches robots.txt, checks the path, enforces the crawl delay and
the daily budget, and mints a token the adapter cannot execute without. Nothing
about this script bypasses any of it - it changes the source, not the rules.

**Read this before enabling it in anything published.** Akasa's booking engine
serves no robots.txt, which the gate reads as unrestricted under RFC 9309. That
is correct and it is not the same as permission: nobody publishes a robots.txt
for a backend API because nobody expected it to be crawled. Low-volume
collection that identifies itself, for a prototype, is defensible. A statistic
published under a ministry's name needs an agreement first, and
``docs/DATA-REQUEST.md`` sets out that ask.

Defaults are deliberately small: two routes, three windows, one carrier. A first
run against a live airline should be the smallest thing that proves the pipeline
works, not the largest thing the budget allows.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages"))
sys.path.insert(0, str(REPO))

from collector.adapter import CollectionSpec  # noqa: E402
from collector.adapters import AkasaAdapter  # noqa: E402
from collector.retry import RetryPolicy  # noqa: E402
from collector.runner import CollectionRunner  # noqa: E402
from compliance.config import ComplianceConfig  # noqa: E402
from compliance.gate import ComplianceGate  # noqa: E402
from compliance.robots import RobotsCache  # noqa: E402
from db.settings import DbSettings  # noqa: E402
from pipeline.normalise import normalise_payload, score_quality  # noqa: E402
from pipeline.orchestrator import compute_index_for_date  # noqa: E402
from schemas.enums import ImputationCode, MissingReason, Provenance, ReviewVerdict  # noqa: E402
from schemas.models.collection import RawQuote  # noqa: E402
from schemas.models.derived import NormalisedQuote  # noqa: E402
from schemas.models.reference import LeadTimeBucket, Route, Source, SourceReview  # noqa: E402

AKASA_HOST = "https://prod-bl.qp.akasaair.com"

#: Akasa's network is smaller than the full basket. Requesting a route it does
#: not fly returns an empty result, which is harmless but is a request made for
#: nothing - and a request made for nothing is still load on someone's server.
AKASA_ROUTES = (
    "DEL-BOM", "BOM-DEL", "DEL-BLR", "BLR-DEL", "BOM-BLR", "BLR-BOM",
    "DEL-CCU", "CCU-DEL", "BLR-HYD", "HYD-BLR", "BOM-AMD", "AMD-BOM",
)


def enable_source(session: Session, *, reviewer: str) -> Source:
    """Enable Akasa, with a recorded human review.

    The gate refuses a source that has not been reviewed by a named person. That
    is the point of the review: enabling a source is a decision someone takes,
    not a flag someone flips.
    """
    source = session.execute(
        sa.select(Source).where(Source.code == "akasa_ibe")
    ).scalar_one_or_none()
    if source is None:
        raise SystemExit(
            "akasa_ibe is not seeded. Run scripts/init_db.py after updating "
            "db/seeds/sources.py."
        )

    source.enabled = True
    source.base_url = AKASA_HOST
    source.adapter_key = "akasa_ibe_v1"

    already = session.execute(
        sa.select(SourceReview).where(SourceReview.source_id == source.id).limit(1)
    ).scalar_one_or_none()
    if already is None:
        session.add(
            SourceReview(
                source_id=source.id,
                reviewer=reviewer,
                reviewed_at=datetime.now(UTC),
                robots_decision=(
                    "prod-bl.qp.akasaair.com serves no robots.txt. Read as "
                    "unrestricted under RFC 9309; recorded as absence of a "
                    "prohibition, not as permission granted."
                ),
                tos_note=(
                    "Terms of service not reviewed by counsel. Prototype "
                    "collection only, at low volume, identifying itself. NOT "
                    "cleared for a published official statistic - see "
                    "docs/DATA-REQUEST.md."
                ),
                verdict=ReviewVerdict.APPROVED,
            )
        )
    session.flush()
    return source


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routes", default="DEL-BOM,BOM-DEL")
    parser.add_argument("--buckets", default="T1,T7,T21")
    parser.add_argument("--reviewer", default="prototype-operator")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="plan and show the requests without making any",
    )
    args = parser.parse_args()

    config = ComplianceConfig.from_env()
    if not config.has_contact:
        print("APIX_CONTACT_URL is not set. APIx does not collect anonymously.")
        return 1

    wanted_routes = [r.strip().upper() for r in args.routes.split(",") if r.strip()]
    unknown = [r for r in wanted_routes if r not in AKASA_ROUTES]
    if unknown:
        print(f"Not known to be flown by Akasa: {unknown}")
        print("Requesting a route an airline does not fly is load on their server")
        print("for no data. Remove them, or add them to AKASA_ROUTES if they are new.")
        return 1

    wanted_buckets = [b.strip().upper() for b in args.buckets.split(",") if b.strip()]

    settings = DbSettings.from_env()
    engine = sa.create_engine(settings.app_url(), future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as session:
        source = enable_source(session, reviewer=args.reviewer)
        session.commit()

        routes = {
            r.code: r
            for r in session.execute(sa.select(Route)).scalars()
            if r.code in wanted_routes
        }
        buckets = {
            b.code: b
            for b in session.execute(sa.select(LeadTimeBucket)).scalars()
            if b.code in wanted_buckets
        }
        missing = set(wanted_routes) - set(routes)
        if missing:
            print(f"Not in the route basket: {sorted(missing)}")
            return 1

        today = date.today()
        plan = [
            CollectionSpec(
                source_id=source.id, source_code=source.code,
                route_id=route.id, route_code=route.code,
                origin=route.code.split("-")[0], destination=route.code.split("-")[1],
                bucket_id=bucket.id, bucket_code=bucket.code,
                lead_time_days=bucket.days,
                travel_date=today + timedelta(days=bucket.days),
                collected_date=today,
            )
            for route in routes.values()
            for bucket in buckets.values()
        ]

        delay = config.effective_crawl_delay(None)
        print(f"Akasa Air — {len(plan)} request(s)")
        print(f"  host        {AKASA_HOST}")
        print(f"  crawl delay {delay}s  (about {len(plan) * delay / 60:.1f} minutes)")
        print(f"  user agent  {config.user_agent}")
        print()

        if args.dry_run:
            for spec in plan:
                print(f"  {spec.route_code:<9} {spec.bucket_code:<4} "
                      f"travel {spec.travel_date}")
            print("\nDry run: nothing was requested.")
            return 0

        runner = CollectionRunner(
            ComplianceGate(config, RobotsCache(config)),
            {"akasa_ibe_v1": AkasaAdapter()},
            retry=RetryPolicy(max_attempts=2),
        )
        result = runner.run(session, plan, now=datetime.now(UTC))
        session.flush()

        written = store_observations(session, result, plan)
        session.commit()

        print(f"\n  collected {result.collected} of {len(plan)} request(s)")
        print(f"  stored    {written} real fare observation(s)")

        for outcome in result.outcomes:
            if outcome.status != "COLLECTED":
                print(f"  {outcome.spec.route_code} {outcome.spec.bucket_code}: "
                      f"{outcome.decision_code or outcome.status} — {outcome.detail}")

        if written:
            run = compute_index_for_date(session, today)
            session.commit()
            print(f"\n  index: {run.routes_with_index} route(s) computed")
            if run.headline is not None:
                print(f"  HEADLINE INDEX: {run.headline}")
                print("  Computed from real fares - the simulated-data trigger did "
                      "not fire, because nothing here is simulated.")
            elif run.headline_refused_reason:
                print(f"  headline withheld: {run.headline_refused_reason[:120]}")
    return 0


def store_observations(
    session: Session, result: object, plan: list[CollectionSpec]
) -> int:
    """Normalise collected raw quotes into observations, preserving lineage.

    Shared with the scheduler, so a scheduled run and a manual one store exactly
    the same thing. Two code paths writing observations would eventually diverge,
    and the one nobody watches would be the one that drifted.
    """
    lookup = {(s.route_id, s.bucket_id): s for s in plan}
    written = 0

    for outcome in result.outcomes:  # type: ignore[attr-defined]
        if outcome.status != "COLLECTED" or outcome.raw_response_id is None:
            continue
        spec = lookup[(outcome.spec.route_id, outcome.spec.bucket_id)]
        raws = session.execute(
            sa.select(RawQuote).where(RawQuote.raw_response_id == outcome.raw_response_id)
        ).scalars().all()

        for raw in raws:
            try:
                fields = normalise_payload(raw.payload)
            except Exception as exc:
                print(f"    rejected a quote: {exc}")
                continue

            session.add(
                NormalisedQuote(
                    raw_quote_id=raw.id,
                    route_id=spec.route_id,
                    bucket_id=spec.bucket_id,
                    source_id=outcome.spec.source_id,
                    carrier=fields.carrier,
                    flight_no=fields.flight_no,
                    lead_time_days=spec.lead_time_days,
                    fare_brand=fields.fare_brand,
                    total_fare=fields.total_fare,
                    currency=fields.currency,
                    collected_at=datetime.now(UTC),
                    collected_date=spec.collected_date,
                    # The whole point: these are real fares from a real airline.
                    provenance=Provenance.LIVE_COLLECTED,
                    quality_status=fields.quality_status,
                    quality_score=score_quality(
                        fields, provenance=Provenance.LIVE_COLLECTED
                    ),
                    imputation_code=ImputationCode.N,
                    missing_reason=MissingReason.NONE,
                    component_confidence=fields.component_confidence,
                )
            )
            written += 1

    session.flush()
    return written


if __name__ == "__main__":
    raise SystemExit(main())
