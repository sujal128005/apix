"""Seed the ten airports named in the build brief.

The brief specifies IATA code, name, city, state and time zone. It does not
specify ICAO codes, so ``icao`` is left NULL. Filling it in would be inventing
data the brief did not supply, and a NULL is always better than a plausible
guess.
"""

from __future__ import annotations

from typing import NamedTuple

from sqlalchemy import Connection
from sqlalchemy.dialects.postgresql import insert

from schemas.models import Airport


class AirportSeed(NamedTuple):
    """One airport, exactly as specified in build brief section 7."""

    iata: str
    name: str
    city: str
    state: str


AIRPORTS: tuple[AirportSeed, ...] = (
    AirportSeed("DEL", "Indira Gandhi International Airport", "Delhi", "Delhi"),
    AirportSeed(
        "BOM",
        "Chhatrapati Shivaji Maharaj International Airport",
        "Mumbai",
        "Maharashtra",
    ),
    AirportSeed("BLR", "Kempegowda International Airport", "Bengaluru", "Karnataka"),
    AirportSeed("MAA", "Chennai International Airport", "Chennai", "Tamil Nadu"),
    AirportSeed(
        "CCU",
        "Netaji Subhas Chandra Bose International Airport",
        "Kolkata",
        "West Bengal",
    ),
    AirportSeed("HYD", "Rajiv Gandhi International Airport", "Hyderabad", "Telangana"),
    AirportSeed(
        "AMD",
        "Sardar Vallabhbhai Patel International Airport",
        "Ahmedabad",
        "Gujarat",
    ),
    AirportSeed("COK", "Cochin International Airport", "Kochi", "Kerala"),
    AirportSeed("PNQ", "Pune Airport", "Pune", "Maharashtra"),
    AirportSeed(
        "GAU",
        "Lokpriya Gopinath Bordoloi International Airport",
        "Guwahati",
        "Assam",
    ),
)

# Every Indian airport in this basket is in a single time zone.
TIMEZONE = "Asia/Kolkata"


def seed(connection: Connection) -> int:
    """Insert the airports, skipping any already present. Returns rows inserted."""
    statement = (
        insert(Airport)
        .values(
            [
                {
                    "iata": airport.iata,
                    "icao": None,
                    "name": airport.name,
                    "city": airport.city,
                    "state": airport.state,
                    "tz": TIMEZONE,
                    "active": True,
                }
                for airport in AIRPORTS
            ]
        )
        .on_conflict_do_nothing(index_elements=["iata"])
        .returning(Airport.id)
    )
    return len(connection.execute(statement).fetchall())


__all__ = ["AIRPORTS", "TIMEZONE", "AirportSeed", "seed"]
