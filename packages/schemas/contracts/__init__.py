"""Pydantic v2 contracts, one per table.

Every contract mirrors its SQLAlchemy model field for field, so a contract can
be validated directly off an ORM instance and dumped straight back into one.
The registry below is what
``tests/unit/test_contract_coverage.py`` walks to prove no table is missing a
contract and no contract has drifted from its table.
"""

from __future__ import annotations

from schemas.contracts.base import ApixContract
from schemas.contracts.collection import (
    CollectionJob,
    CollectionRequest,
    ComplianceDecision,
    RawQuote,
    RawResponse,
)
from schemas.contracts.derived import CleaningEvent, FareComponent, NormalisedQuote
from schemas.contracts.indexing import (
    BacktestRun,
    BenchmarkObservation,
    IndexContribution,
    IndexObservation,
)
from schemas.contracts.reference import Airport, LeadTimeBucket, Route, Source, SourceReview
from schemas.contracts.system import SystemEvent
from schemas.contracts.versioning import (
    BasePeriod,
    MethodologyVersion,
    RouteWeight,
    WeightSetVersion,
)

CONTRACT_BY_TABLE: dict[str, type[ApixContract]] = {
    "airport": Airport,
    "backtest_run": BacktestRun,
    "base_period": BasePeriod,
    "benchmark_observation": BenchmarkObservation,
    "cleaning_event": CleaningEvent,
    "collection_job": CollectionJob,
    "collection_request": CollectionRequest,
    "compliance_decision": ComplianceDecision,
    "fare_component": FareComponent,
    "index_contribution": IndexContribution,
    "index_observation": IndexObservation,
    "lead_time_bucket": LeadTimeBucket,
    "methodology_version": MethodologyVersion,
    "normalised_quote": NormalisedQuote,
    "raw_quote": RawQuote,
    "raw_response": RawResponse,
    "route": Route,
    "route_weight": RouteWeight,
    "source": Source,
    "source_review": SourceReview,
    "system_event": SystemEvent,
    "weight_set_version": WeightSetVersion,
}

__all__ = [
    "CONTRACT_BY_TABLE",
    "Airport",
    "ApixContract",
    "BacktestRun",
    "BasePeriod",
    "BenchmarkObservation",
    "CleaningEvent",
    "CollectionJob",
    "CollectionRequest",
    "ComplianceDecision",
    "FareComponent",
    "IndexContribution",
    "IndexObservation",
    "LeadTimeBucket",
    "MethodologyVersion",
    "NormalisedQuote",
    "RawQuote",
    "RawResponse",
    "Route",
    "RouteWeight",
    "Source",
    "SourceReview",
    "SystemEvent",
    "WeightSetVersion",
]
