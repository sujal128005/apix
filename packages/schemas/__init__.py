"""APIx shared schema package: SQLAlchemy models, Pydantic contracts, enums.

This package is the single source of truth for the APIx data layer. Nothing in
here computes an index, fetches a fare, or makes a compliance decision — those
belong to later phases.
"""

from schemas.enums import (
    ComplianceDecisionCode,
    Confidence,
    EvidenceRung,
    FareComponentKind,
    ImputationCode,
    IndexLevel,
    JobStatus,
    MissingReason,
    Mode,
    Provenance,
    QualityStatus,
    ReviewVerdict,
    SourceTier,
    Transport,
)
from schemas.environment import (
    Environment,
    current_environment,
    is_production,
    require_not_production,
)
from schemas.hashing import compute_query_hash
from schemas.uuid7 import uuid7

__all__ = [
    "ComplianceDecisionCode",
    "Confidence",
    "Environment",
    "EvidenceRung",
    "FareComponentKind",
    "ImputationCode",
    "IndexLevel",
    "JobStatus",
    "MissingReason",
    "Mode",
    "Provenance",
    "QualityStatus",
    "ReviewVerdict",
    "SourceTier",
    "Transport",
    "compute_query_hash",
    "current_environment",
    "is_production",
    "require_not_production",
    "uuid7",
]
