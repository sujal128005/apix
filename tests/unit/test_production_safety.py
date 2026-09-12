"""Phase 19: what production forbids.

Every assertion here is about a *refusal*. A statistical production system
should fail loudly on a misconfiguration rather than fall back to something
that works but is wrong - a wrong figure published is worse than an outage
noticed.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from schemas.environment import (
    Environment,
    ProductionSafetyError,
    current_environment,
    is_production,
    require_not_production,
    requires_explicit_credentials,
)


def test_the_default_environment_is_development() -> None:
    """Between two failure modes, choose the one that announces itself.

    A deployment that wrongly believes it is development fails to find its
    database and stops. One that wrongly believes it is production while on a
    laptop would let demo tooling through silently.
    """
    with mock.patch.dict(os.environ, {}, clear=True):
        assert current_environment() is Environment.DEVELOPMENT
        assert is_production() is False


@pytest.mark.parametrize("value", ["prod", "PRODUCTION_", "live", "prd", "dev"])
def test_an_unrecognised_environment_is_refused(value: str) -> None:
    """A typo must not silently restore development conveniences."""
    with (
        mock.patch.dict(os.environ, {"APIX_ENV": value}, clear=True),
        pytest.raises(ProductionSafetyError, match="not a recognised environment"),
    ):
        current_environment()


@pytest.mark.parametrize("env", ["staging", "production"])
def test_credentials_must_be_explicit_outside_development(env: str) -> None:
    with mock.patch.dict(os.environ, {"APIX_ENV": env}, clear=True):
        assert requires_explicit_credentials() is True


def test_development_still_has_its_conveniences() -> None:
    with mock.patch.dict(os.environ, {"APIX_ENV": "development"}, clear=True):
        assert requires_explicit_credentials() is False


def test_demo_tooling_refuses_to_load_in_production() -> None:
    with (
        mock.patch.dict(os.environ, {"APIX_ENV": "production"}, clear=True),
        pytest.raises(ProductionSafetyError, match="cannot be used in production"),
    ):
        require_not_production("MockAdapter")


def test_a_missing_setting_raises_rather_than_falling_back() -> None:
    """The failure this prevents: a production system pointed at a development
    database, with a development password, silently."""
    from db.settings import MissingConfigurationError, _get

    with (
        mock.patch.dict(os.environ, {"APIX_ENV": "production"}, clear=True),
        pytest.raises(MissingConfigurationError, match="APIX_DB_HOST"),
    ):
        _get("APIX_DB_HOST")


def test_the_refusal_explains_itself() -> None:
    """An operator reading the traceback must learn what to do about it."""
    with mock.patch.dict(os.environ, {"APIX_ENV": "production"}, clear=True):
        try:
            require_not_production("The demo pipeline")
        except ProductionSafetyError as exc:
            message = str(exc)
            assert "synthetic data" in message
            assert "published statistic" in message
            assert "the deployment is wrong" in message
