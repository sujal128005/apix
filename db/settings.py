"""Database connection settings, read from the environment.

Values come from the environment (``.env`` is loaded if present). The fallbacks
below exist so that a fresh checkout works against the local
``docker-compose.yml`` container with no configuration at all; they are
development-container defaults, not secrets, and they match the defaults in
``docker-compose.yml``.

**They apply in development only.** With ``APIX_ENV`` set to staging or
production, a missing variable raises rather than falling back: pointing a
statistical production system at a development database, silently, is how a
wrong figure gets published instead of an outage getting noticed.

The published port defaults to 5433 rather than 5432 so APIx does not collide
with another PostgreSQL already bound to the conventional port.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

from schemas.environment import current_environment, requires_explicit_credentials


class MissingConfigurationError(RuntimeError):
    """A required setting is absent outside development."""

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

_LOCAL_DEV_DEFAULTS: Final[dict[str, str]] = {
    "APIX_DB_HOST": "127.0.0.1",
    "APIX_DB_PORT": "5433",
    "APIX_DB_NAME": "apix",
    "APIX_DB_SUPERUSER": "postgres",
    "APIX_DB_SUPERUSER_PASSWORD": "apix_local_dev_only",
    "APIX_MIGRATOR_USER": "apix_migrator",
    "APIX_MIGRATOR_PASSWORD": "apix_migrator_local_dev_only",
    "APIX_APP_USER": "apix_app",
    "APIX_APP_PASSWORD": "apix_app_local_dev_only",
    "APIX_TEST_DB_NAME": "apix_test",
}

_dotenv_loaded = False


def _load_dotenv_once() -> None:
    global _dotenv_loaded
    if not _dotenv_loaded:
        load_dotenv(REPO_ROOT / ".env", override=False)
        _dotenv_loaded = True


def _get(key: str) -> str:
    """Read a setting, falling back to a local-dev default only in development.

    In staging and production a missing variable raises. A silent fallback there
    would point a statistical production system at a development database with
    a development password, and it would do so without saying anything - which
    is exactly the class of failure that produces a wrong published figure
    rather than an outage.
    """
    _load_dotenv_once()
    value = os.environ.get(key, "").strip()
    if value:
        return value

    if requires_explicit_credentials():
        raise MissingConfigurationError(
            f"{key} is not set. APIX_ENV={current_environment().value} requires "
            "every database setting to be explicit; the local development "
            "defaults are not applied outside development."
        )
    return _LOCAL_DEV_DEFAULTS[key]


@dataclass(frozen=True, slots=True)
class DbSettings:
    """Everything needed to reach the APIx cluster as any of its three roles."""

    host: str
    port: int
    database: str
    superuser: str
    superuser_password: str
    migrator_user: str
    migrator_password: str
    app_user: str
    app_password: str
    test_database: str

    @classmethod
    def from_env(cls) -> DbSettings:
        return cls(
            host=_get("APIX_DB_HOST"),
            port=int(_get("APIX_DB_PORT")),
            database=_get("APIX_DB_NAME"),
            superuser=_get("APIX_DB_SUPERUSER"),
            superuser_password=_get("APIX_DB_SUPERUSER_PASSWORD"),
            migrator_user=_get("APIX_MIGRATOR_USER"),
            migrator_password=_get("APIX_MIGRATOR_PASSWORD"),
            app_user=_get("APIX_APP_USER"),
            app_password=_get("APIX_APP_PASSWORD"),
            test_database=_get("APIX_TEST_DB_NAME"),
        )

    def url(self, *, user: str, password: str, database: str | None = None) -> str:
        """Build a SQLAlchemy URL for an arbitrary role."""
        from urllib.parse import quote_plus

        db = database if database is not None else self.database
        return (
            f"postgresql+psycopg://{quote_plus(user)}:{quote_plus(password)}"
            f"@{self.host}:{self.port}/{db}"
        )

    def superuser_url(self, database: str | None = None) -> str:
        return self.url(
            user=self.superuser, password=self.superuser_password, database=database
        )

    def migrator_url(self, database: str | None = None) -> str:
        return self.url(
            user=self.migrator_user, password=self.migrator_password, database=database
        )

    def app_url(self, database: str | None = None) -> str:
        return self.url(user=self.app_user, password=self.app_password, database=database)

    def maintenance_url(self) -> str:
        """Superuser connection to the `postgres` database, for CREATE/DROP DATABASE."""
        return self.superuser_url(database="postgres")


__all__ = ["REPO_ROOT", "DbSettings"]
