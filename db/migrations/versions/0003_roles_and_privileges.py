"""0003 - database roles and the immutability grants.

**C3 - immutability is a privilege, not a convention.**

Two roles are created:

``apix_migrator``
    Owns and changes structure. Full DDL.

``apix_app``
    What the application connects as. SELECT and INSERT everywhere;
    UPDATE and DELETE only on the eight mutable tables. On the thirteen
    append-only (IMM) tables both are revoked, so an attempt raises
    ``InsufficientPrivilege`` from PostgreSQL itself. No amount of application
    code, ORM misuse or manual psql can edit a raw payload, a compliance
    decision, a cleaning event or a published index value.

Corrections are made by inserting a new row under a new version.

Roles are cluster-global while grants are per-database. That asymmetry shapes
the downgrade: privileges in *this* database are dropped unconditionally, but
the role itself is only dropped if nothing anywhere else in the cluster still
depends on it. A downgrade run against a throwaway database therefore leaves
the shared roles alone instead of breaking every other database that uses them.

Passwords come from the environment (see ``db/settings.py`` and
``.env.example``). Nothing credential-shaped is committed. They are applied only
when a role is first created, so re-running this revision never silently
rotates a password.

Revision ID: 0003_roles_and_privileges
Revises: 0002_constraint_triggers
Create Date: 2026-09-07

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from db.settings import DbSettings

revision: str = "0003_roles_and_privileges"
down_revision: str | None = "0002_constraint_triggers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Frozen copy of the append-only table list. `schemas.models.IMMUTABLE_TABLES`
# carries the same names for application code;
# tests/integration/test_roles_and_privileges.py asserts the live grants match
# that list, so the two cannot drift apart unnoticed.
IMMUTABLE_TABLES: tuple[str, ...] = (
    "backtest_run",
    "benchmark_observation",
    "cleaning_event",
    "collection_request",
    "compliance_decision",
    "index_contribution",
    "index_observation",
    "methodology_version",
    "raw_quote",
    "raw_response",
    "route_weight",
    "source_review",
    "weight_set_version",
)


def _quote(identifier: str, literal: str) -> tuple[str, str]:
    """Quote an identifier and a literal using PostgreSQL's own quoting functions.

    DDL cannot take bind parameters, so role names and passwords have to be
    interpolated. Doing the quoting server-side with quote_ident/quote_literal
    means the escaping rules are PostgreSQL's, not a hand-rolled approximation.
    """
    row = op.get_bind().execute(
        sa.text("SELECT quote_ident(:ident) AS ident, quote_literal(:lit) AS lit"),
        {"ident": identifier, "lit": literal},
    ).one()
    return row.ident, row.lit


def _create_login_role(role: str, password: str) -> None:
    """Create a LOGIN role if the cluster does not already have it.

    The password is set only at creation. A re-run against a second database in
    the same cluster finds the role present and leaves its password untouched,
    which also means this revision does not require superuser after the first
    bootstrap.
    """
    bind = op.get_bind()
    already_present = bind.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
    ).first()
    if already_present:
        return

    ident, lit = _quote(role, password)
    op.execute(f"CREATE ROLE {ident} LOGIN PASSWORD {lit}")


def _drop_role_if_unused(role: str) -> None:
    """Drop a cluster-global role, but only if nothing else still depends on it.

    ``DROP OWNED BY`` removes the role's objects and privileges *in the current
    database only* (plus grants on shared objects such as the database itself).
    If another database in the cluster still grants to this role, ``DROP ROLE``
    raises ``dependent_objects_still_exist`` (2BP01); that is caught and the role
    is left in place, because destroying a shared role on behalf of one database
    would be wrong.
    """
    bind = op.get_bind()
    present = bind.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
    ).first()
    if not present:
        return

    ident, _ = _quote(role, "")
    op.execute(f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {ident}")
    op.execute(f"REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM {ident}")
    op.execute(f"REVOKE ALL PRIVILEGES ON SCHEMA public FROM {ident}")
    op.execute(f"DROP OWNED BY {ident}")
    op.execute(
        f"""
        DO $do$
        BEGIN
            DROP ROLE {ident};
        EXCEPTION WHEN dependent_objects_still_exist THEN
            RAISE NOTICE
                'APIx role kept: another database in this cluster still depends on it';
        END
        $do$;
        """
    )


def upgrade() -> None:
    settings = DbSettings.from_env()

    _create_login_role(settings.migrator_user, settings.migrator_password)
    _create_login_role(settings.app_user, settings.app_password)

    migrator, _ = _quote(settings.migrator_user, "")
    app, _ = _quote(settings.app_user, "")

    # --- apix_migrator: owns and changes structure --------------------------
    op.execute(
        sa.text(
            f"""
            DO $do$
            BEGIN
                EXECUTE format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO {migrator}',
                               current_database());
            END
            $do$;
            """
        )
    )
    op.execute(f"GRANT ALL PRIVILEGES ON SCHEMA public TO {migrator}")
    op.execute(f"GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {migrator}")
    op.execute(f"GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO {migrator}")

    # --- apix_app: DML, minus UPDATE/DELETE on the append-only tables -------
    op.execute(
        sa.text(
            f"""
            DO $do$
            BEGIN
                EXECUTE format('GRANT CONNECT ON DATABASE %I TO {app}', current_database());
            END
            $do$;
            """
        )
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {app}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {app}")
    op.execute(f"GRANT EXECUTE ON FUNCTION uuidv7() TO {app}")

    # Alembic's bookkeeping is not application data.
    op.execute(f"REVOKE ALL PRIVILEGES ON TABLE alembic_version FROM {app}")

    # The immutability barrier itself.
    for table in IMMUTABLE_TABLES:
        op.execute(f"REVOKE UPDATE, DELETE ON TABLE {table} FROM {app}")

    # route_undirected is a read model over `route`; it is never written.
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON TABLE route_undirected FROM {app}")


def downgrade() -> None:
    settings = DbSettings.from_env()
    _drop_role_if_unused(settings.app_user)
    _drop_role_if_unused(settings.migrator_user)
