#!/usr/bin/env python
"""Generate a year of production-scale data and time the real queries.

The demo database holds 15,120 observations over 21 days. The real basket - 78
DGCA-monitored city pairs, both directions, six advance-purchase windows, six
flights, three sources - implies roughly **6.1 million observations a year**, a
factor of 400.

This generates that volume and times the queries the dashboard and API actually
run, so that scaling work is directed by measurement rather than by guessing
which index looks important.

Rows are written with server-side SQL rather than the ORM: the point is to reach
a realistic table size quickly, not to exercise the write path, which the
orchestrator tests already cover.

    .venv/Scripts/python scripts/load_test.py --days 365

Data is written to a **separate database** and dropped afterwards unless
--keep is passed. It must never touch a database carrying real observations.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.settings import DbSettings
from schemas.environment import require_not_production

require_not_production("The load test")

LOAD_DB = "apix_loadtest"


@contextmanager
def timed(label: str) -> Iterator[None]:
    start = time.perf_counter()
    yield
    print(f"  {label:<52} {(time.perf_counter() - start) * 1000:>8.1f} ms")


def create_database(settings: DbSettings) -> None:
    admin = sa.create_engine(settings.maintenance_url(), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(sa.text(f"DROP DATABASE IF EXISTS {LOAD_DB}"))
        connection.execute(sa.text(f"CREATE DATABASE {LOAD_DB}"))
    admin.dispose()


def drop_database(settings: DbSettings) -> None:
    admin = sa.create_engine(settings.maintenance_url(), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(
            sa.text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :db AND pid <> pg_backend_pid()"
            ),
            {"db": LOAD_DB},
        )
        connection.execute(sa.text(f"DROP DATABASE IF EXISTS {LOAD_DB}"))
    admin.dispose()


def build_schema(engine: sa.Engine) -> None:
    """A minimal stand-in for the observation and index tables.

    Deliberately not the full schema: this measures how the *query shapes*
    behave at volume, and carrying every foreign key would slow generation
    without changing what is being measured.
    """
    with engine.begin() as connection:
        connection.execute(sa.text("""
            CREATE TABLE normalised_quote (
                id            bigserial PRIMARY KEY,
                route_code    text        NOT NULL,
                bucket_code   text        NOT NULL,
                carrier       char(2)     NOT NULL,
                collected_date date       NOT NULL,
                total_fare    numeric(12,2) NOT NULL,
                provenance    text        NOT NULL
            )
        """))
        connection.execute(sa.text("""
            CREATE TABLE index_observation (
                id            bigserial PRIMARY KEY,
                obs_date      date        NOT NULL,
                level         text        NOT NULL,
                route_code    text,
                index_value   numeric(12,6) NOT NULL,
                revision      int         NOT NULL DEFAULT 1
            )
        """))


def generate(engine: sa.Engine, days: int) -> None:
    routes = [f"R{i:03d}-R{(i + 1) % 156:03d}" for i in range(156)]
    buckets = ["T1", "T7", "T15", "T21", "T30", "T45"]

    with engine.begin() as connection:
        connection.execute(
            sa.text("""
                INSERT INTO normalised_quote
                    (route_code, bucket_code, carrier, collected_date, total_fare, provenance)
                SELECT
                    r.code,
                    b.code,
                    (ARRAY['6E','AI','SG','QP'])[1 + (g % 4)],
                    CURRENT_DATE - (d || ' days')::interval,
                    3000 + (random() * 12000)::numeric(12,2),
                    'LIVE_COLLECTED'
                FROM generate_series(0, :days - 1) AS d
                CROSS JOIN unnest(CAST(:routes AS text[])) AS r(code)
                CROSS JOIN unnest(CAST(:buckets AS text[])) AS b(code)
                CROSS JOIN generate_series(1, 18) AS g
            """),
            {"days": days, "routes": routes, "buckets": buckets},
        )
        connection.execute(
            sa.text("""
                INSERT INTO index_observation (obs_date, level, route_code, index_value)
                SELECT CURRENT_DATE - (d || ' days')::interval, 'ROUTE', r.code,
                       100 + random() * 30
                FROM generate_series(0, :days - 1) AS d
                CROSS JOIN unnest(CAST(:routes AS text[])) AS r(code)
            """),
            {"days": days, "routes": routes},
        )


def measure(engine: sa.Engine, label: str) -> None:
    print(f"\n{label}")
    with engine.connect() as connection:
        with timed("dashboard: latest route indices"):
            connection.execute(sa.text("""
                SELECT route_code, index_value FROM index_observation
                WHERE level = 'ROUTE'
                  AND obs_date = (SELECT max(obs_date) FROM index_observation)
            """)).all()

        with timed("route explorer: one route's full history"):
            connection.execute(sa.text("""
                SELECT obs_date, index_value FROM index_observation
                WHERE level = 'ROUTE' AND route_code = 'R001-R002'
                ORDER BY obs_date
            """)).all()

        with timed("lead-time profile: mean fare by bucket, latest day"):
            connection.execute(sa.text("""
                SELECT bucket_code, avg(total_fare), count(*)
                FROM normalised_quote
                WHERE collected_date = (SELECT max(collected_date) FROM normalised_quote)
                GROUP BY bucket_code
            """)).all()

        with timed("data quality: provenance counts, whole table"):
            connection.execute(sa.text("""
                SELECT provenance, count(*) FROM normalised_quote GROUP BY provenance
            """)).all()

        with timed("recent observations page"):
            connection.execute(sa.text("""
                SELECT route_code, carrier, total_fare FROM normalised_quote
                ORDER BY collected_date DESC LIMIT 20
            """)).all()

        with timed("bulk export: one year of route indices"):
            connection.execute(sa.text("""
                SELECT obs_date, route_code, index_value FROM index_observation
                WHERE level = 'ROUTE' ORDER BY obs_date DESC LIMIT 50000
            """)).all()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    settings = DbSettings.from_env()
    print(f"Load test - {args.days} days at production basket size\n")

    create_database(settings)
    engine = sa.create_engine(
        settings.url(
            user=settings.superuser, password=settings.superuser_password, database=LOAD_DB
        ),
        future=True,
    )
    try:
        build_schema(engine)
        start = time.perf_counter()
        generate(engine, args.days)
        print(f"generated in {time.perf_counter() - start:.1f}s")

        with engine.connect() as connection:
            quotes = connection.execute(
                sa.text("SELECT count(*) FROM normalised_quote")
            ).scalar_one()
            indices = connection.execute(
                sa.text("SELECT count(*) FROM index_observation")
            ).scalar_one()
            size = connection.execute(
                sa.text(f"SELECT pg_size_pretty(pg_database_size('{LOAD_DB}'))")
            ).scalar_one()
        print(f"observations: {quotes:,}   index rows: {indices:,}   on disk: {size}")

        measure(engine, "BEFORE INDEXES")

        with engine.begin() as connection:
            connection.execute(sa.text(
                "CREATE INDEX ix_quote_date ON normalised_quote (collected_date DESC)"
            ))
            connection.execute(sa.text(
                "CREATE INDEX ix_quote_date_bucket ON normalised_quote "
                "(collected_date, bucket_code)"
            ))
            connection.execute(sa.text(
                "CREATE INDEX ix_obs_level_date ON index_observation "
                "(level, obs_date DESC)"
            ))
            connection.execute(sa.text(
                "CREATE INDEX ix_obs_route ON index_observation (route_code, obs_date)"
            ))
            connection.execute(sa.text("ANALYZE"))

        measure(engine, "AFTER INDEXES")
        print("\nRead the difference, not the absolute numbers: an index that changes")
        print("nothing at this volume is one to leave out until it earns its place.")
    finally:
        engine.dispose()
        if not args.keep:
            drop_database(settings)
            print(f"\ndropped {LOAD_DB}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
