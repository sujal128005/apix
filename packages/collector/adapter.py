"""The source-adapter contract.

One interface over heterogeneous transports: a licensed API, a regulatory PDF, a
robots-permitted web page. ADR-001 chose a hybrid ingestion layer precisely so
that *which* sources feed the index stays a configuration outcome rather than a
structural one, and this module is where that promise is kept - the runner knows
only this interface, never a specific site.

The load-bearing detail is in :meth:`SourceAdapter.execute`. It requires a
``ComplianceToken``, and only :mod:`compliance.gate` can mint one. An adapter
author cannot write a fetch that skips the gate, because the method they must
implement cannot be *called* without the gate's approval in hand. That is ADR-018
doing real work rather than being a promise in a document.

Adapters do four separable things, and keeping them separable is what makes a
broken site a contained failure:

    build_request  pure: a search spec becomes a path and parameters. No I/O.
    execute        the only method that touches the network. Needs a token.
    parse          pure: bytes become a list of source-shaped quote payloads.
    normalize      pure: source-shaped fields are renamed to the common payload.

``parse`` and ``normalize`` are pure, so every real-world response we ever see
can be frozen as a fixture and replayed offline. When a site changes its markup,
the regression test fails on a stored file rather than in production.

**Scope note.** ``normalize`` here does adapter-local field mapping only -
"this source calls it ``totalAmount``, we call it ``total_fare``". It does not
clean, deduplicate, score or impute; that is the Phase 7 pipeline working over
canonical records. The split matters: field naming is knowledge about a source,
whereas cleaning policy is knowledge about the index, and mixing them would put
statistical decisions inside site-specific code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, ClassVar
from uuid import UUID

from compliance.token import ComplianceToken

__all__ = [
    "AdapterRequest",
    "AdapterResponse",
    "CollectionSpec",
    "HealthReport",
    "ParsedQuote",
    "SourceAdapter",
    "SourceValidation",
]


@dataclass(frozen=True, slots=True)
class CollectionSpec:
    """One intended search, in domain terms. Transport-agnostic."""

    source_id: UUID
    source_code: str
    route_id: UUID
    route_code: str
    origin: str
    destination: str
    bucket_id: UUID
    bucket_code: str
    lead_time_days: int
    travel_date: date
    collected_date: date


@dataclass(frozen=True, slots=True)
class AdapterRequest:
    """What to fetch, expressed so the gate can evaluate it before it happens.

    ``path`` is what robots.txt is checked against, so it must be the real path
    the adapter will request - not a summary of it. An adapter that evaluates
    one path and fetches another has defeated the gate.
    """

    path: str
    params: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    method: str = "GET"


@dataclass(frozen=True, slots=True)
class AdapterResponse:
    """Raw bytes plus the metadata needed to store and hash them."""

    body: str
    http_status: int | None
    fetched_at: datetime
    content_type: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.http_status is not None and 200 <= self.http_status < 300


@dataclass(frozen=True, slots=True)
class ParsedQuote:
    """One fare offer as the source presented it, before any interpretation."""

    ordinal: int
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SourceValidation:
    """Whether an adapter can work with a given source row at all."""

    ok: bool
    problems: tuple[str, ...] = ()

    @classmethod
    def valid(cls) -> SourceValidation:
        return cls(ok=True)

    @classmethod
    def invalid(cls, *problems: str) -> SourceValidation:
        return cls(ok=False, problems=tuple(problems))


@dataclass(frozen=True, slots=True)
class HealthReport:
    """An adapter's own view of whether it is currently usable."""

    healthy: bool
    detail: str
    checked_at: datetime


class SourceAdapter(ABC):
    """Base class for every source adapter.

    Subclasses declare ``adapter_key``, which matches ``source.adapter_key`` in
    the database. Several sources may share one adapter - the five airline
    tariff-sheet sources all use ``airline_tariff_doc_v1`` - because the
    difference between them is configuration, not code.
    """

    adapter_key: ClassVar[str]

    @abstractmethod
    def validate_source(self, *, source_code: str, base_url: str | None) -> SourceValidation:
        """Check this adapter can work with that source before any fetch."""

    @abstractmethod
    def build_request(self, spec: CollectionSpec) -> AdapterRequest:
        """Turn a search spec into a concrete request. Pure: no I/O."""

    @abstractmethod
    def execute(
        self,
        request: AdapterRequest,
        token: ComplianceToken,
        *,
        base_url: str,
    ) -> AdapterResponse:
        """Perform the fetch.

        The token is not decorative. It is proof that
        :func:`compliance.gate.evaluate` approved *this* source and *this* path
        moments ago, and there is no way to obtain one except from the gate.
        Implementations must fetch exactly ``request.path`` - the path the gate
        evaluated - and nothing else.
        """

    @abstractmethod
    def parse(self, response: AdapterResponse) -> list[ParsedQuote]:
        """Extract fare offers from a payload. Pure, so fixtures can replay it."""

    @abstractmethod
    def normalize(self, quote: ParsedQuote) -> dict[str, Any]:
        """Map source-specific field names onto the common payload shape.

        Field naming only. Cleaning, deduplication, quality scoring and
        imputation belong to the Phase 7 pipeline, which works over canonical
        records and knows nothing about any particular source.
        """

    @abstractmethod
    def health_check(self) -> HealthReport:
        """Report whether this adapter is currently usable. No collection."""

    def diagnostics(self) -> dict[str, Any]:
        """Operator-facing detail for the Command Center. Override to add more."""
        return {"adapter_key": self.adapter_key, "class": type(self).__name__}
