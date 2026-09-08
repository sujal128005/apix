"""APIx processing pipeline: raw payloads to index-ready observations.

Normalisation knows about sources and not about the index; pairing and
imputation know about the index and not about sources. Keeping that boundary
sharp is what stops statistical policy leaking into site-specific code.
"""

from __future__ import annotations

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
from pipeline.weights import (
    WeightCandidate,
    WeightSet,
    WeightValidationError,
    build_equal_weights,
    build_from_traffic,
    validate_weight_set,
)

__all__ = [
    "ImputationResult",
    "IndexRun",
    "NormalisationError",
    "NormalisedFields",
    "ObservedQuote",
    "RouteOutcome",
    "StratumKey",
    "StratumState",
    "WeightCandidate",
    "WeightSet",
    "WeightValidationError",
    "build_equal_weights",
    "build_from_traffic",
    "build_matched_pairs",
    "compute_index_for_date",
    "group_by_stratum",
    "imputation_rate",
    "impute_missing",
    "normalise_payload",
    "score_quality",
    "validate_weight_set",
]
