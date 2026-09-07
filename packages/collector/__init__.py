"""APIx collection layer: adapters, retry policy and the runner.

The runner is the only caller of an adapter, and an adapter cannot fetch without
a ``ComplianceToken``, so every network request in the system passes the gate by
construction rather than by discipline. See ADR-001 and ADR-018.
"""

from __future__ import annotations

from collector.adapter import (
    AdapterRequest,
    AdapterResponse,
    CollectionSpec,
    HealthReport,
    ParsedQuote,
    SourceAdapter,
    SourceValidation,
)
from collector.mock_adapter import MockAdapter, MockBehaviour
from collector.retry import RetryPolicy, TransportOutcome, is_retryable
from collector.runner import CollectionRunner, RunResult, SpecOutcome
from collector.tls import TlsLadder, TlsMode, build_ssl_context

__all__ = [
    "AdapterRequest",
    "AdapterResponse",
    "CollectionRunner",
    "CollectionSpec",
    "HealthReport",
    "MockAdapter",
    "MockBehaviour",
    "ParsedQuote",
    "RetryPolicy",
    "RunResult",
    "SourceAdapter",
    "SourceValidation",
    "SpecOutcome",
    "TlsLadder",
    "TlsMode",
    "TransportOutcome",
    "build_ssl_context",
    "is_retryable",
]
