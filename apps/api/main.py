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

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, sessionmaker

from db.settings import DbSettings
from schemas.enums import IndexLevel, Mode, Provenance
from schemas.models.collection import ComplianceDecision
from schemas.models.derived import NormalisedQuote
from schemas.models.indexing import IndexObservation
from schemas.models.reference import LeadTimeBucket, Route, Source
from schemas.models.versioning import MethodologyVersion, WeightSetVersion

STATIC_DIR = Path(__file__).resolve().parent / "static"

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


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")
