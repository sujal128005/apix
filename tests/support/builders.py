"""Builders that assemble a complete evidence chain the way the collector will.

A single fare observation is only meaningful with everything behind it, so these
helpers always build the whole chain:

    collection_job -> collection_request -> compliance_decision
                                         -> raw_response -> raw_quote
                                                         -> normalised_quote
                                                         -> cleaning_event

Nothing here computes an index or applies a cleaning rule. The values are
supplied by the caller; the builders only wire up the relationships so a test
can assert on lineage rather than on hand-written INSERT statements.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from schemas.enums import (
    ComplianceDecisionCode,
    Confidence,
    FareComponentKind,
    ImputationCode,
    JobStatus,
    MissingReason,
    Provenance,
    QualityStatus,
)
from schemas.hashing import compute_query_hash
from schemas.models import (
    Airport,
    BasePeriod,
    CleaningEvent,
    CollectionJob,
    CollectionRequest,
    ComplianceDecision,
    FareComponent,
    IndexContribution,
    IndexObservation,
    LeadTimeBucket,
    MethodologyVersion,
    NormalisedQuote,
    RawQuote,
    RawResponse,
    Route,
    RouteWeight,
    Source,
    WeightSetVersion,
)

USER_AGENT = "APIxBot/0.3 (+https://example.invalid/apix-bot; SIH 2026 PS 26056)"


@dataclass(frozen=True)
class SeedRefs:
    """Primary keys of the seeded reference rows, looked up by natural key."""

    airports: dict[str, UUID]
    routes: dict[str, UUID]
    buckets: dict[str, UUID]
    bucket_days: dict[str, int]
    sources: dict[str, UUID]
    methodology_version_id: UUID


def load_refs(session: Session) -> SeedRefs:
    """Read the seeded reference data into a lookup table."""
    airports = {
        iata: airport_id for airport_id, iata in session.execute(select(Airport.id, Airport.iata))
    }
    routes = {code: route_id for route_id, code in session.execute(select(Route.id, Route.code))}
    buckets: dict[str, UUID] = {}
    bucket_days: dict[str, int] = {}
    for bucket_id, code, days in session.execute(
        select(LeadTimeBucket.id, LeadTimeBucket.code, LeadTimeBucket.days)
    ):
        buckets[code] = bucket_id
        bucket_days[code] = days
    sources = {code: source_id for source_id, code in session.execute(select(Source.id, Source.code))}
    methodology_version_id = session.execute(
        select(MethodologyVersion.id).order_by(MethodologyVersion.version)
    ).scalars().first()
    assert methodology_version_id is not None, "methodology_version was not seeded"
    return SeedRefs(
        airports=airports,
        routes=routes,
        buckets=buckets,
        bucket_days=bucket_days,
        sources=sources,
        methodology_version_id=methodology_version_id,
    )


@dataclass
class Collection:
    """One search and the bytes it produced."""

    job: CollectionJob
    request: CollectionRequest
    decision: ComplianceDecision
    response: RawResponse
    next_ordinal: int = 0


def build_job(session: Session, *, started_at: datetime) -> CollectionJob:
    job = CollectionJob(started_at=started_at, status=JobStatus.RUNNING.value)
    session.add(job)
    session.flush()
    return job


def build_collection(
    session: Session,
    refs: SeedRefs,
    *,
    source_code: str = "indigo_web",
    route_code: str = "DEL-BOM",
    bucket_code: str = "T7",
    travel_date: date,
    collected_date: date,
    fetched_at: datetime,
    job: CollectionJob | None = None,
    decision: ComplianceDecisionCode = ComplianceDecisionCode.ALLOWED,
    payload_ref: str | None = None,
) -> Collection:
    """Create the request, its compliance decision and the stored response."""
    if job is None:
        job = build_job(session, started_at=fetched_at)

    request = CollectionRequest(
        job_id=job.id,
        source_id=refs.sources[source_code],
        route_id=refs.routes[route_code],
        bucket_id=refs.buckets[bucket_code],
        travel_date=travel_date,
        collected_date=collected_date,
        query_hash=compute_query_hash(
            source_code=source_code,
            route_code=route_code,
            bucket_code=bucket_code,
            travel_date=travel_date,
            collected_date=collected_date,
        ),
    )
    session.add(request)
    session.flush()

    compliance = ComplianceDecision(
        source_id=refs.sources[source_code],
        request_id=request.id,
        path=f"/search/{route_code}/{travel_date.isoformat()}",
        user_agent=USER_AGENT,
        robots_sha256=hashlib.sha256(f"robots:{source_code}".encode()).hexdigest(),
        matched_rule="Allow: /" if decision is ComplianceDecisionCode.ALLOWED else "Disallow: /",
        decision=decision.value,
        decided_at=fetched_at,
    )
    session.add(compliance)

    reference = payload_ref or f"s3://apix-raw/{source_code}/{collected_date.isoformat()}/{route_code}.json"
    response = RawResponse(
        request_id=request.id,
        payload_ref=reference,
        sha256=hashlib.sha256(reference.encode()).hexdigest(),
        http_status=200,
        fetched_at=fetched_at,
    )
    session.add(response)
    session.flush()

    return Collection(job=job, request=request, decision=compliance, response=response)


def add_quote(
    session: Session,
    refs: SeedRefs,
    collection: Collection,
    *,
    route_code: str = "DEL-BOM",
    bucket_code: str = "T7",
    source_code: str = "indigo_web",
    carrier: str = "6E",
    flight_no: str | None,
    fare_brand: str | None,
    total_fare: Decimal,
    departure_ts: datetime | None,
    collected_at: datetime,
    collected_date: date,
    provenance: Provenance = Provenance.LIVE_COLLECTED,
    quality_status: QualityStatus = QualityStatus.COMPLETE,
    quality_score: Decimal | None = None,
    imputation_code: ImputationCode = ImputationCode.N,
    missing_reason: MissingReason = MissingReason.NONE,
    component_confidence: Confidence | None = None,
    with_raw_quote: bool = True,
) -> NormalisedQuote:
    """Attach one raw offer and its normalised form to an existing collection."""
    raw_quote_id: UUID | None = None
    if with_raw_quote:
        payload: dict[str, Any] = {
            "carrier": carrier,
            "flight_no": flight_no,
            "fare_brand": fare_brand,
            # Money stays a string in the raw payload: JSON numbers are floats.
            "total_fare": str(total_fare),
            "currency": "INR",
            "departure": departure_ts.isoformat() if departure_ts else None,
        }
        raw = RawQuote(
            raw_response_id=collection.response.id,
            ordinal=collection.next_ordinal,
            payload=json.loads(json.dumps(payload)),
        )
        collection.next_ordinal += 1
        session.add(raw)
        session.flush()
        raw_quote_id = raw.id

    quote = NormalisedQuote(
        raw_quote_id=raw_quote_id,
        route_id=refs.routes[route_code],
        bucket_id=refs.buckets[bucket_code],
        source_id=refs.sources[source_code],
        carrier=carrier,
        flight_no=flight_no,
        departure_ts=departure_ts,
        arrival_ts=None,
        lead_time_days=refs.bucket_days[bucket_code],
        fare_brand=fare_brand,
        total_fare=total_fare,
        currency="INR",
        collected_at=collected_at,
        collected_date=collected_date,
        provenance=provenance.value,
        quality_status=quality_status.value,
        quality_score=quality_score,
        imputation_code=imputation_code.value,
        missing_reason=missing_reason.value,
        component_confidence=component_confidence.value if component_confidence else None,
    )
    session.add(quote)
    session.flush()
    return quote


def add_cleaning_event(
    session: Session,
    quote: NormalisedQuote,
    *,
    rule_id: str,
    action: str,
    reason: str,
    threshold: Decimal | None = None,
    observed: Decimal | None = None,
) -> CleaningEvent:
    event = CleaningEvent(
        quote_id=quote.id,
        rule_id=rule_id,
        action=action,
        threshold=threshold,
        observed=observed,
        reason=reason,
    )
    session.add(event)
    session.flush()
    return event


def add_fare_component(
    session: Session,
    quote: NormalisedQuote,
    *,
    kind: FareComponentKind,
    amount: Decimal,
    confidence: Confidence = Confidence.HIGH,
) -> FareComponent:
    component = FareComponent(
        quote_id=quote.id,
        kind=kind.value,
        amount=amount,
        confidence=confidence.value,
    )
    session.add(component)
    session.flush()
    return component


def make_weight_set(
    session: Session,
    *,
    version: str,
    effective_from: date,
    source_note: str,
) -> WeightSetVersion:
    """Create an empty weight set. Callers add the weights themselves.

    Test weight sets are named ``test_weight_set_*`` so they can never be
    mistaken for sourced weights: ``route_weight`` ships empty and stays that
    way until real evidence (open item O-5) arrives.
    """
    assert version.startswith("test_weight_set_"), (
        "test weight sets must be named test_weight_set_* so they are never "
        "mistaken for sourced weights"
    )
    weight_set = WeightSetVersion(
        version=version,
        effective_from=effective_from,
        source_note=source_note,
    )
    session.add(weight_set)
    session.flush()
    return weight_set


def add_route_weight(
    session: Session,
    refs: SeedRefs,
    weight_set: WeightSetVersion,
    *,
    route_code: str,
    weight: Decimal,
    evidence_rung: int | None,
    evidence_ref: str = "synthetic test weight set; not sourced evidence",
    evidence_retrieved_at: datetime | None = None,
) -> RouteWeight:
    row = RouteWeight(
        route_id=refs.routes[route_code],
        weight=weight,
        evidence_rung=evidence_rung,
        evidence_ref=evidence_ref,
        evidence_retrieved_at=evidence_retrieved_at or datetime.now(UTC),
        weight_set_version_id=weight_set.id,
    )
    session.add(row)
    return row


def make_base_period(
    session: Session,
    refs: SeedRefs,
    *,
    code: str,
    start_date: date,
    end_date: date,
    description: str = "synthetic base period built inside a test; not an established one",
) -> BasePeriod:
    """Create a base period. Ships empty in production - Phase 9 establishes the real one."""
    period = BasePeriod(
        code=code,
        start_date=start_date,
        end_date=end_date,
        description=description,
        methodology_version_id=refs.methodology_version_id,
    )
    session.add(period)
    session.flush()
    return period


def make_index_observation(
    session: Session,
    refs: SeedRefs,
    *,
    obs_date: date,
    level: str,
    weight_set: WeightSetVersion,
    index_value: Decimal,
    prev_index_value: Decimal | None = None,
    ref_id: UUID | None = None,
    bucket_id: UUID | None = None,
    input_quote_count: int = 3,
    input_hash: str = "0" * 64,
    routes_in_basket: int | None = None,
    base_period: BasePeriod | None = None,
) -> IndexObservation:
    observation = IndexObservation(
        obs_date=obs_date,
        level=level,
        ref_id=ref_id,
        bucket_id=bucket_id,
        index_value=index_value,
        prev_index_value=prev_index_value,
        base_period_id=base_period.id if base_period else None,
        methodology_version_id=refs.methodology_version_id,
        weight_set_version_id=weight_set.id,
        input_quote_count=input_quote_count,
        excluded_count=0,
        imputed_count=0,
        routes_in_basket=routes_in_basket,
        input_hash=input_hash,
        computed_at=datetime.now(UTC),
    )
    session.add(observation)
    session.flush()
    return observation


def add_contribution(
    session: Session,
    refs: SeedRefs,
    observation: IndexObservation,
    *,
    route_code: str,
    contribution: Decimal,
) -> IndexContribution:
    row = IndexContribution(
        index_observation_id=observation.id,
        route_id=refs.routes[route_code],
        contribution=contribution,
    )
    session.add(row)
    session.flush()
    return row


def utc(day: date, clock: time) -> datetime:
    """Combine a date and a wall time into an aware UTC timestamp."""
    return datetime.combine(day, clock, tzinfo=UTC)


__all__ = [
    "USER_AGENT",
    "Collection",
    "SeedRefs",
    "add_cleaning_event",
    "add_contribution",
    "add_fare_component",
    "add_quote",
    "add_route_weight",
    "build_collection",
    "build_job",
    "load_refs",
    "make_base_period",
    "make_index_observation",
    "make_weight_set",
    "utc",
]
