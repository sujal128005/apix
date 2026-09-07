"""Bring an empty PostgreSQL 16 cluster to a fully migrated, seeded APIx database.

    python scripts/init_db.py

Creates the database if it does not exist, runs every migration, loads the
seeds, and prints what is in the database afterwards - including the fact that
``route_weight`` is empty, which is the correct state and not a failure.

Migrations are run as the superuser because revision 0003 creates the two
cluster-global roles. Once those roles exist, later migrations can be run as
``apix_migrator``; the application itself always connects as ``apix_app``.
"""

from __future__ import annotations

import argparse
import sys
import time

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import OperationalError

from db import migrate
from db.seeds import seed_all
from db.settings import DbSettings
from schemas.models import (
    Airport,
    BasePeriod,
    LeadTimeBucket,
    MethodologyVersion,
    Route,
    RouteWeight,
    Source,
)


def wait_for_postgres(settings: DbSettings, timeout_seconds: int = 60) -> None:
    """Block until the cluster accepts connections, or give up with a clear message."""
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        engine = create_engine(settings.maintenance_url(), future=True)
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except OperationalError as exc:
            last_error = exc
            time.sleep(1)
        finally:
            engine.dispose()
    raise SystemExit(
        f"PostgreSQL at {settings.host}:{settings.port} did not accept connections within "
        f"{timeout_seconds}s. Is `docker compose up -d` running?\nLast error: {last_error}"
    )


def ensure_database(settings: DbSettings, database: str) -> bool:
    """Create ``database`` if absent. Returns True if it was created."""
    engine = create_engine(settings.maintenance_url(), future=True, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": database}
            ).first()
            if exists:
                return False
            quoted = connection.execute(
                text("SELECT quote_ident(:name) AS ident"), {"name": database}
            ).scalar_one()
            connection.execute(text(f"CREATE DATABASE {quoted}"))
            return True
    finally:
        engine.dispose()


def report(settings: DbSettings, database: str) -> None:
    """Print what the database now contains."""
    engine = create_engine(settings.superuser_url(database=database), future=True)
    try:
        with engine.connect() as connection:
            counts = {
                "airport": connection.execute(
                    select(func.count()).select_from(Airport)
                ).scalar_one(),
                "route": connection.execute(select(func.count()).select_from(Route)).scalar_one(),
                "lead_time_bucket": connection.execute(
                    select(func.count()).select_from(LeadTimeBucket)
                ).scalar_one(),
                "source": connection.execute(select(func.count()).select_from(Source)).scalar_one(),
                "methodology_version": connection.execute(
                    select(func.count()).select_from(MethodologyVersion)
                ).scalar_one(),
                "route_weight": connection.execute(
                    select(func.count()).select_from(RouteWeight)
                ).scalar_one(),
                "base_period": connection.execute(
                    select(func.count()).select_from(BasePeriod)
                ).scalar_one(),
            }
            enabled_sources = connection.execute(
                select(func.count()).select_from(Source).where(Source.enabled.is_(True))
            ).scalar_one()
            cpi_comparable = connection.execute(
                select(LeadTimeBucket.code).where(LeadTimeBucket.cpi_comparable.is_(True))
            ).scalars().all()
    finally:
        engine.dispose()

    print()
    print(f"  database              {database}")
    print(f"  revision              {migrate.current_revision(settings.superuser_url(database))}")
    for table, count in counts.items():
        print(f"  {table:<21} {count}")
    print()
    print(f"  enabled sources       {enabled_sources}  (sources are opt-in; 0 is correct)")
    print(f"  CPI-comparable bucket {', '.join(cpi_comparable)}  (MoSPI 21-day window)")
    print(
        "  route_weight          empty by design - weight evidence (O-5) is unresolved and\n"
        "                        placeholder weights are exactly what this project must not ship"
    )
    print(
        "  base_period           empty by design - established in Phase 9 from real\n"
        "                        collection dates, never invented up front"
    )
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        default=None,
        help="Database to initialise (default: APIX_DB_NAME, normally 'apix').",
    )
    parser.add_argument(
        "--no-seed", action="store_true", help="Run migrations but do not load seed data."
    )
    args = parser.parse_args(argv)

    settings = DbSettings.from_env()
    database = args.database or settings.database

    print(f"waiting for PostgreSQL at {settings.host}:{settings.port} ...")
    wait_for_postgres(settings)

    created = ensure_database(settings, database)
    print(f"database {database}: {'created' if created else 'already present'}")

    url = settings.superuser_url(database=database)
    print("running migrations ...")
    migrate.upgrade(url)

    if args.no_seed:
        print("skipping seeds (--no-seed)")
    else:
        print("loading seeds ...")
        engine = create_engine(url, future=True)
        try:
            with engine.begin() as connection:
                counts = seed_all(connection)
            print(f"seeds inserted {counts.total} row(s): {counts!r}")
        finally:
            engine.dispose()

    report(settings, database)
    return 0


if __name__ == "__main__":
    sys.exit(main())
