"""0006 - revisions and the publication lifecycle.

Two things an official statistic needs that a prototype does not.

**Revisions.** Until now a published figure could only change by changing the
methodology version, because ``uq_index_observation_identity`` made
(date, level, ref, bucket, methodology) unique. That conflates two different
events:

    a methodology change   - the method changed; recompute forward
    a data correction      - the method is unchanged; a late or corrected
                             observation arrived for a date already published

The second is an ordinary occurrence in price statistics and the schema could
not express it. Adding ``revision`` to the identity lets revision 2 of a date
exist beside revision 1, with both retained. Nothing is edited; nothing is lost.

**Publication state.** A computed figure is not a published one. An official
statistic is released by a named person against a calendar, not by a scheduler
finishing successfully. The ``publication`` table carries that lifecycle:

    PENDING    computed, not visible outside the ministry
    APPROVED   signed off, awaiting its release time
    PUBLISHED  public
    WITHDRAWN  publicly retracted, with a reason, and never deleted

``index_observation`` stays append-only. Publication state changes, so it lives
in its own table where UPDATE is permitted - keeping the computed figure
immutable while its status moves.

Revision ID: 0006_revisions_and_publication
Revises: 0005_base_period_mutable
Create Date: 2026-09-12

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_revisions_and_publication"
down_revision: str | None = "0005_base_period_mutable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- revisions ------------------------------------------------------
    op.add_column(
        "index_observation",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_check_constraint(
        "ck_index_observation_revision_positive", "index_observation", "revision >= 1"
    )
    op.drop_constraint("uq_index_observation_identity", "index_observation", type_="unique")
    op.execute(
        """
        ALTER TABLE index_observation
        ADD CONSTRAINT uq_index_observation_identity
        UNIQUE NULLS NOT DISTINCT
        (obs_date, level, ref_id, bucket_id, methodology_version_id, revision)
        """
    )

    # --- publication lifecycle ------------------------------------------
    op.create_table(
        "publication",
        sa.Column(
            "id", sa.Uuid(), primary_key=True, server_default=sa.text("uuidv7()")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "index_observation_id",
            sa.Uuid(),
            sa.ForeignKey("index_observation.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("state", sa.Text(), nullable=False, server_default="PENDING"),
        # Who approved it, and when. Null until approval: an official statistic
        # is released by a person, and the record of which person is the point.
        sa.Column("approved_by", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_release_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        # Set when this row supersedes an earlier revision. The superseded row
        # is not deleted; a reader can still retrieve what was published before.
        sa.Column(
            "supersedes_id",
            sa.Uuid(),
            sa.ForeignKey("index_observation.id"),
            nullable=True,
        ),
        sa.Column("revision_reason", sa.Text(), nullable=True),
        sa.Column("withdrawn_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "state IN ('PENDING','APPROVED','PUBLISHED','WITHDRAWN')",
            name="ck_publication_state",
        ),
        # Approval requires an approver. A figure released under no one's name
        # is not an approved figure.
        sa.CheckConstraint(
            "state = 'PENDING' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_publication_approval_is_attributed",
        ),
        # A revision must say why. "The number changed" is not a reason a reader
        # can evaluate.
        sa.CheckConstraint(
            "supersedes_id IS NULL OR revision_reason IS NOT NULL",
            name="ck_publication_revision_has_reason",
        ),
        # So must a withdrawal.
        sa.CheckConstraint(
            "state <> 'WITHDRAWN' OR withdrawn_reason IS NOT NULL",
            name="ck_publication_withdrawal_has_reason",
        ),
    )
    op.create_index("ix_publication_state", "publication", ["state"])
    op.create_index("ix_publication_published_at", "publication", ["published_at"])

    # `publication` is mutable: state is what moves. The observation it points
    # at stays append-only, so the figure cannot change while its status does.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE publication TO apix_app")


def downgrade() -> None:
    op.drop_table("publication")
    op.drop_constraint("uq_index_observation_identity", "index_observation", type_="unique")
    op.execute(
        """
        ALTER TABLE index_observation
        ADD CONSTRAINT uq_index_observation_identity
        UNIQUE NULLS NOT DISTINCT
        (obs_date, level, ref_id, bucket_id, methodology_version_id)
        """
    )
    op.drop_constraint(
        "ck_index_observation_revision_positive", "index_observation", type_="check"
    )
    op.drop_column("index_observation", "revision")
