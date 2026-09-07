"""Shared pytest fixtures.

The integration suite runs against a real PostgreSQL 16 instance - the one in
``docker-compose.yml`` unless the environment points elsewhere. A throwaway
database (``APIX_TEST_DB_NAME``, default ``apix_test``) is created once per
session, migrated, seeded, and dropped afterwards. Set ``APIX_KEEP_TEST_DB=1``
to keep it for inspection.

Two session flavours are offered, because immutability and deferred constraints
need different things:

``app_session``
    Connects as ``apix_app`` inside an outer transaction that is rolled back at
    the end of the test. ``session.commit()`` maps to a savepoint release, so
    tests stay isolated. This is the default.

``committing_session``
    Connects as ``apix_app`` and really commits. Needed to prove that the
    deferred weight-sum trigger fires at COMMIT rather than at statement time.
    Teardown truncates every table as the superuser and reloads the seeds.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from db import migrate
from db.seeds import seed_all
from db.settings import DbSettings
from schemas.models import ALL_TABLES

if TYPE_CHECKING:
    from tests.support.builders import SeedRefs

FIXTURE_ROOT = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# fixture data files
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def golden_day() -> dict[str, Any]:
    """The golden-day fixture from build brief section 8."""
    path = FIXTURE_ROOT / "golden_day" / "golden_day.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def adversarial_manifest() -> dict[str, Any]:
    """The manifest of known-bad inputs from build brief section 8."""
    path = FIXTURE_ROOT / "adversarial" / "adversarial_cases.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# database session scaffolding
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def db_settings() -> DbSettings:
    return DbSettings.from_env()


@pytest.fixture(scope="session")
def _require_postgres(db_settings: DbSettings) -> None:
    """Fail loudly, and usefully, if the cluster is not reachable."""
    engine = create_engine(db_settings.maintenance_url(), future=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError as exc:  # pragma: no cover - environment problem
        pytest.fail(
            f"PostgreSQL is not reachable at {db_settings.host}:{db_settings.port}.\n"
            f"Start it with `docker compose up -d`.\nUnderlying error: {exc}",
            pytrace=False,
        )
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def migrated_database(db_settings: DbSettings, _require_postgres: None) -> Iterator[str]:
    """Create, migrate and seed the throwaway test database for this session."""
    name = db_settings.test_database
    admin = create_engine(db_settings.maintenance_url(), future=True, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            ident = connection.execute(
                text("SELECT quote_ident(:name) AS ident"), {"name": name}
            ).scalar_one()
            connection.execute(text(f"DROP DATABASE IF EXISTS {ident} WITH (FORCE)"))
            connection.execute(text(f"CREATE DATABASE {ident}"))

        url = db_settings.superuser_url(database=name)
        migrate.upgrade(url)

        engine = create_engine(url, future=True)
        try:
            with engine.begin() as connection:
                seed_all(connection)
        finally:
            engine.dispose()

        yield name

        if not os.environ.get("APIX_KEEP_TEST_DB"):
            with admin.connect() as connection:
                ident = connection.execute(
                    text("SELECT quote_ident(:name) AS ident"), {"name": name}
                ).scalar_one()
                connection.execute(text(f"DROP DATABASE IF EXISTS {ident} WITH (FORCE)"))
    finally:
        admin.dispose()


@pytest.fixture(scope="session")
def admin_engine(db_settings: DbSettings, migrated_database: str) -> Iterator[Engine]:
    """Superuser connection to the test database. Used for setup and teardown only."""
    engine = create_engine(db_settings.superuser_url(database=migrated_database), future=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_engine(db_settings: DbSettings, migrated_database: str) -> Iterator[Engine]:
    """The role the application uses: apix_app, with UPDATE/DELETE revoked on IMM tables."""
    engine = create_engine(db_settings.app_url(database=migrated_database), future=True)
    yield engine
    engine.dispose()


@pytest.fixture
def app_session(app_engine: Engine) -> Iterator[Session]:
    """A rolled-back session as apix_app.

    ``join_transaction_mode='create_savepoint'`` means a test may call
    ``commit()`` freely: it releases a savepoint rather than ending the outer
    transaction, so nothing survives the test.
    """
    connection = app_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _reset_database(admin_engine: Engine) -> None:
    """Truncate every table as superuser, then reload the seeds."""
    quoted = ", ".join(ALL_TABLES)
    with admin_engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
        seed_all(connection)


@pytest.fixture
def committing_session(app_engine: Engine, admin_engine: Engine) -> Iterator[Session]:
    """A session as apix_app that really commits.

    Required to observe DEFERRABLE INITIALLY DEFERRED constraint triggers, which
    fire at COMMIT and nowhere else. Everything written is removed afterwards by
    truncating as the superuser - apix_app cannot delete from an IMM table, and
    that is the point.
    """
    session = Session(bind=app_engine)
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        _reset_database(admin_engine)


@pytest.fixture
def refs(app_session: Session) -> SeedRefs:
    """Primary keys of the seeded reference rows, for the rolled-back session."""
    from tests.support.builders import load_refs

    return load_refs(app_session)


@pytest.fixture
def committing_refs(committing_session: Session) -> SeedRefs:
    """Primary keys of the seeded reference rows, for the committing session."""
    from tests.support.builders import load_refs

    return load_refs(committing_session)
