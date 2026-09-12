"""Migrations are reversible, and they produce exactly what the models describe.

Two properties, both of which quietly rot without a test:

* ``alembic downgrade base`` followed by ``upgrade head`` runs clean. A
  migration nobody can reverse is a migration nobody can review.
* The migrated database and ``Base.metadata`` agree. The initial revision was
  generated from the models and then hand-extended with a function, a view,
  triggers and roles; this asserts the hand-editing did not put the two out of
  step, which is what makes the models a trustworthy description of the schema.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import ProgrammingError

from db import migrate
from db.settings import DbSettings
from schemas.models import ALL_TABLES, Base

pytestmark = pytest.mark.integration

SCRATCH_DATABASE = "apix_migration_reversibility"

# alembic_version.version_num is VARCHAR(32); a longer revision id fails at
# stamp time, after the DDL has already run.
ALEMBIC_VERSION_NUM_LIMIT = 32


def test_migrated_schema_matches_the_models(admin_engine: Engine) -> None:
    """Autogenerate finds nothing to do against a freshly migrated database."""
    with admin_engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"include_object": migrate.include_object, "compare_type": True},
        )
        differences = compare_metadata(context, Base.metadata)

    assert differences == [], (
        "the migrated database and the ORM models disagree:\n"
        + "\n".join(repr(difference) for difference in differences)
    )


def test_head_revision_is_the_latest_revision(admin_engine: Engine) -> None:
    with admin_engine.connect() as connection:
        revision = MigrationContext.configure(connection).get_current_revision()
    assert revision == "0006_revisions_and_publication"


@pytest.fixture
def scratch_database(db_settings: DbSettings, migrated_database: str) -> Iterator[str]:
    """A second, disposable database used to exercise upgrade/downgrade cycles."""
    admin = create_engine(db_settings.maintenance_url(), future=True, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{SCRATCH_DATABASE}" WITH (FORCE)'))
            connection.execute(text(f'CREATE DATABASE "{SCRATCH_DATABASE}"'))
        yield SCRATCH_DATABASE
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{SCRATCH_DATABASE}" WITH (FORCE)'))
    finally:
        admin.dispose()


def table_names(url: str) -> set[str]:
    engine = create_engine(url, future=True)
    try:
        return set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def test_upgrade_downgrade_upgrade_runs_clean(
    db_settings: DbSettings, scratch_database: str
) -> None:
    """From empty to head, back to base, and up again - on a database of its own."""
    url = db_settings.superuser_url(database=scratch_database)

    assert table_names(url) == set(), "the scratch database did not start empty"

    migrate.upgrade(url)
    assert table_names(url) == set(ALL_TABLES)
    assert migrate.current_revision(url) == "0006_revisions_and_publication"

    migrate.downgrade(url, "base")
    assert table_names(url) == set(), "downgrade base left tables behind"
    assert migrate.current_revision(url) is None

    migrate.upgrade(url)
    assert table_names(url) == set(ALL_TABLES)
    assert migrate.current_revision(url) == "0006_revisions_and_publication"


def test_downgrade_removes_the_view_and_the_uuid_generator(
    db_settings: DbSettings, scratch_database: str
) -> None:
    url = db_settings.superuser_url(database=scratch_database)
    migrate.upgrade(url)

    engine = create_engine(url, future=True)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM route_undirected")).scalar_one() == 0
            assert connection.execute(text("SELECT uuidv7()")).scalar_one().version == 7
    finally:
        engine.dispose()

    migrate.downgrade(url, "base")

    engine = create_engine(url, future=True)
    try:
        with engine.connect() as connection, pytest.raises(ProgrammingError):
            connection.execute(text("SELECT count(*) FROM route_undirected"))
        with engine.connect() as connection, pytest.raises(ProgrammingError):
            connection.execute(text("SELECT uuidv7()"))
    finally:
        engine.dispose()


def test_downgrade_of_one_database_leaves_shared_roles_intact(
    db_settings: DbSettings, scratch_database: str, app_engine: Engine
) -> None:
    """Roles are cluster-global; a per-database downgrade must not break other databases.

    ``DROP ROLE`` raises ``dependent_objects_still_exist`` while the main test
    database still grants to the role, and revision 0003 deliberately catches
    that and leaves the role alone. This asserts the outcome that matters: after
    the scratch database is taken back to base, ``apix_app`` still works, and it
    still cannot write to an append-only table.
    """
    url = db_settings.superuser_url(database=scratch_database)
    migrate.upgrade(url)
    migrate.downgrade(url, "base")

    with app_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM airport")).scalar_one() == 10
        with pytest.raises(ProgrammingError, match="permission denied"):
            connection.execute(text("UPDATE raw_response SET http_status = 500"))


def test_every_revision_id_fits_the_version_column() -> None:
    """alembic_version.version_num is VARCHAR(32).

    A longer id fails when Alembic stamps the revision - after the migration's
    DDL has run - so the failure looks like a broken migration rather than a
    naming problem. Cheaper to assert than to debug twice.
    """
    from alembic.script import ScriptDirectory

    scripts = ScriptDirectory.from_config(migrate.alembic_config("postgresql://unused"))
    too_long = {
        revision.revision
        for revision in scripts.walk_revisions()
        if len(revision.revision) > ALEMBIC_VERSION_NUM_LIMIT
    }
    assert not too_long, f"revision ids over {ALEMBIC_VERSION_NUM_LIMIT} characters: {too_long}"
