"""0007 - indexes and a quality summary, from load-test measurement.

A load test at production basket size - 78 DGCA-monitored city pairs, both
directions, six advance-purchase windows, three sources: **6.1 million
observations a year, 640 MB** - timed the queries the dashboard and API
actually run. Every index below is here because it was measured, not because it
looked sensible:

    recent observations          1040.4 ms  ->    0.6 ms
    lead-time profile             827.6 ms  ->    4.5 ms
    route history                   4.7 ms  ->    0.8 ms
    latest route indices            6.8 ms  ->    4.2 ms

One query did **not** improve:

    data quality, provenance counts   810.4 ms  ->  788.0 ms

Counting every row grouped by provenance reads the whole table by definition,
and no index on that table changes it. Adding one anyway would carry write cost
for no read benefit. The fix is a different shape of answer: a materialised
summary, refreshed after each daily run, which turns a full scan into a lookup
of a few dozen rows.

The summary is refreshed rather than live on purpose. Data-quality figures
describe a completed collection, so being current to the last run is what the
page needs; recomputing on every page load would spend 800 ms answering a
question whose answer changed once that morning.

Revision ID: 0007_scale_indexes
Revises: 0006_revisions_and_publication
Create Date: 2026-09-12

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_scale_indexes"
down_revision: str | None = "0006_revisions_and_publication"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- measured indexes -------------------------------------------------
    op.create_index(
        "ix_normalised_quote_collected_date",
        "normalised_quote",
        ["collected_date"],
        postgresql_using="btree",
    )
    op.create_index(
        "ix_normalised_quote_date_bucket",
        "normalised_quote",
        ["collected_date", "bucket_id"],
    )
    op.create_index(
        "ix_index_observation_level_date",
        "index_observation",
        ["level", "obs_date"],
    )
    op.create_index(
        "ix_index_observation_ref_date",
        "index_observation",
        ["ref_id", "obs_date"],
    )

    # --- quality summary --------------------------------------------------
    # Answers the Data Quality page without reading six million rows. Refreshed
    # by the daily run; the page states the refresh time so a reader knows how
    # current it is rather than assuming.
    op.execute("""
        CREATE MATERIALIZED VIEW quality_summary AS
        SELECT
            collected_date,
            provenance,
            quality_status,
            component_confidence,
            imputation_code,
            count(*)            AS observations,
            min(total_fare)     AS min_fare,
            avg(total_fare)     AS mean_fare,
            max(total_fare)     AS max_fare
        FROM normalised_quote
        GROUP BY collected_date, provenance, quality_status,
                 component_confidence, imputation_code
        WITH NO DATA
    """)
    # Unique index required for REFRESH ... CONCURRENTLY, which is what lets the
    # page keep serving the previous summary while the new one is built rather
    # than blocking on it.
    op.execute("""
        CREATE UNIQUE INDEX ix_quality_summary_identity
        ON quality_summary (collected_date, provenance, quality_status,
                            component_confidence, imputation_code)
    """)
    op.execute("GRANT SELECT ON quality_summary TO apix_app")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS quality_summary")
    op.drop_index("ix_index_observation_ref_date", table_name="index_observation")
    op.drop_index("ix_index_observation_level_date", table_name="index_observation")
    op.drop_index("ix_normalised_quote_date_bucket", table_name="normalised_quote")
    op.drop_index("ix_normalised_quote_collected_date", table_name="normalised_quote")
