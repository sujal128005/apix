"""Reference and versioning seeds.

Every loader is idempotent: it inserts with ``ON CONFLICT DO NOTHING`` on the
table's natural key, so running the seeds twice leaves the database in exactly
the state one run produced.

``route_weight`` is deliberately **not** seeded. Weight evidence is open item
O-5 and is unresolved. Seeding placeholder weights is exactly the failure mode
this project exists to avoid: once a made-up number is in the table it is
indistinguishable from a sourced one in every chart, API response and export
downstream. The table, its constraints and its tests exist; its rows do not.
Tests that need weights build their own, named ``test_weight_set_*``.
"""

from __future__ import annotations

from typing import NamedTuple

from sqlalchemy import Connection

from db.seeds import airports, lead_time_buckets, methodology, routes, sources


class SeedCounts(NamedTuple):
    """Rows actually inserted by one seed run. All zeroes on a second run."""

    airports: int
    routes: int
    lead_time_buckets: int
    sources: int
    methodology_versions: int

    @property
    def total(self) -> int:
        return (
            self.airports
            + self.routes
            + self.lead_time_buckets
            + self.sources
            + self.methodology_versions
        )


def seed_all(connection: Connection) -> SeedCounts:
    """Load every seed, in dependency order. Safe to run repeatedly."""
    airport_rows = airports.seed(connection)
    route_rows = routes.seed(connection)
    bucket_rows = lead_time_buckets.seed(connection)
    source_rows = sources.seed(connection)
    methodology_rows = methodology.seed(connection)
    return SeedCounts(
        airports=airport_rows,
        routes=route_rows,
        lead_time_buckets=bucket_rows,
        sources=source_rows,
        methodology_versions=methodology_rows,
    )


__all__ = [
    "SeedCounts",
    "airports",
    "lead_time_buckets",
    "methodology",
    "routes",
    "seed_all",
    "sources",
]
