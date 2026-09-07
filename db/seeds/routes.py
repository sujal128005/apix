"""Seed the ten city pairs as twenty directional routes.

Routes are directional (ADR-017): DEL-BOM and BOM-DEL are different routes with
different fares, different demand and different index values. The undirected
read model is the ``route_undirected`` view, not a second set of rows.
"""

from __future__ import annotations

from sqlalchemy import Connection, select
from sqlalchemy.dialects.postgresql import insert

from schemas.models import Airport, Route

# The ten pairs from build brief section 7. Each becomes two rows.
PAIRS: tuple[tuple[str, str], ...] = (
    ("DEL", "BOM"),
    ("DEL", "BLR"),
    ("DEL", "CCU"),
    ("DEL", "MAA"),
    ("DEL", "HYD"),
    ("BOM", "BLR"),
    ("BOM", "MAA"),
    ("BLR", "HYD"),
    ("BOM", "AMD"),
    ("DEL", "GAU"),
)


def directional_codes() -> tuple[str, ...]:
    """Return all twenty route codes, forward then reverse of each pair."""
    codes: list[str] = []
    for origin, destination in PAIRS:
        codes.append(f"{origin}-{destination}")
        codes.append(f"{destination}-{origin}")
    return tuple(codes)


def seed(connection: Connection) -> int:
    """Insert the twenty directional routes. Returns rows inserted."""
    airport_ids = {
        iata: airport_id
        for airport_id, iata in connection.execute(select(Airport.id, Airport.iata)).all()
    }

    missing = {code for pair in PAIRS for code in pair} - set(airport_ids)
    if missing:
        raise RuntimeError(
            f"cannot seed routes: airports not seeded yet: {sorted(missing)}"
        )

    rows = []
    for origin, destination in PAIRS:
        for from_iata, to_iata in ((origin, destination), (destination, origin)):
            rows.append(
                {
                    "code": f"{from_iata}-{to_iata}",
                    "origin_id": airport_ids[from_iata],
                    "destination_id": airport_ids[to_iata],
                    "directional": True,
                    "active": True,
                }
            )

    statement = (
        insert(Route)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["code"])
        .returning(Route.id)
    )
    return len(connection.execute(statement).fetchall())


__all__ = ["PAIRS", "directional_codes", "seed"]
