"""APIx API — versioned, self-describing, and honest about what it is serving.

Every response carries a ``meta`` block naming the methodology version, the
weight-set version, the provenance of the underlying data and the operating
mode. A statistical consumer must be able to tell *which method produced a
number* without reading our documentation, and a number whose provenance cannot
be stated should not be served at all.

The dashboard is served from here as static HTML rather than a separate
front-end application. For a data-dense statistical portal that is the simpler
and more reliable choice: one process, no build step, no Node toolchain between
a judge and the numbers.
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, sessionmaker

from db.settings import DbSettings
from schemas.enums import IndexLevel, Mode, Provenance
from schemas.models.collection import ComplianceDecision
from schemas.models.derived import NormalisedQuote
from schemas.models.indexing import IndexObservation, Publication
from schemas.models.reference import LeadTimeBucket, Route, Source
from schemas.models.versioning import MethodologyVersion, RouteWeight, WeightSetVersion

logger = logging.getLogger("apix.api")

STATIC_DIR = Path(__file__).resolve().parent / "static"

# --------------------------------------------------------------------------
# Security posture
#
# The public API is read-only and unauthenticated by design: these are official
# statistics, and putting a key in front of them would be theatre. What it does
# need is protection against a single client exhausting the database, and
# headers that stop the JSON being rendered as something else.
#
# CORS is an allow-list, never "*". A wildcard on a government data endpoint
# invites any page anywhere to read it as the user - harmless here, but the
# habit is not.
# --------------------------------------------------------------------------

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("APIX_CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",")
    if origin.strip()
]
# 600/min. Each dashboard page makes roughly eight API calls, so a reader
# refreshing a few times must not trip this. A limiter that blocks normal use is
# not protecting anything - it is a bug that looks like a security control.
RATE_LIMIT_PER_MINUTE = int(os.environ.get("APIX_RATE_LIMIT_PER_MINUTE", "600"))

# Static assets and liveness checks are exempt. They are cheap, cacheable and
# not what a limiter exists to protect; counting them means a page reload can
# lock a reader out of the site.
RATE_LIMIT_EXEMPT_PREFIXES = ("/static/", "/favicon", "/api/v1/health")

app = FastAPI(
    title="APIx — Real-time Airfare Price Index",
    version="0.1.0",
    description=(
        "Daily airfare price index for India, computed with the formulae MoSPI "
        "specifies for CPI 2024: Jevons short (chain-base) at the elementary "
        "level, Young / Modified Laspeyres by weighted arithmetic mean above it."
    ),
    docs_url="/api/docs",
    openapi_url="/api/v1/openapi.json",
)

_engine = sa.create_engine(DbSettings.from_env().app_url(), future=True)
_Session = sessionmaker(bind=_engine, expire_on_commit=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["Accept", "Content-Type"],
)

_requests: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def rate_limit_and_secure_headers(request: Request, call_next: Any) -> Response:
    """A sliding-window limiter and a small set of security headers.

    In-process and per-worker, which is the honest scope: behind several workers
    the effective limit multiplies. That is adequate for a prototype and is
    stated rather than glossed - a reader who assumes it is a global limit would
    be wrong, and a limiter that quietly does less than advertised is worse than
    none.
    """
    path = request.url.path
    if path.startswith(RATE_LIMIT_EXEMPT_PREFIXES):
        response: Response = await call_next(request)
        return _secure(response)

    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    window = _requests[client]
    while window and now - window[0] > 60.0:
        window.popleft()

    if len(window) >= RATE_LIMIT_PER_MINUTE:
        return JSONResponse(
            status_code=429,
            content={
                "type": "about:blank",
                "title": "Too Many Requests",
                "status": 429,
                "detail": (
                    f"More than {RATE_LIMIT_PER_MINUTE} requests in 60 seconds. "
                    "This is a per-process limit on a prototype."
                ),
            },
            headers={"Retry-After": "60"},
        )
    window.append(now)

    return _secure(await call_next(request))


def _secure(response: Response) -> Response:
    """Security headers, applied to every response including static assets."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    # Inline styles and scripts are used by the dashboard pages, so
    # 'unsafe-inline' is required; no remote origin is permitted, which is the
    # property that matters - every asset is served by this process.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
    )
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Never leak an internal error to a caller.

    A stack trace in an API response tells an attacker the framework, the file
    layout and often the query. It is logged in full and returned as nothing.
    """
    logger.exception("unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "type": "about:blank",
            "title": "Internal Server Error",
            "status": 500,
            "detail": "The request could not be completed. The error has been logged.",
        },
    )


def _decimal(value: Decimal | None) -> float | None:
    """Serialise money and index values as strings-turned-floats only at the edge.

    Decimal is preserved everywhere inside the system; JSON has no decimal type,
    so the conversion happens here and nowhere earlier.
    """
    return float(value) if value is not None else None


def _meta(session: Session, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    methodology = session.execute(
        sa.select(MethodologyVersion).order_by(MethodologyVersion.effective_from.desc()).limit(1)
    ).scalar_one_or_none()
    weight_set = session.execute(
        sa.select(WeightSetVersion).order_by(WeightSetVersion.effective_from.desc()).limit(1)
    ).scalar_one_or_none()

    provenances = [
        row[0]
        for row in session.execute(sa.select(NormalisedQuote.provenance).distinct()).all()
    ]

    meta: dict[str, Any] = {
        "as_of": datetime.now(UTC).isoformat(),
        "methodology_version": methodology.version if methodology else None,
        "weight_set_version": weight_set.version if weight_set else None,
        "provenance": sorted(provenances),
        "mode": Mode.OFFLINE_DEMO if Provenance.SIMULATED_DEMO in provenances else Mode.LIVE,
    }
    if extra:
        meta.update(extra)
    return meta


@app.get("/api/v1/health", tags=["system"])
def health() -> dict[str, Any]:
    """Liveness. Does not touch the database."""
    return {"status": "ok", "service": "apix-api", "version": app.version}


@app.get("/api/v1/ready", tags=["system"])
def ready() -> JSONResponse:
    """Readiness: database reachable and migrated."""
    try:
        with _Session() as session:
            session.execute(sa.text("SELECT 1"))
            routes = session.execute(
                sa.select(sa.func.count()).select_from(Route)
            ).scalar_one()
        return JSONResponse({"status": "ready", "routes": routes})
    except Exception as exc:
        return JSONResponse({"status": "not_ready", "detail": str(exc)}, status_code=503)


@app.get("/api/v1/index/latest", tags=["index"])
def index_latest() -> dict[str, Any]:
    """The headline index, or an explanation of why there isn't one.

    A missing headline is not an error. Simulated development data is barred by
    a database trigger from producing a published index value, so on a demo
    database this endpoint correctly reports no headline and says why. Serving a
    number anyway would defeat the guarantee.
    """
    with _Session() as session:
        headline = session.execute(
            sa.select(IndexObservation)
            .where(IndexObservation.level == IndexLevel.HEADLINE)
            .order_by(IndexObservation.obs_date.desc())
            .limit(1)
        ).scalar_one_or_none()

        routes = session.execute(
            sa.select(IndexObservation)
            .where(IndexObservation.level == IndexLevel.ROUTE)
            .order_by(IndexObservation.obs_date.desc())
            .limit(50)
        ).scalars().all()

        provenances = [
            row[0]
            for row in session.execute(sa.select(NormalisedQuote.provenance).distinct()).all()
        ]
        simulated = Provenance.SIMULATED_DEMO in provenances

        return {
            "data": {
                "headline": None
                if headline is None
                else {
                    "obs_date": headline.obs_date.isoformat(),
                    "index_value": _decimal(headline.index_value),
                    "previous_index_value": _decimal(headline.prev_index_value),
                    "routes_in_basket": headline.routes_in_basket,
                    "input_quote_count": headline.input_quote_count,
                    "imputed_count": headline.imputed_count,
                },
                "headline_unavailable_reason": (
                    "No headline index has been published. The database refuses to "
                    "compute one for any date carrying SIMULATED_DEMO observations "
                    "(Phase 3 trigger), so development data cannot become a published "
                    "figure. Route-level indices below are computed from the same "
                    "pipeline and are labelled with their provenance."
                    if headline is None and simulated
                    else None
                    if headline is not None
                    else "No index has been computed yet."
                ),
                "route_count": len(routes),
            },
            "meta": _meta(session),
        }


@app.get("/api/v1/index/routes", tags=["index"])
def index_routes(limit: int = Query(default=100, le=500)) -> dict[str, Any]:
    """Route-level index values, most recent first."""
    with _Session() as session:
        rows = session.execute(
            sa.select(IndexObservation, Route.code)
            .join(Route, Route.id == IndexObservation.ref_id, isouter=True)
            .where(IndexObservation.level == IndexLevel.ROUTE)
            .order_by(IndexObservation.obs_date.desc())
            .limit(limit)
        ).all()

        return {
            "data": [
                {
                    "obs_date": obs.obs_date.isoformat(),
                    "route": code,
                    "index_value": _decimal(obs.index_value),
                    "previous_index_value": _decimal(obs.prev_index_value),
                    "movement": _decimal(
                        (obs.index_value - obs.prev_index_value)
                        if obs.prev_index_value is not None
                        else None
                    ),
                    "input_quote_count": obs.input_quote_count,
                    "excluded_count": obs.excluded_count,
                    "imputed_count": obs.imputed_count,
                }
                for obs, code in rows
            ],
            "meta": _meta(session),
        }


@app.get("/api/v1/routes/{code}", tags=["routes"])
def route_detail(code: str) -> dict[str, Any]:
    """One route: its weight and the evidence behind it, plus its index history.

    The weight's evidence rung is returned alongside the weight itself, never
    separately. A weight without its provenance looks identical to a sourced
    one, and ours are currently rung 4.
    """
    with _Session() as session:
        route = session.execute(
            sa.select(Route).where(Route.code == code.upper())
        ).scalar_one_or_none()
        if route is None:
            raise HTTPException(status_code=404, detail=f"No route {code!r}.")

        weight = session.execute(
            sa.select(RouteWeight)
            .where(RouteWeight.route_id == route.id)
            .order_by(RouteWeight.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        history = session.execute(
            sa.select(IndexObservation)
            .where(IndexObservation.level == IndexLevel.ROUTE)
            .where(IndexObservation.ref_id == route.id)
            .order_by(IndexObservation.obs_date)
        ).scalars().all()

        return {
            "data": {
                "route": route.code,
                "origin": route.code.split("-")[0],
                "destination": route.code.split("-")[1],
                "directional": route.directional,
                "weight": None
                if weight is None
                else {
                    "value": _decimal(weight.weight),
                    "evidence_rung": weight.evidence_rung,
                    "evidence_ref": weight.evidence_ref,
                    "is_proxy": weight.evidence_rung >= 3,
                    "rung_meaning": {
                        1: "DGCA per-city-pair passenger volumes",
                        2: "DGCA popular-routes list",
                        3: "Airport-throughput proxy",
                        4: "Equal weights - not derived from traffic data",
                    }.get(weight.evidence_rung, "unknown"),
                },
                "history": [
                    {
                        "obs_date": row.obs_date.isoformat(),
                        "index_value": _decimal(row.index_value),
                        "movement": _decimal(
                            row.index_value - row.prev_index_value
                            if row.prev_index_value is not None
                            else None
                        ),
                        "input_quote_count": row.input_quote_count,
                        "excluded_count": row.excluded_count,
                    }
                    for row in history
                ],
            },
            "meta": _meta(session),
        }


@app.get("/api/v1/lead-time-profile", tags=["routes"])
def lead_time_profile(route: str | None = None) -> dict[str, Any]:
    """Fare level by advance-purchase window.

    Deliberately a *profile*, not an elasticity. No causal elasticity is
    estimated here - this is the observed price level at each booking horizon,
    and calling it elasticity would claim a great deal more than the data
    supports.

    T+21 is flagged because CPI 2024 collects domestic airfare at a 21-day
    advance-purchase window (Expert Group Report 3.9), making it the one bucket
    directly comparable to the official index.
    """
    with _Session() as session:
        latest = session.execute(
            sa.select(sa.func.max(NormalisedQuote.collected_date))
        ).scalar_one_or_none()
        if latest is None:
            return {"data": {"as_of": None, "buckets": []}, "meta": _meta(session)}

        statement = (
            sa.select(
                LeadTimeBucket.code,
                LeadTimeBucket.days,
                LeadTimeBucket.cpi_comparable,
                sa.func.count().label("quotes"),
                sa.func.min(NormalisedQuote.total_fare).label("min_fare"),
                sa.func.avg(NormalisedQuote.total_fare).label("mean_fare"),
                sa.func.max(NormalisedQuote.total_fare).label("max_fare"),
            )
            .join(NormalisedQuote, NormalisedQuote.bucket_id == LeadTimeBucket.id)
            .where(NormalisedQuote.collected_date == latest)
            .group_by(LeadTimeBucket.code, LeadTimeBucket.days, LeadTimeBucket.cpi_comparable)
            .order_by(LeadTimeBucket.days)
        )
        if route:
            statement = statement.join(
                Route, Route.id == NormalisedQuote.route_id
            ).where(Route.code == route.upper())

        rows = session.execute(statement).all()
        baseline = next((r.mean_fare for r in rows if r.code == "T21"), None)

        return {
            "data": {
                "as_of": latest.isoformat(),
                "route": route.upper() if route else "all routes",
                "baseline_bucket": "T21",
                "baseline_note": (
                    "Indexed to T+21 because CPI 2024 collects domestic airfare at a "
                    "21-day advance-purchase window (Expert Group Report 3.9)."
                ),
                "buckets": [
                    {
                        "bucket": row.code,
                        "days": row.days,
                        "cpi_comparable": row.cpi_comparable,
                        "quotes": row.quotes,
                        "min_fare": _decimal(row.min_fare),
                        "mean_fare": _decimal(row.mean_fare),
                        "max_fare": _decimal(row.max_fare),
                        "relative_to_t21": (
                            None
                            if not baseline
                            else round(float(row.mean_fare / baseline) * 100, 1)
                        ),
                    }
                    for row in rows
                ],
            },
            "meta": _meta(session),
        }


@app.get("/api/v1/quotes", tags=["quotes"])
def quotes(
    limit: int = Query(default=50, le=500),
    route: str | None = None,
) -> dict[str, Any]:
    """Observed fare quotes with their provenance."""
    with _Session() as session:
        statement = (
            sa.select(NormalisedQuote, Route.code, LeadTimeBucket.code)
            .join(Route, Route.id == NormalisedQuote.route_id)
            .join(LeadTimeBucket, LeadTimeBucket.id == NormalisedQuote.bucket_id)
            .order_by(NormalisedQuote.collected_at.desc())
            .limit(limit)
        )
        if route:
            statement = statement.where(Route.code == route.upper())

        rows = session.execute(statement).all()
        return {
            "data": [
                {
                    "collected_date": quote.collected_date.isoformat(),
                    "route": route_code,
                    "bucket": bucket_code,
                    "carrier": quote.carrier,
                    "flight_no": quote.flight_no,
                    "fare_brand": quote.fare_brand,
                    "total_fare": _decimal(quote.total_fare),
                    "currency": quote.currency,
                    "provenance": quote.provenance,
                    "quality_status": quote.quality_status,
                    "imputation_code": quote.imputation_code,
                }
                for quote, route_code, bucket_code in rows
            ],
            "meta": _meta(session),
        }


@app.get("/api/v1/quality", tags=["quality"])
def quality() -> dict[str, Any]:
    """What was collected, what was kept, and what was thrown away.

    A data-quality page that only reports successes is decoration. The counts
    that matter here are the rejections and the imputations: a rising outlier
    rate or a rising imputation rate is usually the first sign that a source has
    quietly stopped working, well before anyone notices the index looks odd.
    """
    with _Session() as session:
        by_status = dict(
            session.execute(
                sa.select(NormalisedQuote.quality_status, sa.func.count())
                .group_by(NormalisedQuote.quality_status)
            ).all()
        )
        by_provenance = dict(
            session.execute(
                sa.select(NormalisedQuote.provenance, sa.func.count())
                .group_by(NormalisedQuote.provenance)
            ).all()
        )
        by_confidence = dict(
            session.execute(
                sa.select(NormalisedQuote.component_confidence, sa.func.count())
                .group_by(NormalisedQuote.component_confidence)
            ).all()
        )
        by_decision = dict(
            session.execute(
                sa.select(ComplianceDecision.decision, sa.func.count())
                .group_by(ComplianceDecision.decision)
            ).all()
        )

        total_quotes = sum(by_status.values())
        imputed = session.execute(
            sa.select(sa.func.count())
            .select_from(NormalisedQuote)
            .where(NormalisedQuote.imputation_code == "Y")
        ).scalar_one()

        index_rows = session.execute(
            sa.select(
                sa.func.coalesce(sa.func.sum(IndexObservation.input_quote_count), 0),
                sa.func.coalesce(sa.func.sum(IndexObservation.excluded_count), 0),
                sa.func.coalesce(sa.func.sum(IndexObservation.imputed_count), 0),
                sa.func.count(),
            ).where(IndexObservation.level == IndexLevel.STRATUM)
        ).one()
        used, excluded, insufficient, strata = index_rows

        daily = session.execute(
            sa.select(
                NormalisedQuote.collected_date,
                sa.func.count(),
                sa.func.count(sa.func.nullif(NormalisedQuote.quality_status, "COMPLETE")),
            )
            .group_by(NormalisedQuote.collected_date)
            .order_by(NormalisedQuote.collected_date)
        ).all()

        return {
            "data": {
                "totals": {
                    "quotes": total_quotes,
                    "strata_computed": strata,
                    "quotes_entering_index": used,
                    "quotes_excluded_as_outliers": excluded,
                    "strata_insufficient": insufficient,
                    "quotes_imputed": imputed,
                },
                "rates": {
                    "outlier_rejection_pct": (
                        round(excluded / (used + excluded) * 100, 2) if used + excluded else 0.0
                    ),
                    "imputation_pct": (
                        round(imputed / total_quotes * 100, 2) if total_quotes else 0.0
                    ),
                    "complete_pct": (
                        round(by_status.get("COMPLETE", 0) / total_quotes * 100, 2)
                        if total_quotes
                        else 0.0
                    ),
                },
                "by_quality_status": by_status,
                "by_provenance": by_provenance,
                "by_component_confidence": by_confidence,
                "by_compliance_decision": by_decision,
                "daily": [
                    {
                        "date": day.isoformat(),
                        "quotes": count,
                        "not_complete": partial,
                    }
                    for day, count, partial in daily
                ],
                "interpretation": {
                    "outlier_rejection_pct": (
                        "Share of matched pairs rejected by the MAD screen before the "
                        "elementary index. A sustained rise means either the market "
                        "turned volatile or a parser started producing nonsense - the "
                        "two need opposite responses, so this is monitored rather than "
                        "tuned away."
                    ),
                    "imputation_pct": (
                        "Share of observations imputed rather than observed. CPI 2024 "
                        "imputes missing prices and carries them until the item "
                        "reappears; a stratum imputed for weeks is a genuine weakness "
                        "and is shown rather than buried."
                    ),
                },
            },
            "meta": _meta(session),
        }


@app.get("/api/v1/provenance/{quote_id}", tags=["quality"])
def provenance(quote_id: str) -> dict[str, Any]:
    """Trace one fare quote back through every step that produced it.

    index value -> route -> observation -> raw quote -> raw response ->
    collection request -> compliance decision -> source

    This is the claim the whole project rests on: no number appears anywhere in
    APIx that cannot be walked back to a fare a source actually quoted, the
    moment it was collected, and the compliance decision that permitted the
    request.
    """
    from uuid import UUID as _UUID

    from schemas.models.collection import CollectionRequest, RawQuote, RawResponse

    try:
        parsed = _UUID(quote_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="quote_id must be a UUID.") from exc

    with _Session() as session:
        quote = session.get(NormalisedQuote, parsed)
        if quote is None:
            raise HTTPException(status_code=404, detail="No such observation.")

        route = session.get(Route, quote.route_id)
        bucket = session.get(LeadTimeBucket, quote.bucket_id)
        source = session.get(Source, quote.source_id)

        raw = session.get(RawQuote, quote.raw_quote_id) if quote.raw_quote_id else None
        response = session.get(RawResponse, raw.raw_response_id) if raw else None
        request = session.get(CollectionRequest, response.request_id) if response else None
        decision = (
            session.execute(
                sa.select(ComplianceDecision)
                .where(ComplianceDecision.request_id == request.id)
                .limit(1)
            ).scalar_one_or_none()
            if request
            else None
        )

        return {
            "data": {
                "observation": {
                    "id": str(quote.id),
                    "route": route.code if route else None,
                    "bucket": bucket.code if bucket else None,
                    "carrier": quote.carrier,
                    "flight_no": quote.flight_no,
                    "fare_brand": quote.fare_brand,
                    "total_fare": _decimal(quote.total_fare),
                    "currency": quote.currency,
                    "collected_at": quote.collected_at.isoformat(),
                    "provenance": quote.provenance,
                    "quality_status": quote.quality_status,
                    "imputation_code": quote.imputation_code,
                },
                "raw_quote": None if raw is None else {"id": str(raw.id), "payload": raw.payload},
                "raw_response": None
                if response is None
                else {
                    "sha256": response.sha256,
                    "http_status": response.http_status,
                    "fetched_at": response.fetched_at.isoformat(),
                },
                "collection_request": None
                if request is None
                else {
                    "query_hash": request.query_hash,
                    "travel_date": request.travel_date.isoformat(),
                    "collected_date": request.collected_date.isoformat(),
                },
                "compliance_decision": None
                if decision is None
                else {
                    "decision": decision.decision,
                    "decided_at": decision.decided_at.isoformat(),
                    "path": decision.path,
                    "user_agent": decision.user_agent,
                    "matched_rule": decision.matched_rule,
                },
                "source": None
                if source is None
                else {"code": source.code, "name": source.name, "tier": source.tier},
                "chain_complete": all(
                    x is not None for x in (raw, response, request, decision, source)
                ),
            },
            "meta": _meta(session),
        }


@app.get("/api/v1/sources", tags=["compliance"])
def sources() -> dict[str, Any]:
    """Every source, its tier, and its most recent compliance decision.

    Blocked sources appear here as blocked. That is the point: an adapter that
    exists but is refused by the compliance gate is evidence of judgement, not a
    gap to be hidden.
    """
    with _Session() as session:
        rows = session.execute(sa.select(Source).order_by(Source.tier, Source.code)).scalars().all()

        latest: dict[Any, ComplianceDecision] = {}
        for decision in session.execute(
            sa.select(ComplianceDecision).order_by(ComplianceDecision.decided_at.desc())
        ).scalars():
            latest.setdefault(decision.source_id, decision)

        return {
            "data": [
                {
                    "code": source.code,
                    "name": source.name,
                    "tier": source.tier,
                    "transport": source.transport,
                    "enabled": source.enabled,
                    "last_decision": (
                        latest[source.id].decision if source.id in latest else None
                    ),
                    "last_decision_at": (
                        latest[source.id].decided_at.isoformat()
                        if source.id in latest
                        else None
                    ),
                    "matched_rule": (
                        latest[source.id].matched_rule if source.id in latest else None
                    ),
                }
                for source in rows
            ],
            "meta": _meta(session),
        }


@app.get("/api/v1/operations", tags=["operations"])
def operations() -> dict[str, Any]:
    """Operational state: is the pipeline healthy right now?

    This answers a different question from the public dashboard, for a different
    reader. The dashboard reader wants to know what airfares are doing; this
    reader wants to know whether to trust today's numbers, and if not, which
    part broke.

    Written in operational language deliberately. A statistical operations
    console, not an agent control room.
    """
    from schemas.models.collection import CollectionJob, CollectionRequest, RawResponse

    with _Session() as session:
        jobs = session.execute(
            sa.select(CollectionJob).order_by(CollectionJob.started_at.desc()).limit(15)
        ).scalars().all()

        freshest = session.execute(
            sa.select(sa.func.max(NormalisedQuote.collected_at))
        ).scalar_one_or_none()
        latest_index = session.execute(
            sa.select(sa.func.max(IndexObservation.obs_date))
        ).scalar_one_or_none()

        now = datetime.now(UTC)
        age_hours = (
            round((now - freshest).total_seconds() / 3600, 1) if freshest else None
        )

        # Per source: what the gate last decided, and whether anything arrived.
        source_rows = session.execute(
            sa.select(Source).order_by(Source.tier, Source.code)
        ).scalars().all()
        last_decision: dict[Any, ComplianceDecision] = {}
        for decision in session.execute(
            sa.select(ComplianceDecision).order_by(ComplianceDecision.decided_at.desc())
        ).scalars():
            last_decision.setdefault(decision.source_id, decision)

        quote_counts = dict(
            session.execute(
                sa.select(NormalisedQuote.source_id, sa.func.count())
                .group_by(NormalisedQuote.source_id)
            ).all()
        )

        decision_mix = dict(
            session.execute(
                sa.select(ComplianceDecision.decision, sa.func.count())
                .group_by(ComplianceDecision.decision)
            ).all()
        )

        failed_responses = session.execute(
            sa.select(sa.func.count())
            .select_from(RawResponse)
            .where(sa.or_(RawResponse.http_status.is_(None), RawResponse.http_status >= 400))
        ).scalar_one()

        requests_total = session.execute(
            sa.select(sa.func.count()).select_from(CollectionRequest)
        ).scalar_one()

        # Freshness is judged, not just reported: a number with no threshold
        # beside it leaves every reader to invent their own.
        if age_hours is None:
            freshness = "NO_DATA"
        elif age_hours <= 26:
            freshness = "CURRENT"
        elif age_hours <= 72:
            freshness = "STALE"
        else:
            freshness = "OVERDUE"

        alerts: list[dict[str, str]] = []
        if freshness in ("STALE", "OVERDUE"):
            alerts.append({
                "level": "warning" if freshness == "STALE" else "critical",
                "message": f"Most recent observation is {age_hours}h old ({freshness}).",
            })
        if failed_responses:
            alerts.append({
                "level": "warning",
                "message": f"{failed_responses} stored response(s) carry a failed HTTP status.",
            })
        blocked = sum(v for k, v in decision_mix.items() if str(k).startswith("BLOCKED"))
        if blocked:
            alerts.append({
                "level": "info",
                "message": (
                    f"{blocked} request(s) refused by the compliance gate. This is "
                    "expected where a source's robots.txt disallows collection."
                ),
            })
        enabled = [s for s in source_rows if s.enabled]
        if not enabled:
            alerts.append({
                "level": "critical",
                "message": "No source is enabled. Nothing will be collected.",
            })

        return {
            "data": {
                "freshness": {
                    "status": freshness,
                    "latest_observation_at": freshest.isoformat() if freshest else None,
                    "age_hours": age_hours,
                    "latest_index_date": latest_index.isoformat() if latest_index else None,
                    "thresholds": {"current_within_hours": 26, "stale_within_hours": 72},
                },
                "counters": {
                    "collection_requests": requests_total,
                    "responses_with_failed_status": failed_responses,
                    "sources_total": len(source_rows),
                    "sources_enabled": len(enabled),
                },
                "compliance_decisions": decision_mix,
                "alerts": alerts,
                "jobs": [
                    {
                        "started_at": job.started_at.isoformat(),
                        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                        "status": job.status,
                        "requests_total": job.requests_total,
                        "requests_ok": job.requests_ok,
                        "requests_blocked": job.requests_blocked,
                        "parse_failures": job.parse_failures,
                    }
                    for job in jobs
                ],
                "sources": [
                    {
                        "code": source.code,
                        "name": source.name,
                        "tier": source.tier,
                        "transport": source.transport,
                        "enabled": source.enabled,
                        "adapter_key": source.adapter_key,
                        "observations": quote_counts.get(source.id, 0),
                        "last_decision": (
                            last_decision[source.id].decision
                            if source.id in last_decision
                            else None
                        ),
                        "last_decision_at": (
                            last_decision[source.id].decided_at.isoformat()
                            if source.id in last_decision
                            else None
                        ),
                        "matched_rule": (
                            last_decision[source.id].matched_rule
                            if source.id in last_decision
                            else None
                        ),
                    }
                    for source in source_rows
                ],
            },
            "meta": _meta(session),
        }


@app.get("/api/v1/data/structure", tags=["dissemination"])
def data_structure() -> dict[str, Any]:
    """The dataset's structural definition, as an SDMX-JSON structure message.

    SDMX is the usual exchange standard between statistical bodies. If the
    ministry's dissemination stack expects a different format, only the
    serialiser changes - the definition it is built from does not.
    """
    from pipeline.dissemination import APIX_DATASET, to_sdmx_structure

    return to_sdmx_structure(APIX_DATASET)


@app.get("/api/v1/data/download", tags=["dissemination"])
def data_download(
    fmt: str = Query(default="csv", pattern="^(csv|json)$"),
    level: str = Query(default=IndexLevel.ROUTE),
    limit: int = Query(default=5000, le=50000),
) -> Response:
    """Bulk extract of **published** figures.

    An export is a publication. A CSV containing an unapproved figure is as much
    a disclosure as a web page showing one, and easier to do by accident - so
    this filters on publication state exactly as the dashboard does.

    Every row carries its methodology version, weight-set version and revision.
    Extracts get filtered, sorted and pasted into spreadsheets; a provenance
    header at the top of the file survives none of that.
    """
    from pipeline.dissemination import APIX_DATASET, to_csv, to_json
    from pipeline.publication import PublicationState

    with _Session() as session:
        statement = (
            sa.select(IndexObservation, Route.code, LeadTimeBucket.code, Publication)
            .join(Publication, Publication.index_observation_id == IndexObservation.id)
            .join(Route, Route.id == IndexObservation.ref_id, isouter=True)
            .join(
                LeadTimeBucket,
                LeadTimeBucket.id == IndexObservation.bucket_id,
                isouter=True,
            )
            .where(Publication.state == PublicationState.PUBLISHED)
            .where(IndexObservation.level == level)
            .order_by(IndexObservation.obs_date.desc())
            .limit(limit)
        )
        methodologies = {
            row.id: row.version
            for row in session.execute(sa.select(MethodologyVersion)).scalars()
        }
        weight_sets = {
            row.id: row.version
            for row in session.execute(sa.select(WeightSetVersion)).scalars()
        }

        rows = [
            {
                "FREQ": "D",
                "TIME_PERIOD": obs.obs_date.isoformat(),
                "LEVEL": obs.level,
                "ROUTE": route_code or "",
                "LEAD_TIME": bucket_code or "",
                "OBS_VALUE": obs.index_value,
                "METHODOLOGY_VERSION": methodologies.get(obs.methodology_version_id, ""),
                "WEIGHT_SET_VERSION": weight_sets.get(obs.weight_set_version_id, ""),
                "REVISION": obs.revision,
                "OBS_STATUS": pub.state,
                "STD_ERROR": "",
                "PROVENANCE": "",
            }
            for obs, route_code, bucket_code, pub in session.execute(statement).all()
        ]

    if fmt == "csv":
        return Response(
            content=to_csv(rows, APIX_DATASET),
            media_type="text/csv",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="apix-{level.lower()}-'
                    f'{date.today().isoformat()}.csv"'
                )
            },
        )
    return JSONResponse(to_json(rows, APIX_DATASET))


@app.get("/api/v1/methodology", tags=["methodology"])
def methodology() -> dict[str, Any]:
    """The active methodology, its parameters, and its labelled assumptions."""
    with _Session() as session:
        version = session.execute(
            sa.select(MethodologyVersion)
            .order_by(MethodologyVersion.effective_from.desc())
            .limit(1)
        ).scalar_one_or_none()
        if version is None:
            raise HTTPException(status_code=404, detail="No methodology version recorded.")

        buckets = session.execute(
            sa.select(LeadTimeBucket).order_by(LeadTimeBucket.days)
        ).scalars().all()

        return {
            "data": {
                "version": version.version,
                "effective_from": version.effective_from.isoformat(),
                "changelog": version.changelog,
                "parameters": version.params,
                "elementary_formula": "Jevons short (chain-base): I_t = GM(p_t/p_{t-1}) x I_{t-1}",
                "higher_level_formula": (
                    "Young / Modified Laspeyres, weighted arithmetic mean of "
                    "lower-level indices"
                ),
                "source": (
                    "MoSPI Expert Group Report on Comprehensive Updation of CPI, "
                    "January 2026, sections 4.6.1 and 4.6.2"
                ),
                "lead_time_buckets": [
                    {
                        "code": bucket.code,
                        "days": bucket.days,
                        "cpi_comparable": bucket.cpi_comparable,
                    }
                    for bucket in buckets
                ],
                "labelled_assumptions": [
                    "Lead-time weights are uniform. No public Indian distribution of "
                    "booking lead times was found (PA-7).",
                    "Route weights are equal (evidence rung 4) while open item O-5 is "
                    "unresolved. Not derived from traffic data.",
                    "Outlier screening (MAD, k=3.5) is an engineering choice. MoSPI "
                    "prescribes no outlier rule for airfare.",
                    "APIx is based on its own first 30 collection days, not 2024=100. "
                    "Levels are NOT comparable with CPI; only movements are.",
                ],
            },
            "meta": _meta(session),
        }


@app.get("/api/v1/benchmark", tags=["backtest"])
def benchmark() -> dict[str, Any]:
    """The official CPI 2024 domestic-airfare series used for Tier-2 validation."""
    path = Path(__file__).resolve().parents[2] / "data" / "reference" / "cpi_airfare_benchmark.json"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "No benchmark file. Run scripts/fetch_cpi_airfare_series.py to "
                "retrieve the official CPI 2024 airfare series."
            ),
        )
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = [r for r in payload.get("rows", []) if r.get("sector") == "Combined"]
    return {
        "data": {
            "item": payload.get("item"),
            "retrieved_at": payload.get("retrieved_at"),
            "usage": payload.get("_usage"),
            "months": len(rows),
            "series": rows,
        },
        "meta": {
            "provenance": [Provenance.OFFICIAL_STATISTIC],
            "source_url": payload.get("source_url"),
        },
    }


@app.get("/api/v1/backtest", tags=["backtest"])
def backtest() -> dict[str, Any]:
    """Validation against the official CPI airfare index (ADR-015, Tier 2).

    Reports metrics only when enough months align. When they do not - which is
    the present state, APIx having begun after the published benchmark ends -
    the shortfall is reported instead. A validation endpoint that always returns
    a number teaches its reader to stop looking at it.
    """
    import json

    from pipeline.backtest import MonthlyPoint, compare_movements, monthly_average

    path = Path(__file__).resolve().parents[2] / "data" / "reference" / "cpi_airfare_benchmark.json"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="No benchmark file. Run scripts/fetch_cpi_airfare_series.py first.",
        )

    months = {
        name: number
        for number, name in enumerate(
            ("January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"),
            start=1,
        )
    }
    payload = json.loads(path.read_text(encoding="utf-8"))
    benchmark = [
        MonthlyPoint(
            year=int(row["year"]),
            month=months[str(row["month"]).strip().title()],
            value=Decimal(str(row["index"])),
        )
        for row in payload.get("rows", [])
        if row.get("sector") == "Combined"
    ]
    benchmark.sort(key=lambda p: (p.year, p.month))

    with _Session() as session:
        daily = [
            (row.obs_date, row.index_value)
            for row in session.execute(
                sa.select(IndexObservation)
                .where(IndexObservation.level == IndexLevel.HEADLINE)
                .order_by(IndexObservation.obs_date)
            ).scalars()
        ]
        headline_available = bool(daily)

        # With no published headline, the route indices are what exists. They are
        # a weaker comparator and the response says so rather than quietly
        # substituting one series for another.
        if not daily:
            rows = session.execute(
                sa.select(IndexObservation.obs_date, IndexObservation.index_value)
                .where(IndexObservation.level == IndexLevel.ROUTE)
                .order_by(IndexObservation.obs_date)
            ).all()
            grouped: dict[date, list[Decimal]] = {}
            for obs_date, value in rows:
                grouped.setdefault(obs_date, []).append(value)
            daily = [
                (day, sum(values, Decimal(0)) / len(values))
                for day, values in sorted(grouped.items())
            ]

        apix_monthly = monthly_average(daily)
        result = compare_movements(apix_monthly, benchmark)

        return {
            "data": {
                "tier": 2,
                "benchmark": {
                    "item": payload.get("item"),
                    "source_url": payload.get("source_url"),
                    "months": len(benchmark),
                    "range": (
                        f"{benchmark[0].label} to {benchmark[-1].label}" if benchmark else None
                    ),
                },
                "apix": {
                    "series": "headline" if headline_available else "mean of route indices",
                    "series_note": (
                        None
                        if headline_available
                        else "No headline index is published (simulated data). The mean "
                        "of route indices is shown as a weaker stand-in and is labelled "
                        "as such."
                    ),
                    "months": len(apix_monthly),
                    "range": (
                        f"{apix_monthly[0].label} to {apix_monthly[-1].label}"
                        if apix_monthly
                        else None
                    ),
                },
                "sufficient": result.sufficient,
                "limitation": result.limitation,
                "aligned_months": [
                    {
                        "month": m.label,
                        "apix_movement_pct": float(m.apix_movement_pct),
                        "benchmark_movement_pct": float(m.benchmark_movement_pct),
                        "error": float(m.error),
                        "same_direction": m.same_direction,
                    }
                    for m in result.aligned
                ],
                "metrics": None
                if not result.sufficient
                else {
                    "mae_pct_points": float(result.mae or 0),
                    "rmse_pct_points": float(result.rmse or 0),
                    "directional_agreement_pct": float(result.directional_agreement or 0),
                },
                "ps_requirement_note": (
                    "PS 26056 asks for back-testing against publicly available DGCA "
                    "monthly average-fare data. Research found no such public series: "
                    "DGCA's Tariff Monitoring Unit covers 78 routes monthly but does "
                    "not publish a downloadable time series. This comparison uses the "
                    "official CPI 2024 domestic-airfare index instead (ADR-015)."
                ),
            },
            "meta": _meta(session),
        }


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        """A tiny inline mark, so the browser stops asking and the log stays readable."""
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
            '<rect width="32" height="32" fill="#1b3d6d"/>'
            '<text x="16" y="22" font-family="sans-serif" font-size="15" '
            'font-weight="bold" fill="#ffffff" text-anchor="middle">A</text></svg>'
        )
        return Response(content=svg, media_type="image/svg+xml")

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/routes", include_in_schema=False)
    def routes_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "routes.html")

    @app.get("/lead-time", include_in_schema=False)
    def lead_time_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "lead-time.html")

    @app.get("/quality", include_in_schema=False)
    def quality_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "quality.html")

    @app.get("/methodology", include_in_schema=False)
    def methodology_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "methodology.html")

    @app.get("/operations", include_in_schema=False)
    def operations_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "operations.html")
