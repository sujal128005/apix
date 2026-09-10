#!/usr/bin/env python
"""Run the whole pipeline end to end and populate the dashboard.

    plan -> compliance gate -> adapter -> raw storage
         -> normalise -> matched pairs -> Jevons short
         -> route index -> headline attempt -> dashboard

Everything on the way through is the real code path. The only thing that is not
real is the *source*: quotes come from ``MockAdapter`` and carry
``SIMULATED_DEMO`` provenance, because no live source is enabled yet.

That has a consequence worth watching for rather than working around. The Phase 3
database trigger refuses to write a HEADLINE index row for any date carrying
simulated observations, so this run will produce route-level indices and **no
headline**. The dashboard will say so. When a real source is enabled in Phase 5,
the headline appears for the first time on genuine observations - which is the
correct order for those two events to happen in.

    .venv/Scripts/python scripts/run_demo_pipeline.py --days 21
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector.adapter import AdapterRequest, AdapterResponse, CollectionSpec
from collector.mock_adapter import MockAdapter
from collector.retry import RetryPolicy
from collector.runner import CollectionRunner
from compliance.config import ComplianceConfig
from compliance.gate import ComplianceGate
from compliance.robots import RobotsCache
from compliance.token import ComplianceToken
from db.settings import DbSettings
from pipeline.normalise import normalise_payload, score_quality
from pipeline.orchestrator import compute_index_for_date
from pipeline.weights import build_equal_weights
from schemas.enums import (
    ImputationCode,
    MissingReason,
    Provenance,
    ReviewVerdict,
)
from schemas.models.collection import RawQuote
from schemas.models.derived import NormalisedQuote
from schemas.models.reference import (
    LeadTimeBucket,
    Route,
    Source,
    SourceReview,
)
from schemas.models.versioning import RouteWeight, WeightSetVersion

# A deterministic price path per route. Real airfares are volatile and
# route-specific; a flat series would make the index look like it works when it
# has simply never been asked to move.
ROUTE_BASE = {
    "DEL-BOM": 5200, "BOM-DEL": 5350, "DEL-BLR": 6100, "BLR-DEL": 6250,
    "DEL-CCU": 5800, "CCU-DEL": 5900, "DEL-MAA": 6400, "MAA-DEL": 6500,
    "DEL-HYD": 5600, "HYD-DEL": 5700, "BOM-BLR": 4300, "BLR-BOM": 4400,
    "BOM-MAA": 4800, "MAA-BOM": 4900, "BLR-HYD": 3400, "HYD-BLR": 3500,
    "BOM-AMD": 3200, "AMD-BOM": 3300, "DEL-GAU": 7100, "GAU-DEL": 7250,
}
BUCKET_MULTIPLIER = {
    "T1": Decimal("2.10"), "T7": Decimal("1.35"), "T15": Decimal("1.10"),
    "T21": Decimal("1.00"), "T30": Decimal("0.95"), "T45": Decimal("0.92"),
}
CARRIER_OFFSET = {
    "6E": Decimal("1.00"), "AI": Decimal("1.12"),
    "SG": Decimal("0.94"), "QP": Decimal("0.97"),
}
CARRIERS = [("6E", "SAVER"), ("AI", "ECOVALUE"), ("SG", "SAVER"), ("QP", "AKASAVALUE")]


def _route_character(route: str) -> tuple[int, Decimal, Decimal]:
    """A stable per-route phase, weekend amplitude and trend.

    Without this every route moves identically, because the same multipliers
    apply everywhere - and twenty identical index values look like hardcoded
    output rather than a working index. Real routes differ: a business corridor
    peaks midweek, a leisure route at weekends, and they do not share a trend.

    Derived from the route code so it is deterministic, not random.
    """
    seed = sum(ord(c) * (i + 1) for i, c in enumerate(route))
    phase = seed % 7
    amplitude = Decimal("0.03") + (Decimal(seed % 9) * Decimal("0.008"))  # 3%..9.4%
    trend = Decimal("0.0015") + (Decimal(seed % 5) * Decimal("0.0018"))   # 0.15%..0.87%/day
    return phase, amplitude, trend


def synthetic_fare(route: str, bucket: str, carrier: str, day: int, seat: int) -> Decimal:
    """A deterministic fare. Same inputs, same rupees, every run.

    Decimal throughout, and not merely to satisfy the no-float rule: this
    function *is* a money path, and the demo claims two runs produce identical
    index values. Computing the inputs in binary floating point while the engine
    computes in exact decimal would make that claim true only by luck.

    Deterministic rather than random for the same reason. Reproducibility is the
    property the project rests on, so its own demo data should have it too.
    """
    phase, amplitude, daily_trend = _route_character(route)
    base = Decimal(ROUTE_BASE.get(route, 5000)) * BUCKET_MULTIPLIER.get(bucket, Decimal("1.00"))
    trend = Decimal("1.00") + (Decimal(day) * daily_trend)
    peak = (day + phase) % 7 in (5, 6)
    weekly = (Decimal("1.00") + amplitude) if peak else Decimal("1.00")
    # A short-lived demand spike, at a different time on each route.
    spike = Decimal("1.11") if (day + phase) % 11 == 3 else Decimal("1.00")
    ladder = Decimal("1.00") + (Decimal(seat) * Decimal("0.035"))
    rupees = base * trend * weekly * spike * CARRIER_OFFSET[carrier] * ladder
    return rupees.quantize(Decimal("0.01"))


def ensure_weight_set(session: Session) -> WeightSetVersion:
    """Create a clearly-labelled rung-4 equal-weight basket if none exists.

    Rung 4 because open item O-5 is unresolved: DGCA publishes city-pair counts
    annually but a public per-city-pair passenger-volume table is not confirmed
    to exist. Equal weighting is a real methodological position, not a
    placeholder pretending to be sourced, and the evidence rung says so beside
    every weight in the UI.
    """
    existing = session.execute(sa.select(WeightSetVersion).limit(1)).scalar_one_or_none()
    if existing is not None:
        return existing

    routes = {r.code: r for r in session.execute(sa.select(Route)).scalars()}
    reason = (
        "Equal weights. Open item O-5 unresolved: no public DGCA per-city-pair "
        "passenger-volume table was found, so no traffic-proportional weighting is "
        "available. Replace with rung 1 or 2 weights when the data is obtained."
    )
    built = build_equal_weights(sorted(routes), version="2026.1-equal-rung4", reason=reason)

    version = WeightSetVersion(
        version=built.version, effective_from=date.today(), source_note=built.note
    )
    session.add(version)
    session.flush()

    for candidate in built.candidates:
        session.add(
            RouteWeight(
                route_id=routes[candidate.route_code].id,
                weight=candidate.weight,
                evidence_rung=candidate.evidence_rung,
                evidence_ref=candidate.evidence_ref,
                evidence_retrieved_at=datetime.now(UTC),
                weight_set_version_id=version.id,
            )
        )
    session.flush()
    print(f"  created weight set {built.version} "
          f"({len(built.candidates)} routes, evidence rung {built.worst_rung})")
    return version


def _offer_json(carrier: str, brand: str, flight: int, fare: Decimal) -> str:
    """One offer, with its fare decomposed.

    Real sources usually disclose base fare, taxes and UDF separately, so the
    demo does too - otherwise every observation would be PARTIAL and the
    component-confidence machinery would never be exercised. One offer in five
    omits the breakdown, which is also realistic and keeps the PARTIAL path
    visible on the dashboard.
    """
    if flight % 5 == 0:
        return (
            f'{{"carrier":"{carrier}","flightNumber":"{carrier}{flight}",'
            f'"totalAmount":"{fare}","currencyCode":"INR","fareBrand":"{brand}","stops":0}}'
        )
    base = (fare * Decimal("0.78")).quantize(Decimal("0.01"))
    taxes = (fare * Decimal("0.16")).quantize(Decimal("0.01"))
    udf = (fare - base - taxes).quantize(Decimal("0.01"))
    return (
        f'{{"carrier":"{carrier}","flightNumber":"{carrier}{flight}",'
        f'"totalAmount":"{fare}","currencyCode":"INR","fareBrand":"{brand}","stops":0,'
        f'"baseFare":"{base}","taxes":"{taxes}","udf":"{udf}"}}'
    )


class CollectionRefusedError(RuntimeError):
    """Every search in a run was refused. Reported loudly, not as an empty day."""


class DemoAdapter(MockAdapter):
    """MockAdapter with a route- and date-aware price path.

    Subclassed here rather than built into MockAdapter: demo pricing is a
    property of this script, not of the test double, and mixing the two would
    put demo behaviour into the code path that tests rely on being boring.
    """

    adapter_key = "mock_v1"

    def __init__(self, day_index: int) -> None:
        super().__init__()
        self.day_index = day_index
        self._spec: CollectionSpec | None = None

    def build_request(self, spec: CollectionSpec) -> AdapterRequest:
        self._spec = spec
        return super().build_request(spec)

    def execute(
        self, request: AdapterRequest, token: ComplianceToken, *, base_url: str
    ) -> AdapterResponse:
        assert self._spec is not None
        spec = self._spec
        offers = ",".join(
            _offer_json(
                carrier,
                brand,
                2000 + seat * 11 + (sum(ord(c) for c in spec.route_code) % 90),
                synthetic_fare(spec.route_code, spec.bucket_code, carrier,
                               self.day_index, seat),
            )
            for seat, (carrier, brand) in enumerate(CARRIERS)
        )
        self.attempts += 1
        self.tokens_seen.append(token)
        self.executed_paths.append(request.path)
        return AdapterResponse(
            body=f'{{"offers": [{offers}]}}',
            http_status=200,
            fetched_at=datetime.now(UTC),
            content_type="application/json",
        )


class _PermissiveRobots:
    """Serves a permissive robots.txt without touching the network.

    Demo mode makes no outbound requests, so robots.txt cannot be fetched for
    real. This is stated rather than hidden: the compliance gate still runs
    every check, still writes a decision row for every request, and still
    refuses anything not enabled and reviewed - only the transport is stubbed.
    """

    # `timeout` is annotated loosely on purpose. It is a duration, not money, but
    # this module also builds fares - so rather than exempt a fare-handling file
    # from the no-float rule for the sake of one unused parameter, the stub
    # simply does not claim a numeric type it ignores.
    def fetch(self, base_url: str, *, user_agent: str, timeout: object):
        return 200, "User-agent: *\nAllow: /\n"


def enable_demo_source(session: Session) -> None:
    """Enable one source with a recorded human review, as the gate requires."""
    source = session.execute(sa.select(Source).where(Source.code == "indigo_web")).scalar_one()
    source.enabled = True
    source.base_url = "https://demo.invalid"
    source.adapter_key = "mock_v1"
    already = session.execute(
        sa.select(SourceReview).where(SourceReview.source_id == source.id).limit(1)
    ).scalar_one_or_none()
    if already is None:
        session.add(
            SourceReview(
                source_id=source.id,
                reviewer="demo-operator",
                reviewed_at=datetime.now(UTC),
                robots_decision="Allow: / (stubbed for offline demo)",
                tos_note="Demo source. No live collection performed.",
                verdict=ReviewVerdict.APPROVED,
            )
        )
    session.flush()


def collect_day(session: Session, obs_date: date, day_index: int) -> tuple[int, int]:
    """Run one day through gate, adapter, raw storage and normalisation."""
    routes = list(session.execute(sa.select(Route)).scalars())
    buckets = list(session.execute(sa.select(LeadTimeBucket)).scalars())
    source = session.execute(sa.select(Source).where(Source.code == "indigo_web")).scalar_one()

    config = ComplianceConfig.from_env()
    gate = ComplianceGate(config, RobotsCache(config, _PermissiveRobots(), write_snapshots=False))

    clock_state = {"t": datetime.combine(obs_date, datetime.min.time(), tzinfo=UTC)}

    def clock() -> datetime:
        clock_state["t"] = clock_state["t"] + timedelta(seconds=30)
        return clock_state["t"]

    adapter = DemoAdapter(day_index)
    runner = CollectionRunner(
        gate,
        {"mock_v1": adapter},
        retry=RetryPolicy(max_attempts=1),
        sleep=lambda _s: None,
        clock=clock,
    )

    plan = [
        CollectionSpec(
            source_id=source.id, source_code=source.code,
            route_id=route.id, route_code=route.code,
            origin=route.code.split("-")[0], destination=route.code.split("-")[1],
            bucket_id=bucket.id, bucket_code=bucket.code,
            lead_time_days=bucket.days,
            travel_date=obs_date + timedelta(days=bucket.days),
            collected_date=obs_date,
        )
        for route in routes
        for bucket in buckets
    ]
    result = runner.run(session, plan, now=clock_state["t"])
    session.flush()

    # A run that collects nothing must say why. Reporting "searches 0" and
    # moving on looks like an empty day rather than a refused one, and the two
    # need entirely different responses from whoever is reading the output.
    if result.collected == 0 and result.outcomes:
        first = result.outcomes[0]
        raise CollectionRefusedError(
            f"All {len(result.outcomes)} searches were refused "
            f"({first.decision_code or first.status}): {first.detail}"
        )

    # raw quotes -> normalised observations, preserving lineage
    written = 0
    lookup = {(s.route_id, s.bucket_id): s for s in plan}
    for outcome in result.outcomes:
        if outcome.status != "COLLECTED" or outcome.raw_response_id is None:
            continue
        spec = lookup[(outcome.spec.route_id, outcome.spec.bucket_id)]
        raws = session.execute(
            sa.select(RawQuote).where(RawQuote.raw_response_id == outcome.raw_response_id)
        ).scalars().all()
        for raw in raws:
            fields = normalise_payload(raw.payload)
            session.add(
                NormalisedQuote(
                    raw_quote_id=raw.id,
                    route_id=spec.route_id,
                    bucket_id=spec.bucket_id,
                    source_id=source.id,
                    carrier=fields.carrier,
                    flight_no=fields.flight_no,
                    lead_time_days=spec.lead_time_days,
                    fare_brand=fields.fare_brand,
                    total_fare=fields.total_fare,
                    currency=fields.currency,
                    collected_at=datetime.combine(obs_date, datetime.min.time(), tzinfo=UTC),
                    collected_date=obs_date,
                    provenance=Provenance.SIMULATED_DEMO,
                    quality_status=fields.quality_status,
                    quality_score=score_quality(fields, provenance=Provenance.SIMULATED_DEMO),
                    imputation_code=ImputationCode.N,
                    missing_reason=MissingReason.NONE,
                    component_confidence=fields.component_confidence,
                )
            )
            written += 1
    session.flush()
    return written, result.collected


def _reset(settings: DbSettings) -> None:
    """Clear demo data using the migrator role.

    The application role cannot do this, and that is deliberate: index
    observations and contributions are append-only, with UPDATE and DELETE
    revoked from ``apix_app`` at the database level. Wiping an audit trail is an
    administrative act, so it needs administrative credentials and a separate
    connection - which is exactly the friction it should have.
    """
    admin = sa.create_engine(
        settings.url(user=settings.migrator_user, password=settings.migrator_password),
        future=True,
    )
    # Order matters: children before parents. The collection chain must go too,
    # or the query_hash uniqueness constraint will correctly refuse to re-issue
    # searches that were already made - idempotency working exactly as designed,
    # and a confusing way to discover it.
    with admin.begin() as connection:
        for table in (
            "index_contribution",
            "index_observation",
            "normalised_quote",
            "raw_quote",
            "raw_response",
            "compliance_decision",
            "collection_request",
            "collection_job",
        ):
            connection.execute(sa.text(f"DELETE FROM {table}"))
    admin.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=21)
    parser.add_argument("--reset", action="store_true", help="clear prior demo data first")
    args = parser.parse_args()

    # The orchestrator logs a warning every time the headline is refused, which
    # is correct behaviour and useless output: it happens on every day of a demo
    # run and buries the per-day report it interleaves with. Said once, in the
    # summary, is enough.
    logging.getLogger("apix.pipeline").setLevel(logging.ERROR)

    settings = DbSettings.from_env()
    engine = sa.create_engine(settings.app_url(), future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    print(f"APIx pipeline run - {args.days} days\n")
    with factory() as session:
        if args.reset:
            _reset(settings)
            print("  cleared prior observations and index values\n")

        ensure_weight_set(session)
        enable_demo_source(session)
        session.commit()

        start = date.today() - timedelta(days=args.days - 1)
        for offset in range(args.days):
            obs_date = start + timedelta(days=offset)
            try:
                written, collected = collect_day(session, obs_date, offset)
            except CollectionRefusedError as refusal:
                session.rollback()
                print(f"\n  {obs_date}  COLLECTION REFUSED")
                print(f"  {refusal}")
                if not ComplianceConfig.from_env().has_contact:
                    print(
                        "\n  APIX_CONTACT_URL is not set. The compliance gate refuses to "
                        "crawl\n  anonymously - every request needs a contact address a site "
                        "operator\n  could reach. Set it and re-run:\n"
                        "\n      $env:APIX_CONTACT_URL=\"https://github.com/you/apix\"\n"
                    )
                return 1
            run = compute_index_for_date(session, obs_date)
            session.commit()

            headline = f"{run.headline:.3f}" if run.headline else "withheld"
            print(
                f"  {obs_date}  searches {collected:3d}  quotes {written:4d}"
                f"  strata {run.strata_total:3d}  routes indexed {run.routes_with_index:2d}"
                f"  headline {headline}"
            )

        print()
        if run.headline_refused_reason:
            print("Headline index: NOT PUBLISHED")
            print(f"  {run.headline_refused_reason}")
        print("\nOpen http://127.0.0.1:8000 to see the result.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
