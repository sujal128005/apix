"""Seed the source register. Every source is seeded disabled.

Sources are opt-in, never opt-out, so ``enabled`` is false for all eighteen
rows. Enabling one is a deliberate act recorded in a migration or by an
operator, not a default.

The Tier-4 OTAs are seeded precisely *because* they will never run. Their
robots.txt disallows automated flight-search collection, so the compliance gate
refuses them and the UI shows them as ``BLOCKED_ROBOTS``. A source that is
absent from the register cannot be shown as blocked; one that is present and
disabled can be, and that visible refusal is part of what this system
demonstrates.

Names and adapter keys were supplied by the architect in the Phase 3 review.
Note that ``adapter_key`` is deliberately *not* one-to-one with ``code``: the
five airline tariff sheets share ``airline_tariff_doc_v1``, the five airline
sites share ``airline_web_v1``, and the six OTAs share ``ota_web_v1``, because
one adapter handles the whole family.

``base_url`` stays NULL for every source. The URLs are unverified open items
(O-4), and this project does not guess them.
"""

from __future__ import annotations

from typing import NamedTuple

from sqlalchemy import Connection
from sqlalchemy.dialects.postgresql import insert

from schemas.enums import SourceTier, Transport
from schemas.models import Source


class SourceSeed(NamedTuple):
    """One source, exactly as specified in build brief section 7."""

    code: str
    name: str
    tier: SourceTier
    transport: Transport
    adapter_key: str


SOURCES: tuple[SourceSeed, ...] = (
    # Tier 5 - official statistics
    SourceSeed(
        "mospi_cpi",
        "MoSPI eSankhyiki CPI API",
        SourceTier.OFFICIAL_STATISTICS,
        Transport.API,
        "mospi_cpi_v1",
    ),
    # Tier 1 - licensed API
    SourceSeed(
        "amadeus",
        "Amadeus Self-Service Flight Offers",
        SourceTier.LICENSED_API,
        Transport.API,
        "amadeus_flight_offers_v2",
    ),
    # Tier 2 - regulatory / published tariff disclosures.
    # One adapter reads all five tariff sheets.
    SourceSeed(
        "indigo_tariff",
        "IndiGo — Published Tariff Sheet",
        SourceTier.REGULATORY_DISCLOSURE,
        Transport.DOCUMENT,
        "airline_tariff_doc_v1",
    ),
    SourceSeed(
        "airindia_tariff",
        "Air India — Published Tariff Sheet",
        SourceTier.REGULATORY_DISCLOSURE,
        Transport.DOCUMENT,
        "airline_tariff_doc_v1",
    ),
    SourceSeed(
        "aix_tariff",
        "Air India Express — Published Tariff Sheet",
        SourceTier.REGULATORY_DISCLOSURE,
        Transport.DOCUMENT,
        "airline_tariff_doc_v1",
    ),
    SourceSeed(
        "akasa_tariff",
        "Akasa Air — Published Tariff Sheet",
        SourceTier.REGULATORY_DISCLOSURE,
        Transport.DOCUMENT,
        "airline_tariff_doc_v1",
    ),
    SourceSeed(
        "spicejet_tariff",
        "SpiceJet — Published Tariff Sheet",
        SourceTier.REGULATORY_DISCLOSURE,
        Transport.DOCUMENT,
        "airline_tariff_doc_v1",
    ),
    # Tier 3 - permitted crawl. One adapter reads all five airline sites.
    # Akasa's fares come from its booking engine, on a different host from the
    # marketing site. Registered separately because robots.txt is per-origin:
    # permission established for www.akasaair.com says nothing about the host
    # that actually serves fares. Ships disabled, like every source.
    SourceSeed(
        "akasa_ibe",
        "Akasa Air — Availability API",
        SourceTier.PERMITTED_CRAWL,
        Transport.API,
        "akasa_ibe_v1",
    ),
    SourceSeed(
        "indigo_web",
        "IndiGo — Website",
        SourceTier.PERMITTED_CRAWL,
        Transport.BROWSER,
        "airline_web_v1",
    ),
    SourceSeed(
        "airindia_web",
        "Air India — Website",
        SourceTier.PERMITTED_CRAWL,
        Transport.BROWSER,
        "airline_web_v1",
    ),
    SourceSeed(
        "aix_web",
        "Air India Express — Website",
        SourceTier.PERMITTED_CRAWL,
        Transport.BROWSER,
        "airline_web_v1",
    ),
    SourceSeed(
        "akasa_web",
        "Akasa Air — Website",
        SourceTier.PERMITTED_CRAWL,
        Transport.BROWSER,
        "airline_web_v1",
    ),
    SourceSeed(
        "spicejet_web",
        "SpiceJet — Website",
        SourceTier.PERMITTED_CRAWL,
        Transport.BROWSER,
        "airline_web_v1",
    ),
    # Tier 4 - restricted. Seeded for visibility and audit; permanently disabled.
    SourceSeed("makemytrip", "MakeMyTrip", SourceTier.RESTRICTED, Transport.BROWSER, "ota_web_v1"),
    SourceSeed("yatra", "Yatra", SourceTier.RESTRICTED, Transport.BROWSER, "ota_web_v1"),
    SourceSeed("easemytrip", "EaseMyTrip", SourceTier.RESTRICTED, Transport.BROWSER, "ota_web_v1"),
    SourceSeed("cleartrip", "Cleartrip", SourceTier.RESTRICTED, Transport.BROWSER, "ota_web_v1"),
    SourceSeed("ixigo", "Ixigo", SourceTier.RESTRICTED, Transport.BROWSER, "ota_web_v1"),
    SourceSeed("goibibo", "Goibibo", SourceTier.RESTRICTED, Transport.BROWSER, "ota_web_v1"),
)


def seed(connection: Connection) -> int:
    """Insert the source register, skipping any already present. Returns rows inserted."""
    statement = (
        insert(Source)
        .values(
            [
                {
                    "code": source.code,
                    "name": source.name,
                    "tier": int(source.tier),
                    "transport": source.transport.value,
                    "adapter_key": source.adapter_key,
                    "base_url": None,
                    "enabled": False,
                }
                for source in SOURCES
            ]
        )
        .on_conflict_do_nothing(index_elements=["code"])
        .returning(Source.id)
    )
    return len(connection.execute(statement).fetchall())


__all__ = ["SOURCES", "SourceSeed", "seed"]
