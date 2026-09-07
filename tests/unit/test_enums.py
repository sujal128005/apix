"""The controlled vocabularies must match build brief section 4 exactly.

These are not decoration. Every one of them is mirrored into a PostgreSQL CHECK
constraint, so a member added or renamed here silently changes what the database
will accept. Pinning the exact member sets means that change cannot happen by
accident.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum

import pytest

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
    values,
)

EXPECTED_STRING_MEMBERS: dict[type[StrEnum], tuple[str, ...]] = {
    Provenance: (
        "LIVE_COLLECTED",
        "LICENSED_API",
        "OFFICIAL_STATISTIC",
        "PUBLIC_HISTORICAL",
        "SIMULATED_DEMO",
    ),
    ReviewVerdict: ("APPROVED", "REQUIRES_LEGAL_REVIEW", "REJECTED"),
    ComplianceDecisionCode: (
        "ALLOWED",
        "BLOCKED_ROBOTS",
        "BLOCKED_UNREVIEWED",
        "SKIPPED_DISABLED",
        "DEFERRED_RATE_LIMIT",
    ),
    JobStatus: ("PENDING", "RUNNING", "SUCCESS", "PARTIAL", "FAILED"),
    MissingReason: (
        "NONE",
        "SCRAPER_FAILURE",
        "SOURCE_BLOCKED",
        "NO_FLIGHTS",
        "SOLD_OUT",
        "PARSE_FAILURE",
        "PARTIAL_COMPONENTS",
        "CHAIN_GAP",
    ),
    FareComponentKind: ("BASE", "TAX", "UDF", "CONVENIENCE", "OTHER"),
    Confidence: ("HIGH", "MEDIUM", "LOW"),
    QualityStatus: ("COMPLETE", "PARTIAL", "SUSPICIOUS", "UNUSABLE"),
    IndexLevel: ("STRATUM", "ROUTE", "HEADLINE"),
    ImputationCode: ("N", "Y"),
    Mode: ("LIVE", "STAGED", "OFFLINE_DEMO"),
    Transport: ("api", "document", "browser"),
}

EXPECTED_INT_MEMBERS: dict[type[IntEnum], tuple[int, ...]] = {
    SourceTier: (1, 2, 3, 4, 5),
    EvidenceRung: (1, 2, 3, 4),
}


@pytest.mark.parametrize(
    ("enum_cls", "expected"),
    list(EXPECTED_STRING_MEMBERS.items()),
    ids=[cls.__name__ for cls in EXPECTED_STRING_MEMBERS],
)
def test_string_enum_members_match_the_brief(
    enum_cls: type[StrEnum], expected: tuple[str, ...]
) -> None:
    assert values(enum_cls) == expected


@pytest.mark.parametrize(
    ("enum_cls", "expected"),
    list(EXPECTED_INT_MEMBERS.items()),
    ids=[cls.__name__ for cls in EXPECTED_INT_MEMBERS],
)
def test_int_enum_members_match_the_brief(
    enum_cls: type[IntEnum], expected: tuple[int, ...]
) -> None:
    assert tuple(int(member) for member in enum_cls) == expected


def test_imputation_code_keeps_mospi_field_shape() -> None:
    """ImputationCode mirrors MoSPI's own CPI 2024 per-record flag. Do not rename it."""
    assert ImputationCode.N.value == "N"
    assert ImputationCode.Y.value == "Y"
    assert len(ImputationCode) == 2


def test_simulated_demo_is_a_provenance_not_a_quality_status() -> None:
    """Simulated data is a separate lineage, never a degraded form of live data."""
    assert "SIMULATED_DEMO" in values(Provenance)
    assert "SIMULATED_DEMO" not in values(QualityStatus)


def test_blocked_robots_is_a_compliance_outcome_not_an_error() -> None:
    """A robots-blocked source is the system working, and is rendered as such."""
    assert ComplianceDecisionCode.BLOCKED_ROBOTS in ComplianceDecisionCode
    assert "ERROR" not in values(ComplianceDecisionCode)


def test_string_enums_compare_equal_to_their_values() -> None:
    """StrEnum members are plain strings, so ORM columns can hold them directly."""
    assert Provenance.LIVE_COLLECTED == "LIVE_COLLECTED"
    assert isinstance(Provenance.LIVE_COLLECTED, str)


def test_evidence_rung_orders_strongest_first() -> None:
    """Rung 1 is published city-pair volumes; rung 4 is equal weights, the last resort."""
    assert EvidenceRung.CITY_PAIR_VOLUMES < EvidenceRung.EQUAL
    assert int(EvidenceRung.EQUAL) == 4
