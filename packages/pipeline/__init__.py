"""APIx processing pipeline: raw payloads to index-ready observations.

Normalisation knows about sources and not about the index; pairing and
imputation know about the index and not about sources. Keeping that boundary
sharp is what stops statistical policy leaking into site-specific code.
"""

from __future__ import annotations

from pipeline.backtest import (
    AlignedMonth,
    BacktestReport,
    MonthlyPoint,
    TierTwoResult,
    compare_movements,
    monthly_average,
)
from pipeline.dissemination import (
    APIX_DATASET,
    Codelist,
    DatasetDefinition,
    Dimension,
    Measure,
    to_csv,
    to_json,
    to_sdmx_structure,
)
from pipeline.impute import ImputationResult, StratumState, imputation_rate, impute_missing
from pipeline.normalise import (
    NormalisationError,
    NormalisedFields,
    ObservedQuote,
    StratumKey,
    build_matched_pairs,
    group_by_stratum,
    normalise_payload,
    score_quality,
)
from pipeline.orchestrator import IndexRun, RouteOutcome, compute_index_for_date
from pipeline.publication import (
    PublicationError,
    PublicationState,
    PublishedFigure,
    approve,
    current_published,
    publish,
    revise,
    submit_for_approval,
    withdraw,
)
from pipeline.specification import (
    Cabin,
    Changeability,
    DepartureBand,
    ProductSpecification,
    Refundability,
    RoutingType,
    TripType,
    departure_band_for,
    specification_from_quote,
)
from pipeline.uncertainty import (
    StratumUncertainty,
    aggregate_standard_error,
    stratum_uncertainty,
)
from pipeline.weights import (
    WeightCandidate,
    WeightSet,
    WeightValidationError,
    build_equal_weights,
    build_from_airport_throughput,
    build_from_traffic,
    validate_weight_set,
)

__all__ = [
    "APIX_DATASET",
    "AlignedMonth",
    "BacktestReport",
    "Cabin",
    "Changeability",
    "Codelist",
    "DatasetDefinition",
    "DepartureBand",
    "Dimension",
    "ImputationResult",
    "IndexRun",
    "Measure",
    "MonthlyPoint",
    "NormalisationError",
    "NormalisedFields",
    "ObservedQuote",
    "ProductSpecification",
    "PublicationError",
    "PublicationState",
    "PublishedFigure",
    "Refundability",
    "RouteOutcome",
    "RoutingType",
    "StratumKey",
    "StratumState",
    "StratumUncertainty",
    "TierTwoResult",
    "TripType",
    "WeightCandidate",
    "WeightSet",
    "WeightValidationError",
    "aggregate_standard_error",
    "approve",
    "build_equal_weights",
    "build_from_airport_throughput",
    "build_from_traffic",
    "build_matched_pairs",
    "compare_movements",
    "compute_index_for_date",
    "current_published",
    "departure_band_for",
    "group_by_stratum",
    "imputation_rate",
    "impute_missing",
    "monthly_average",
    "normalise_payload",
    "publish",
    "revise",
    "score_quality",
    "specification_from_quote",
    "stratum_uncertainty",
    "submit_for_approval",
    "to_csv",
    "to_json",
    "to_sdmx_structure",
    "validate_weight_set",
    "withdraw",
]
