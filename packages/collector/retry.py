"""Retry policy.

Two rules, and the second matters more than the first.

**Retry transport failures.** A timeout or a 502 is the network being unreliable,
and trying again is reasonable. Twice, with backoff, then stop.

**Never retry a refusal.** A ``BLOCKED_ROBOTS`` verdict is not a transient
failure - it is a site telling us not to fetch that path, and retrying it is
precisely the behaviour robots.txt exists to prevent. The same holds for a
rate-limit deferral: the correct response to "you are going too fast" is to
wait until the stated time, not to ask again immediately.

This distinction is enforced by :func:`is_retryable` refusing to look at a
compliance decision at all. The runner asks it only about transport outcomes,
and the type signature means a refusal cannot be passed to it by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = ["RetryPolicy", "TransportOutcome", "is_retryable"]

# 429 is absent deliberately. Being asked to slow down is not a transport
# failure; it is an instruction, and the runner honours it by deferring the
# source rather than by trying again.
RETRYABLE_STATUSES: Final[frozenset[int]] = frozenset({500, 502, 503, 504})

TERMINAL_STATUSES: Final[frozenset[int]] = frozenset({400, 401, 403, 404, 410, 422, 429})


@dataclass(frozen=True, slots=True)
class TransportOutcome:
    """What happened at the wire, with no compliance meaning attached."""

    http_status: int | None
    timed_out: bool = False
    connection_error: bool = False

    @property
    def succeeded(self) -> bool:
        return self.http_status is not None and 200 <= self.http_status < 300


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How many times to retry a transport failure, and how long to wait."""

    max_attempts: int = 3  # one initial attempt plus two retries
    base_delay_seconds: float = 2.0
    multiplier: float = 3.0

    def delay_for(self, attempt: int) -> float:
        """Backoff before ``attempt`` (1-based). Attempt 1 never waits."""
        if attempt <= 1:
            return 0.0
        return self.base_delay_seconds * (self.multiplier ** (attempt - 2))

    def should_retry(self, outcome: TransportOutcome, attempt: int) -> bool:
        if attempt >= self.max_attempts:
            return False
        return is_retryable(outcome)


def is_retryable(outcome: TransportOutcome) -> bool:
    """True only for failures that a later identical request might survive.

    Takes a :class:`TransportOutcome`, never a compliance decision. A refusal
    has no route into this function, which is how "never retry a block" is kept
    true by construction rather than by remembering.
    """
    if outcome.succeeded:
        return False
    if outcome.timed_out or outcome.connection_error:
        return True
    if outcome.http_status is None:
        return True
    if outcome.http_status in TERMINAL_STATUSES:
        return False
    return outcome.http_status in RETRYABLE_STATUSES
