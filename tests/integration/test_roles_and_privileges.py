"""C3 - immutability is enforced by PostgreSQL, not by convention.

Thirteen tables are append-only. The application role holds SELECT and INSERT on
them and nothing more, so an UPDATE or DELETE fails with
``InsufficientPrivilege`` before a single row is examined. That is what makes
"we never edit raw payloads" a property of the system rather than a promise
about our own discipline.

Every append-only table is checked individually. A missing REVOKE on one table
is exactly the kind of gap that survives a code review.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError

from db.settings import DbSettings
from schemas.models import ALL_TABLES, IMMUTABLE_TABLES, MUTABLE_TABLES

pytestmark = [pytest.mark.integration, pytest.mark.constraint]


def test_both_roles_exist(admin_engine: Engine, db_settings: DbSettings) -> None:
    with admin_engine.connect() as connection:
        roles = set(
            connection.execute(
                text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:names)"),
                {"names": [db_settings.migrator_user, db_settings.app_user]},
            ).scalars()
        )
    assert roles == {db_settings.migrator_user, db_settings.app_user}


def test_the_application_role_has_no_elevated_attributes(
    admin_engine: Engine, db_settings: DbSettings
) -> None:
    with admin_engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls
                FROM pg_roles WHERE rolname = :name
                """
            ),
            {"name": db_settings.app_user},
        ).one()
    assert row.rolsuper is False
    assert row.rolcreaterole is False
    assert row.rolcreatedb is False
    assert row.rolbypassrls is False


@pytest.mark.parametrize("table", sorted(IMMUTABLE_TABLES))
def test_update_on_an_append_only_table_is_denied(app_engine: Engine, table: str) -> None:
    """No amount of application code can rewrite history."""
    with app_engine.connect() as connection, pytest.raises(ProgrammingError) as caught:
        connection.execute(text(f"UPDATE {table} SET created_at = now()"))
    assert "permission denied" in str(caught.value).lower()


@pytest.mark.parametrize("table", sorted(IMMUTABLE_TABLES))
def test_delete_on_an_append_only_table_is_denied(app_engine: Engine, table: str) -> None:
    """Corrections are new rows under a new version, never deletions."""
    with app_engine.connect() as connection, pytest.raises(ProgrammingError) as caught:
        connection.execute(text(f"DELETE FROM {table}"))
    assert "permission denied" in str(caught.value).lower()


@pytest.mark.parametrize("table", sorted(IMMUTABLE_TABLES))
def test_append_only_tables_still_accept_reads_and_writes(
    app_engine: Engine, table: str
) -> None:
    """Append-only means append-only, not read-only."""
    with app_engine.connect() as connection:
        connection.execute(text(f"SELECT count(*) FROM {table}"))
        privileges = connection.execute(
            text(
                """
                SELECT
                    has_table_privilege(current_user, :table, 'SELECT') AS can_select,
                    has_table_privilege(current_user, :table, 'INSERT') AS can_insert,
                    has_table_privilege(current_user, :table, 'UPDATE') AS can_update,
                    has_table_privilege(current_user, :table, 'DELETE') AS can_delete
                """
            ),
            {"table": table},
        ).one()
    assert privileges.can_select is True
    assert privileges.can_insert is True
    assert privileges.can_update is False
    assert privileges.can_delete is False


@pytest.mark.parametrize("table", sorted(MUTABLE_TABLES))
def test_mutable_tables_keep_full_dml(app_engine: Engine, table: str) -> None:
    """The eight tables that are not append-only must not have been over-revoked."""
    with app_engine.connect() as connection:
        privileges = connection.execute(
            text(
                """
                SELECT
                    has_table_privilege(current_user, :table, 'SELECT') AS can_select,
                    has_table_privilege(current_user, :table, 'INSERT') AS can_insert,
                    has_table_privilege(current_user, :table, 'UPDATE') AS can_update,
                    has_table_privilege(current_user, :table, 'DELETE') AS can_delete
                """
            ),
            {"table": table},
        ).one()
    assert all(
        (privileges.can_select, privileges.can_insert, privileges.can_update, privileges.can_delete)
    )


def test_a_mutable_table_really_can_be_updated(app_engine: Engine) -> None:
    """Proves the privilege check above is not vacuous."""
    with app_engine.connect() as connection:
        transaction = connection.begin()
        result = connection.execute(text("UPDATE airport SET active = true WHERE iata = 'DEL'"))
        assert result.rowcount == 1
        transaction.rollback()


def test_live_grants_match_the_declared_immutable_list(app_engine: Engine) -> None:
    """The database is the authority; this asserts the code's list agrees with it."""
    with app_engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    t.table_name,
                    has_table_privilege(current_user, t.table_name, 'UPDATE') AS can_update,
                    has_table_privilege(current_user, t.table_name, 'DELETE') AS can_delete
                FROM unnest(CAST(:tables AS text[])) AS t(table_name)
                """
            ),
            {"tables": list(ALL_TABLES)},
        ).all()

    append_only = {row.table_name for row in rows if not (row.can_update or row.can_delete)}
    writable = {row.table_name for row in rows if row.can_update and row.can_delete}

    assert append_only == set(IMMUTABLE_TABLES)
    assert writable == set(MUTABLE_TABLES)


def test_alembic_bookkeeping_is_not_application_data(app_engine: Engine) -> None:
    with app_engine.connect() as connection:
        can_select = connection.execute(
            text("SELECT has_table_privilege(current_user, 'alembic_version', 'SELECT')")
        ).scalar_one()
    assert can_select is False


def test_the_undirected_route_view_is_read_only(app_engine: Engine) -> None:
    with app_engine.connect() as connection:
        privileges = connection.execute(
            text(
                """
                SELECT
                    has_table_privilege(current_user, 'route_undirected', 'SELECT') AS can_select,
                    has_table_privilege(current_user, 'route_undirected', 'INSERT') AS can_insert
                """
            )
        ).one()
    assert privileges.can_select is True
    assert privileges.can_insert is False


def test_the_application_role_cannot_create_tables(app_engine: Engine) -> None:
    """DDL belongs to apix_migrator. The app role must not be able to reshape the schema."""
    with app_engine.connect() as connection, pytest.raises(ProgrammingError) as caught:
        connection.execute(text("CREATE TABLE should_not_exist (id int)"))
    assert "permission denied" in str(caught.value).lower()


def test_base_period_is_mutable_but_its_references_are_not(app_engine: Engine) -> None:
    """A definition may be refined; the value that recorded it may not be rewritten.

    ``base_period`` is the one versioned definition that is not append-only
    (architect ruling, review round 2). Phase 9 establishes it from real
    collection dates and may correct it before anything is published.

    Reproducibility survives that because the reference is frozen even though the
    definition is not: ``index_observation`` is append-only, so a published row
    can never be repointed at a different base period, and the foreign key stops
    a base period being deleted while a published value still points at it.
    """
    with app_engine.connect() as connection:
        privileges = connection.execute(
            text(
                """
                SELECT
                    has_table_privilege(current_user, 'base_period', 'UPDATE') AS period_update,
                    has_table_privilege(current_user, 'base_period', 'DELETE') AS period_delete,
                    has_table_privilege(current_user, 'index_observation', 'UPDATE')
                        AS observation_update
                """
            )
        ).one()

    assert privileges.period_update is True
    assert privileges.period_delete is True
    assert privileges.observation_update is False


def test_the_other_versioned_definitions_stay_append_only(app_engine: Engine) -> None:
    """base_period is the exception, not a precedent."""
    with app_engine.connect() as connection:
        for table in ("methodology_version", "weight_set_version", "route_weight"):
            can_update = connection.execute(
                text("SELECT has_table_privilege(current_user, :table, 'UPDATE')"),
                {"table": table},
            ).scalar_one()
            assert can_update is False, f"{table} should still be append-only"
