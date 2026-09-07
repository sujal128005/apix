"""ComplianceToken: unforgeable, single-use, time-limited, path-bound.

These tests attack the token rather than exercise it. Each one attempts an abuse
the design is supposed to make impossible and asserts that it fails.
"""

from __future__ import annotations

import copy
import json
import pickle
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from compliance.errors import (
    ComplianceTokenExpiredError,
    ComplianceTokenForgeryError,
    ComplianceTokenMismatchError,
    ComplianceTokenReusedError,
)
from compliance.token import ComplianceToken, TokenRegistry, mint

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def _token(*, source_id=None, path="/search", issued=NOW, ttl=300) -> ComplianceToken:
    return mint(
        decision_id=uuid4(),
        source_id=source_id or uuid4(),
        path=path,
        user_agent="APIx-Research/0.1 (+https://example.org; MoSPI SIH 2026 PS 26056)",
        issued_at=issued,
        expires_at=issued + timedelta(seconds=ttl),
        crawl_delay=5.0,
    )


# -- forgery ---------------------------------------------------------------


def test_direct_construction_is_forgery() -> None:
    with pytest.raises(ComplianceTokenForgeryError):
        ComplianceToken(
            decision_id=uuid4(),
            source_id=uuid4(),
            path="/search",
            user_agent="ua",
            issued_at=NOW,
            expires_at=NOW + timedelta(seconds=300),
            crawl_delay=5.0,
        )


def test_construction_with_a_guessed_sentinel_is_forgery() -> None:
    """An attacker who knows the shape of the mint key still cannot forge one."""
    for guess in (object(), "MINT", None, True, 0):
        with pytest.raises(ComplianceTokenForgeryError):
            ComplianceToken(
                decision_id=uuid4(),
                source_id=uuid4(),
                path="/search",
                user_agent="ua",
                issued_at=NOW,
                expires_at=NOW + timedelta(seconds=300),
                crawl_delay=5.0,
                mint=guess,
            )


def test_the_gate_can_mint() -> None:
    token = _token()
    assert token.path == "/search"
    assert token.crawl_delay == 5.0


# -- single use ------------------------------------------------------------


def test_a_token_authorises_exactly_one_fetch() -> None:
    registry = TokenRegistry()
    source_id, path = uuid4(), "/search"
    token = _token(source_id=source_id, path=path)

    registry.redeem(token, source_id=source_id, path=path, now=NOW)
    with pytest.raises(ComplianceTokenReusedError):
        registry.redeem(token, source_id=source_id, path=path, now=NOW)


def test_spent_count_tracks_redemptions() -> None:
    registry = TokenRegistry()
    for _ in range(3):
        source_id = uuid4()
        registry.redeem(
            _token(source_id=source_id), source_id=source_id, path="/search", now=NOW
        )
    assert registry.spent_count() == 3


# -- expiry ----------------------------------------------------------------


def test_an_expired_token_is_refused() -> None:
    registry = TokenRegistry()
    source_id = uuid4()
    token = _token(source_id=source_id, ttl=300)
    with pytest.raises(ComplianceTokenExpiredError):
        registry.redeem(
            token, source_id=source_id, path="/search", now=NOW + timedelta(seconds=301)
        )


def test_a_token_inside_its_ttl_is_accepted() -> None:
    registry = TokenRegistry()
    source_id = uuid4()
    token = _token(source_id=source_id, ttl=300)
    registry.redeem(token, source_id=source_id, path="/search", now=NOW + timedelta(seconds=299))


def test_expiry_is_inclusive_at_the_boundary() -> None:
    registry = TokenRegistry()
    source_id = uuid4()
    token = _token(source_id=source_id, ttl=300)
    with pytest.raises(ComplianceTokenExpiredError):
        registry.redeem(
            token, source_id=source_id, path="/search", now=NOW + timedelta(seconds=300)
        )


# -- binding ---------------------------------------------------------------


def test_a_token_cannot_be_used_for_another_path() -> None:
    registry = TokenRegistry()
    source_id = uuid4()
    token = _token(source_id=source_id, path="/allowed")
    with pytest.raises(ComplianceTokenMismatchError):
        registry.redeem(token, source_id=source_id, path="/disallowed", now=NOW)


def test_a_token_cannot_be_used_for_another_source() -> None:
    registry = TokenRegistry()
    token = _token(source_id=uuid4(), path="/search")
    with pytest.raises(ComplianceTokenMismatchError):
        registry.redeem(token, source_id=uuid4(), path="/search", now=NOW)


# -- non-persistence -------------------------------------------------------


def test_a_token_cannot_be_pickled() -> None:
    with pytest.raises(TypeError):
        pickle.dumps(_token())


def test_a_token_cannot_be_copied() -> None:
    token = _token()
    with pytest.raises(TypeError):
        copy.copy(token)
    with pytest.raises(TypeError):
        copy.deepcopy(token)


def test_a_token_is_not_json_serialisable() -> None:
    with pytest.raises(TypeError):
        json.dumps(_token())  # type: ignore[arg-type]


def test_a_token_is_frozen() -> None:
    token = _token()
    with pytest.raises(Exception):  # noqa: B017 - FrozenInstanceError
        token.path = "/elsewhere"  # type: ignore[misc]
