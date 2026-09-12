"""Controlled vocabularies for APIx.

Every enum here is mirrored in PostgreSQL as a ``CHECK (col IN (...))``
constraint rather than a native ``CREATE TYPE ... AS ENUM``. That is the
build brief's instruction (§4) and it has a practical benefit: adding a value
is an ordinary migration rather than a type rewrite, and the allowed set is
visible in ``information_schema.check_constraints`` for auditors.

``ImputationCode`` deliberately mirrors MoSPI's own CPI 2024 per-record field
name and its single-character ``N``/``Y`` domain. Do not rename it.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class Provenance(StrEnum):
    """Where an observation came from.

    ``SIMULATED_DEMO`` is structurally barred from reaching a headline index
    value by a database trigger (see migration 0002). It is not a fallback and
    it is not a degraded form of live data: it is a separate lineage.
    """

    LIVE_COLLECTED = "LIVE_COLLECTED"
    LICENSED_API = "LICENSED_API"
    OFFICIAL_STATISTIC = "OFFICIAL_STATISTIC"
    PUBLIC_HISTORICAL = "PUBLIC_HISTORICAL"
    SIMULATED_DEMO = "SIMULATED_DEMO"


class SourceTier(IntEnum):
    """Compliance tier of a source.

    Modelled as an ``IntEnum`` because the column is ``INT`` and the brief
    specifies the domain as the numeric range 1..5.
    """

    LICENSED_API = 1
    REGULATORY_DISCLOSURE = 2
    PERMITTED_CRAWL = 3
    RESTRICTED = 4
    OFFICIAL_STATISTICS = 5


class Transport(StrEnum):
    """How a source is reached. Column domain fixed by the brief (§5, `source`)."""

    API = "api"
    DOCUMENT = "document"
    BROWSER = "browser"


class ReviewVerdict(StrEnum):
    """Outcome of a human compliance review of a source."""

    APPROVED = "APPROVED"
    REQUIRES_LEGAL_REVIEW = "REQUIRES_LEGAL_REVIEW"
    REJECTED = "REJECTED"


class ComplianceDecisionCode(StrEnum):
    """Outcome of the compliance gate for one attempted fetch.

    ``BLOCKED_ROBOTS`` is not an error. It is the system working: a source whose
    robots.txt disallows automated collection is refused, recorded, and shown as
    blocked.
    """

    ALLOWED = "ALLOWED"
    BLOCKED_ROBOTS = "BLOCKED_ROBOTS"
    BLOCKED_UNREVIEWED = "BLOCKED_UNREVIEWED"
    SKIPPED_DISABLED = "SKIPPED_DISABLED"
    DEFERRED_RATE_LIMIT = "DEFERRED_RATE_LIMIT"


class JobStatus(StrEnum):
    """Lifecycle state of a collection job."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class MissingReason(StrEnum):
    """Why an expected observation is absent. ``NONE`` means nothing is missing."""

    NONE = "NONE"
    SCRAPER_FAILURE = "SCRAPER_FAILURE"
    SOURCE_BLOCKED = "SOURCE_BLOCKED"
    NO_FLIGHTS = "NO_FLIGHTS"
    SOLD_OUT = "SOLD_OUT"
    PARSE_FAILURE = "PARSE_FAILURE"
    PARTIAL_COMPONENTS = "PARTIAL_COMPONENTS"
    CHAIN_GAP = "CHAIN_GAP"


class FareComponentKind(StrEnum):
    """Decomposition of a total fare into published components."""

    BASE = "BASE"
    TAX = "TAX"
    UDF = "UDF"
    CONVENIENCE = "CONVENIENCE"
    OTHER = "OTHER"


class Confidence(StrEnum):
    """Confidence attached to a parsed value."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class QualityStatus(StrEnum):
    """Quality classification of a normalised quote."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    SUSPICIOUS = "SUSPICIOUS"
    UNUSABLE = "UNUSABLE"


class IndexLevel(StrEnum):
    """Aggregation level of an index observation.

    ``STRATUM`` is route x lead-time bucket (Jevons short, geometric).
    ``ROUTE`` and ``HEADLINE`` are Young / modified Laspeyres (weighted
    arithmetic). Geometric below, arithmetic above.
    """

    STRATUM = "STRATUM"
    ROUTE = "ROUTE"
    HEADLINE = "HEADLINE"


class ImputationCode(StrEnum):
    """MoSPI CPI 2024 per-record imputation flag. Field name and domain are theirs."""

    N = "N"
    Y = "Y"


class EvidenceRung(IntEnum):
    """Strength of the evidence behind a route weight. Lower is stronger.

    1. Published city-pair passenger volumes
    2. DGCA popular-routes list
    3. Airport-throughput proxy
    4. Equal weights (last resort, must be labelled as such)
    """

    CITY_PAIR_VOLUMES = 1
    DGCA_POPULAR_ROUTES = 2
    AIRPORT_THROUGHPUT_PROXY = 3
    EQUAL = 4


class PublicationState(StrEnum):
    """Where a computed figure sits in the release lifecycle.

    Computing is not publishing. An official statistic is released by a named
    person against a calendar, and once released it is revised openly rather
    than changed silently.
    """

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"


class Mode(StrEnum):
    """Operating mode of a deployment.

    Which provenance each mode produces, per the architect's Phase 3 ruling:

    ``LIVE``
        Real collection. There should be zero ``SIMULATED_DEMO`` quotes at all.
    ``STAGED``
        Rehearsal against recorded payloads.
    ``OFFLINE_DEMO``
        Frozen, previously collected **real** data - ``LIVE_COLLECTED`` or
        ``PUBLIC_HISTORICAL``. Not ``SIMULATED_DEMO``.

    ``SIMULATED_DEMO`` is for development fixtures only, which is why the C5
    trigger can bar it from headline values outright without ever blocking
    offline demo mode.

    Declared here because the brief (section 4) requires it. No Phase 3 table
    stores it; the collection runtime that consumes it arrives in a later phase.
    """

    LIVE = "LIVE"
    STAGED = "STAGED"
    OFFLINE_DEMO = "OFFLINE_DEMO"


def values(enum_cls: type[StrEnum]) -> tuple[str, ...]:
    """Return the member values of a string enum, in declaration order.

    Used to build the PostgreSQL ``CHECK (col IN (...))`` constraints so the
    database domain and the Python domain cannot drift apart.
    """
    return tuple(member.value for member in enum_cls)


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
    "values",
]
