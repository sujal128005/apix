"""Programmatic access to the Alembic migrations.

``scripts/init_db.py`` and the integration test suite both need to run
migrations against a URL chosen at runtime (the development database, or a
throwaway one). Doing that through Alembic's Python API keeps a single
definition of where the scripts live and how the URL is supplied.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from db.settings import REPO_ROOT

ALEMBIC_INI: Path = REPO_ROOT / "db" / "alembic.ini"
SCRIPT_LOCATION: Path = REPO_ROOT / "db" / "migrations"

# route_undirected is a view created by revision 0001, and alembic_version is
# Alembic's own bookkeeping. Neither is part of Base.metadata, so both are kept
# out of autogenerate comparisons - otherwise every diff would propose
# dropping them.
EXCLUDED_OBJECTS: frozenset[str] = frozenset({"route_undirected", "alembic_version"})


def include_object(
    obj: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object,
) -> bool:
    """Alembic hook: keep views and bookkeeping out of schema comparisons."""
    return not (type_ == "table" and name in EXCLUDED_OBJECTS)


def alembic_config(url: str) -> Config:
    """Build an Alembic Config pinned to this repository and the given URL."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(SCRIPT_LOCATION))
    config.set_main_option("sqlalchemy.url", url)
    return config


def upgrade(url: str, revision: str = "head") -> None:
    """Run ``alembic upgrade`` against ``url``."""
    command.upgrade(alembic_config(url), revision)


def downgrade(url: str, revision: str = "base") -> None:
    """Run ``alembic downgrade`` against ``url``."""
    command.downgrade(alembic_config(url), revision)


def current_revision(url: str) -> str | None:
    """Return the revision stamped on ``url``, or None if the database is empty."""
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine

    engine = create_engine(url, future=True)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


__all__ = [
    "ALEMBIC_INI",
    "EXCLUDED_OBJECTS",
    "SCRIPT_LOCATION",
    "alembic_config",
    "current_revision",
    "downgrade",
    "include_object",
    "upgrade",
]
