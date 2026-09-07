"""0005 - base_period is a definition, not an observation, so it is mutable.

Architect ruling, Phase 3 review round 2, overruling the append-only grant that
revision 0004 gave this table.

A base period is a *definition*. Phase 9 establishes it from real collection
dates and may need to correct it before anything is published - a date range
that turns out to straddle a collection gap, say. Freezing it would mean
discarding a base period and issuing a new one for what is genuinely an edit to
an unpublished definition.

Reproducibility does not depend on this table being frozen. It depends on the
two things that pin a published value, and both remain append-only:

* ``index_observation`` - the row records which ``base_period_id`` it used, and
  that row can never be updated, so the reference is immutable even when the
  definition behind it is refined.
* ``methodology_version`` - frozen alongside it.

So ``apix_app`` gains UPDATE and DELETE here. The foreign key from
``index_observation`` stays, which is what stops a base period being deleted
while a published value still points at it.

Revision ID: 0005_base_period_mutable
Revises: 0004_base_period_identity_key
Create Date: 2026-09-07

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from db.settings import DbSettings

revision: str = "0005_base_period_mutable"
down_revision: str | None = "0004_base_period_identity_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _app_role() -> str:
    """Quote the application role name using PostgreSQL's own quoting."""
    settings = DbSettings.from_env()
    return op.get_bind().execute(
        sa.text("SELECT quote_ident(:ident) AS ident"), {"ident": settings.app_user}
    ).scalar_one()


def upgrade() -> None:
    op.execute(f"GRANT UPDATE, DELETE ON TABLE base_period TO {_app_role()}")


def downgrade() -> None:
    op.execute(f"REVOKE UPDATE, DELETE ON TABLE base_period FROM {_app_role()}")
