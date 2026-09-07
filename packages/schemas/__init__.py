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
from schemas.hashing import compute_query_hash
from schemas.uuid7 import uuid7

__all__ = [
    "ComplianceDecisionCode",
    "Confidence",
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
    "uuid7",
]
