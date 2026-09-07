"""Retry policy: retry the wire, never retry a refusal."""

from __future__ import annotations

import pytest

from collector.retry import RetryPolicy, TransportOutcome, is_retryable


def _status(code: int) -> TransportOutcome:
    return TransportOutcome(http_status=code)


# -- what is retryable -----------------------------------------------------


@pytest.mark.parametrize("code", [500, 502, 503, 504])
def test_server_errors_are_retryable(code: int) -> None:
    assert is_retryable(_status(code)) is True


def test_timeouts_and_connection_failures_are_retryable() -> None:
    assert is_retryable(TransportOutcome(http_status=None, timed_out=True)) is True
    assert is_retryable(TransportOutcome(http_status=None, connection_error=True)) is True


@pytest.mark.parametrize("code", [200, 201, 204])
def test_success_is_not_retried(code: int) -> None:
    assert is_retryable(_status(code)) is False


# -- what is not ------------------------------------------------------------


@pytest.mark.parametrize("code", [400, 401, 403, 404, 410, 422])
def test_client_errors_are_terminal(code: int) -> None:
    """Retrying a 403 is asking a site that said no to say no again."""
    assert is_retryable(_status(code)) is False


def test_429_is_never_retried() -> None:
    """Being told to slow down is an instruction, not a transport failure.

    The runner honours it by deferring the source. Retrying would be the exact
    behaviour the status code exists to prevent.
    """
    assert is_retryable(_status(429)) is False


def test_the_policy_takes_no_compliance_decision() -> None:
    """A refusal has no route into the retry path.

    ``is_retryable`` accepts a TransportOutcome only, so "never retry a block"
    holds by construction: there is no argument you could pass that would
    express a compliance verdict.
    """
    import inspect

    signature = inspect.signature(is_retryable)
    (parameter,) = signature.parameters.values()
    assert parameter.annotation == "TransportOutcome"


# -- attempts and backoff ---------------------------------------------------


def test_three_attempts_means_one_try_and_two_retries() -> None:
    policy = RetryPolicy(max_attempts=3)
    outcome = _status(503)
    assert policy.should_retry(outcome, attempt=1) is True
    assert policy.should_retry(outcome, attempt=2) is True
    assert policy.should_retry(outcome, attempt=3) is False


def test_backoff_grows_and_the_first_attempt_never_waits() -> None:
    policy = RetryPolicy(base_delay_seconds=2.0, multiplier=3.0)
    assert policy.delay_for(1) == 0.0
    assert policy.delay_for(2) == 2.0
    assert policy.delay_for(3) == 6.0


def test_a_terminal_status_is_not_retried_even_on_the_first_attempt() -> None:
    assert RetryPolicy().should_retry(_status(403), attempt=1) is False
