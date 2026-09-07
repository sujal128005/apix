"""The capability token (ADR-018).

A test asserting "the gate was called" proves that *today's* code calls the
gate. It says nothing about code written six phases from now. So the guarantee
is made structural instead of behavioural.

``ComplianceToken`` can only be constructed by the gate, because construction
requires a module-private sentinel that is not exported and not reachable from
the package's public surface. Every function that performs a network request
takes a token as an argument. A caller who skipped the gate cannot obtain one -
not because a rule forbids it, but because the object cannot be built.

Tokens are single-use, time-limited, and bound to one (source, path) pair. They
are never persisted and never serialised: a token is a fact about this process
at this moment, and writing one down would make it forgeable.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from compliance.errors import (
    ComplianceTokenExpiredError,
    ComplianceTokenForgeryError,
    ComplianceTokenMismatchError,
    ComplianceTokenReusedError,
)

__all__ = ["ComplianceToken", "TokenRegistry"]

# The mint key. Deliberately module-private, absent from __all__, and never
# re-exported by __init__.py. The gate imports it; nothing else may.
_MINT_KEY: Final[object] = object()


@dataclass(frozen=True, slots=True)
class ComplianceToken:
    """Proof that the gate approved one specific fetch.

    Construct only via :func:`compliance.token.mint`, which the gate alone
    calls. Direct construction raises :class:`ComplianceTokenForgeryError`.
    """

    decision_id: UUID
    source_id: UUID
    path: str
    user_agent: str
    issued_at: datetime
    expires_at: datetime
    crawl_delay: float
    mint: InitVar[Any] = field(default=None)

    def __post_init__(self, mint: Any) -> None:
        if mint is not _MINT_KEY:
            raise ComplianceTokenForgeryError(
                "ComplianceToken may only be minted by the compliance gate. "
                "Call compliance.gate.evaluate() to obtain one."
            )

    # -- serialisation is refused, not merely absent --------------------------
    # A token written to disk or sent over a wire could be replayed. Every hook
    # that would let that happen raises instead.

    def __reduce__(self) -> Any:
        raise TypeError("ComplianceToken is not picklable: a token must not outlive its process.")

    def __getstate__(self) -> Any:
        raise TypeError("ComplianceToken is not serialisable.")

    def __copy__(self) -> Any:
        raise TypeError("ComplianceToken must not be copied: tokens are single-use.")

    def __deepcopy__(self, memo: dict[int, Any]) -> Any:
        raise TypeError("ComplianceToken must not be copied: tokens are single-use.")

    def is_expired(self, *, now: datetime | None = None) -> bool:
        return (now or datetime.now(UTC)) >= self.expires_at

    def matches(self, *, source_id: UUID, path: str) -> bool:
        return self.source_id == source_id and self.path == path


def mint(
    *,
    decision_id: UUID,
    source_id: UUID,
    path: str,
    user_agent: str,
    issued_at: datetime,
    expires_at: datetime,
    crawl_delay: float,
) -> ComplianceToken:
    """Mint a token. Callable in practice only from the gate, which holds the key."""
    return ComplianceToken(
        decision_id=decision_id,
        source_id=source_id,
        path=path,
        user_agent=user_agent,
        issued_at=issued_at,
        expires_at=expires_at,
        crawl_delay=crawl_delay,
        mint=_MINT_KEY,
    )


class TokenRegistry:
    """Tracks which tokens have been spent, so that none is spent twice.

    In-process and deliberately not shared. A registry that survived a restart
    would be a persisted token store by another name.
    """

    def __init__(self) -> None:
        self._spent: set[UUID] = set()

    def redeem(
        self,
        token: ComplianceToken,
        *,
        source_id: UUID,
        path: str,
        now: datetime | None = None,
    ) -> ComplianceToken:
        """Spend a token for one fetch, or raise explaining why it cannot be spent."""
        if token.decision_id in self._spent:
            raise ComplianceTokenReusedError(
                f"Token {token.decision_id} has already authorised a fetch. "
                "Return to the gate for each request."
            )
        if token.is_expired(now=now):
            raise ComplianceTokenExpiredError(
                f"Token {token.decision_id} expired at {token.expires_at.isoformat()}. "
                "Conditions may have changed; re-evaluate."
            )
        if not token.matches(source_id=source_id, path=path):
            raise ComplianceTokenMismatchError(
                f"Token {token.decision_id} authorises "
                f"source={token.source_id} path={token.path!r}, "
                f"not source={source_id} path={path!r}."
            )
        self._spent.add(token.decision_id)
        return token

    def spent_count(self) -> int:
        return len(self._spent)
