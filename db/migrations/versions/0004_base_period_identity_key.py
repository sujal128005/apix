"""0004 - architect corrections from the Phase 3 review.

Four amendments to the spec, applied as a forward migration rather than by
editing 0001. A migration that has been run is history; corrections are new
revisions, which is the same rule this schema applies to its own data.

1. ``base_period`` table, and ``index_observation.base_period_id`` becomes a
   real foreign key to it. A published index value means nothing without the
   period it is 100 against, and that period is a pinned definition rather than
   a constant in code. Ships empty: the base period is established in Phase 9
   from real collection dates.

2. ``uq_index_observation_identity`` becomes ``UNIQUE NULLS NOT DISTINCT``.
   ``ref_id`` and ``bucket_id`` are both NULL on a HEADLINE row, and
   PostgreSQL's default treats NULLs as distinct, so two headline values could
   exist for the same date and methodology version. That duplicate would break
   the reproducibility guarantee the whole project rests on.

   ``uq_normalised_quote_dedup`` deliberately keeps the default NULLS DISTINCT:
   imputed rows legitimately carry a NULL ``flight_no`` and several may coexist
   in one stratum, and two partial extractions are not provably the same offer.
   Near-duplicate detection there is a cleaning-layer concern - recorded in
   docs/deferred.md as a Phase 7 requirement, not solved with a key.

3. ``collection_request`` travel/collection check becomes strict. Every
   lead-time bucket has ``days >= 1``, so ``travel_date > collected_date``
   always holds and the tighter form is the correct one. The constraint is
   renamed to say what it now means.

4. ``base_period`` is append-only, like every other pinned definition. Editing
   a base period would silently re-baseline every index value that references
   it.

   **Superseded by revision 0005** (architect ruling, review round 2):
   ``base_period`` is mutable. A base period is a definition, not an
   observation, and Phase 9 may refine it before anything is published.
   Reproducibility is protected instead by ``index_observation`` being
   append-only - the reference a published value recorded can never be
   repointed - and by ``methodology_version``. This paragraph is left in place
   because it is what this revision actually did.

Revision ID: 0004_base_period_identity_key
Revises: 0003_roles_and_privileges
Create Date: 2026-09-07

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from db.settings import DbSettings

revision: str = "0004_base_period_identity_key"
down_revision: str | None = "0003_roles_and_privileges"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _app_role() -> str:
    """Quote the application role name using PostgreSQL's own quoting."""
    settings = DbSettings.from_env()
    return op.get_bind().execute(
        sa.text("SELECT quote_ident(:ident) AS ident"), {"ident": settings.app_user}
    ).scalar_one()


def upgrade() -> None:
    # --- 1. base_period -----------------------------------------------------
    op.create_table(
        "base_period",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("methodology_version_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("end_date > start_date", name=op.f("ck_base_period_dates_ordered")),
        sa.ForeignKeyConstraint(
            ["methodology_version_id"],
            ["methodology_version.id"],
            name=op.f("fk_base_period_methodology_version_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_base_period")),
        sa.UniqueConstraint("code", name=op.f("uq_base_period_code")),
    )

    op.create_foreign_key(
        op.f("fk_index_observation_base_period_id"),
        "index_observation",
        "base_period",
        ["base_period_id"],
        ["id"],
    )

    # --- 2. the identity key must treat NULLs as equal ----------------------
    op.drop_constraint(
        "uq_index_observation_identity", "index_observation", type_="unique"
    )
    op.execute(
        """
        ALTER TABLE index_observation
        ADD CONSTRAINT uq_index_observation_identity
        UNIQUE NULLS NOT DISTINCT (obs_date, level, ref_id, bucket_id, methodology_version_id)
        """
    )

    # --- 3. travel is strictly after collection -----------------------------
    op.drop_constraint(
        "ck_collection_request_travel_not_before_collected",
        "collection_request",
        type_="check",
    )
    op.create_check_constraint(
        "ck_collection_request_travel_after_collected",
        "collection_request",
        "travel_date > collected_date",
    )

    # --- 4. grants for the new table ---------------------------------------
    app = _app_role()
    op.execute(f"GRANT SELECT, INSERT ON TABLE base_period TO {app}")


def downgrade() -> None:
    op.drop_constraint(
        "ck_collection_request_travel_after_collected", "collection_request", type_="check"
    )
    op.create_check_constraint(
        "ck_collection_request_travel_not_before_collected",
        "collection_request",
        "travel_date >= collected_date",
    )

    op.drop_constraint("uq_index_observation_identity", "index_observation", type_="unique")
    op.create_unique_constraint(
        "uq_index_observation_identity",
        "index_observation",
        ["obs_date", "level", "ref_id", "bucket_id", "methodology_version_id"],
    )

    op.drop_constraint(
        op.f("fk_index_observation_base_period_id"), "index_observation", type_="foreignkey"
    )
    op.drop_table("base_period")
