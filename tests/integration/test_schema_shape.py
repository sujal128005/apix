"""The live schema is the one the brief specifies - tables, types, keys, indexes.

Two complementary checks run here. The generic ones compare the live database
against ``Base.metadata`` so nothing can drift. The specific ones name the
constraints and precisions the build brief calls out, so those cannot be
silently dropped even if the models and the migration agree with each other.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, inspect, text

from schemas.models import ALL_TABLES, IMMUTABLE_TABLES, MUTABLE_TABLES, Base

pytestmark = pytest.mark.integration

# Alembic's own bookkeeping table is not part of the data layer.
BOOKKEEPING = {"alembic_version"}

# Constraints the brief names explicitly. Losing any of these changes what the
# database will accept, so they are pinned by name rather than by inference.
REQUIRED_CHECKS = {
    "ck_airport_iata_format",
    "ck_route_code_format",
    "ck_route_origin_ne_destination",
    "ck_lead_time_bucket_days_positive",
    "ck_source_tier_range",
    "ck_route_weight_weight_range",
    "ck_route_weight_evidence_rung_range",
    "ck_normalised_quote_total_fare_positive",
    "ck_normalised_quote_currency_inr",
    "ck_normalised_quote_imputed_or_sourced",
    "ck_index_observation_index_value_positive",
    "ck_benchmark_observation_citation_present",
    "ck_backtest_run_tier_range",
    "ck_backtest_run_limitations_present",
    "ck_collection_request_travel_after_collected",
    "ck_base_period_dates_ordered",
}

REQUIRED_UNIQUE = {
    "uq_airport_iata",
    "uq_route_code",
    "uq_lead_time_bucket_code",
    "uq_lead_time_bucket_days",
    "uq_source_code",
    "uq_methodology_version_version",
    "uq_weight_set_version_version",
    "uq_route_weight_route_set",
    "uq_collection_request_query_hash",
    "uq_raw_response_request_sha256",
    "uq_raw_quote_response_ordinal",
    "uq_normalised_quote_dedup",
    "uq_fare_component_quote_kind",
    "uq_index_observation_identity",
    "uq_index_contribution_obs_route",
    "uq_base_period_code",
}

REQUIRED_INDEXES = {
    "ix_collection_job_started_at",
    "ix_compliance_decision_source_decided",
    "ix_normalised_quote_route_bucket_date",
    "ix_cleaning_event_quote_id",
    "ix_system_event_created_at",
}


def live_table_names(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names()) - BOOKKEEPING


# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------
def test_all_tables_exist(admin_engine: Engine) -> None:
    """21 from the build brief, plus base_period added in the Phase 3 review."""
    assert live_table_names(admin_engine) == set(ALL_TABLES)
    assert len(ALL_TABLES) == 23


def test_immutable_and_mutable_lists_partition_the_schema() -> None:
    assert set(IMMUTABLE_TABLES) & set(MUTABLE_TABLES) == set()
    assert set(IMMUTABLE_TABLES) | set(MUTABLE_TABLES) == set(ALL_TABLES)
    assert len(IMMUTABLE_TABLES) == 13
    assert len(MUTABLE_TABLES) == 10


@pytest.mark.parametrize("table_name", sorted(ALL_TABLES))
def test_columns_match_the_models(admin_engine: Engine, table_name: str) -> None:
    """Name, nullability and NUMERIC precision, column for column."""
    inspector = inspect(admin_engine)
    live = {column["name"]: column for column in inspector.get_columns(table_name)}
    expected = Base.metadata.tables[table_name]

    assert set(live) == {column.name for column in expected.columns}

    for column in expected.columns:
        observed = live[column.name]
        assert observed["nullable"] == column.nullable, (
            f"{table_name}.{column.name}: database nullable={observed['nullable']}, "
            f"model nullable={column.nullable}"
        )
        # Compile both sides against the PostgreSQL dialect: `sa.Uuid()` is
        # dialect-agnostic and stringifies as CHAR(32) without one.
        dialect = admin_engine.dialect
        live_type = observed["type"].compile(dialect=dialect).upper().replace(" ", "")
        model_type = column.type.compile(dialect=dialect).upper().replace(" ", "")
        assert live_type == model_type, (
            f"{table_name}.{column.name}: database type {live_type}, model type {model_type}"
        )


def test_every_table_has_a_uuid_primary_key_and_created_at(admin_engine: Engine) -> None:
    inspector = inspect(admin_engine)
    for table_name in ALL_TABLES:
        primary_key = inspector.get_pk_constraint(table_name)
        assert primary_key["constrained_columns"] == ["id"], table_name
        columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        assert str(columns["id"]["type"]).upper() == "UUID", table_name
        assert "TIMESTAMP" in str(columns["created_at"]["type"]).upper(), table_name
        assert columns["created_at"]["nullable"] is False, table_name


def test_every_timestamp_column_carries_a_time_zone(admin_engine: Engine) -> None:
    """TIMESTAMPTZ everywhere. A bare TIMESTAMP would lose the offset silently."""
    with admin_engine.connect() as connection:
        naive = connection.execute(
            text(
                """
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND data_type = 'timestamp without time zone'
                """
            )
        ).all()
    assert naive == [], f"naive timestamp columns found: {naive}"


# ---------------------------------------------------------------------------
# constraints and indexes
# ---------------------------------------------------------------------------
def test_named_check_constraints_exist(admin_engine: Engine) -> None:
    with admin_engine.connect() as connection:
        live = {
            row.conname
            for row in connection.execute(
                text(
                    """
                    SELECT conname FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    JOIN pg_namespace n ON n.oid = t.relnamespace
                    WHERE c.contype = 'c' AND n.nspname = 'public'
                    """
                )
            )
        }
    missing = REQUIRED_CHECKS - live
    assert not missing, f"CHECK constraints missing: {sorted(missing)}"


def test_named_unique_constraints_exist(admin_engine: Engine) -> None:
    with admin_engine.connect() as connection:
        live = {
            row.conname
            for row in connection.execute(
                text(
                    """
                    SELECT conname FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    JOIN pg_namespace n ON n.oid = t.relnamespace
                    WHERE c.contype = 'u' AND n.nspname = 'public'
                    """
                )
            )
        }
    missing = REQUIRED_UNIQUE - live
    assert not missing, f"UNIQUE constraints missing: {sorted(missing)}"


def test_named_indexes_exist(admin_engine: Engine) -> None:
    with admin_engine.connect() as connection:
        live = {
            row.indexname
            for row in connection.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
            )
        }
    missing = REQUIRED_INDEXES - live
    assert not missing, f"indexes missing: {sorted(missing)}"


def test_dedup_key_covers_the_specified_columns(admin_engine: Engine) -> None:
    with admin_engine.connect() as connection:
        columns = connection.execute(
            text(
                """
                SELECT a.attname
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON true
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
                WHERE c.conname = 'uq_normalised_quote_dedup'
                ORDER BY k.ord
                """
            )
        ).scalars().all()
    assert columns == [
        "source_id",
        "carrier",
        "flight_no",
        "departure_ts",
        "fare_brand",
        "collected_date",
    ]


def test_index_observation_identity_key_treats_nulls_as_equal(
    admin_engine: Engine,
) -> None:
    """UNIQUE NULLS NOT DISTINCT: a HEADLINE row has NULL ref_id and bucket_id.

    Under PostgreSQL's default those NULLs are distinct, so two headline values
    could exist for one date and methodology version. That duplicate would break
    reproducibility, so the key is declared NULLS NOT DISTINCT (revision 0004).
    """
    with admin_engine.connect() as connection:
        nulls_not_distinct = connection.execute(
            text(
                """
                SELECT i.indnullsnotdistinct
                FROM pg_constraint c
                JOIN pg_index i ON i.indexrelid = c.conindid
                WHERE c.conname = 'uq_index_observation_identity'
                """
            )
        ).scalar_one()
    assert nulls_not_distinct is True


def test_normalised_quote_dedup_key_keeps_nulls_distinct(admin_engine: Engine) -> None:
    """Deliberately the opposite: imputed rows have a NULL flight_no and coexist.

    Near-duplicate detection for those belongs in the Phase 7 cleaning layer -
    see docs/deferred.md D-1 - not in a unique key.
    """
    with admin_engine.connect() as connection:
        nulls_not_distinct = connection.execute(
            text(
                """
                SELECT i.indnullsnotdistinct
                FROM pg_constraint c
                JOIN pg_index i ON i.indexrelid = c.conindid
                WHERE c.conname = 'uq_normalised_quote_dedup'
                """
            )
        ).scalar_one()
    assert nulls_not_distinct is False


def test_index_observation_identity_key_covers_the_specified_columns(
    admin_engine: Engine,
) -> None:
    with admin_engine.connect() as connection:
        columns = connection.execute(
            text(
                """
                SELECT a.attname
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON true
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
                WHERE c.conname = 'uq_index_observation_identity'
                ORDER BY k.ord
                """
            )
        ).scalars().all()
    assert columns == [
        "obs_date",
        "level",
        "ref_id",
        "bucket_id",
        "methodology_version_id",
        # Phase 21. Without revision in the identity, a correction to an
        # already-published date could only be expressed by inventing a new
        # methodology version - conflating "the method changed" with "a late
        # observation arrived", which are different events a reader must be
        # able to tell apart.
        "revision",
    ]


# ---------------------------------------------------------------------------
# functions, triggers, view
# ---------------------------------------------------------------------------
def test_base_period_is_linked_to_index_observation(admin_engine: Engine) -> None:
    """base_period_id is a real foreign key, not a loose UUID (revision 0004)."""
    inspector = inspect(admin_engine)
    foreign_keys = {
        tuple(fk["constrained_columns"]): fk["referred_table"]
        for fk in inspector.get_foreign_keys("index_observation")
    }
    assert foreign_keys[("base_period_id",)] == "base_period"


def test_uuidv7_function_generates_version_seven_identifiers(admin_engine: Engine) -> None:
    """The server-side generator must agree with schemas/uuid7.py on layout."""
    with admin_engine.connect() as connection:
        generated = connection.execute(
            text("SELECT uuidv7() FROM generate_series(1, 200)")
        ).scalars().all()

    assert len({str(value) for value in generated}) == 200
    for value in generated:
        assert value.version == 7
        assert (value.bytes[8] & 0xC0) == 0x80


def test_uuidv7_timestamp_is_current(admin_engine: Engine) -> None:
    with admin_engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    ('x' || substring(replace(uuidv7()::text, '-', '') from 1 for 12))::bit(48)::bigint
                        AS embedded_ms,
                    (extract(epoch from clock_timestamp()) * 1000)::bigint AS now_ms
                """
            )
        ).one()
    assert abs(row.embedded_ms - row.now_ms) < 5_000


def test_required_triggers_exist(admin_engine: Engine) -> None:
    with admin_engine.connect() as connection:
        triggers = {
            (row.tgname, row.relname)
            for row in connection.execute(
                text(
                    """
                    SELECT t.tgname, c.relname
                    FROM pg_trigger t
                    JOIN pg_class c ON c.oid = t.tgrelid
                    WHERE NOT t.tgisinternal
                    """
                )
            )
        }
    assert ("trg_route_weight_sums_to_one", "route_weight") in triggers
    assert ("trg_index_observation_no_simulated", "index_observation") in triggers
    assert ("trg_index_contribution_no_simulated", "index_contribution") in triggers


def test_weight_sum_trigger_is_deferrable_and_deferred(admin_engine: Engine) -> None:
    """It has to fire at COMMIT, or a weight set could never be inserted row by row."""
    with admin_engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT tgdeferrable, tginitdeferred
                FROM pg_trigger
                WHERE tgname = 'trg_route_weight_sums_to_one'
                """
            )
        ).one()
    assert row.tgdeferrable is True
    assert row.tginitdeferred is True


def test_route_undirected_view_pairs_the_directional_routes(admin_engine: Engine) -> None:
    with admin_engine.connect() as connection:
        rows = connection.execute(
            text("SELECT pair_code, directional_count FROM route_undirected ORDER BY pair_code")
        ).all()

    assert len(rows) == 10, "ten city pairs, twenty directional routes"
    assert all(row.directional_count == 2 for row in rows)
    assert [row.pair_code for row in rows] == sorted(row.pair_code for row in rows)
    # least(origin, destination) first, so BOM-DEL is the pair key for both directions.
    assert "BOM-DEL" in {row.pair_code for row in rows}


def test_database_is_pinned_to_utc(admin_engine: Engine) -> None:
    """Storage is UTC; IST is applied when rendering, never in the database."""
    with admin_engine.connect() as connection:
        timezone = connection.execute(text("SHOW timezone")).scalar_one()
    assert timezone.upper() == "UTC"
