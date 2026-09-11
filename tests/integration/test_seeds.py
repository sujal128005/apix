"""What the seeds put in the database, and - just as importantly - what they do not.

Three of these tests assert an absence. ``route_weight`` is empty, no fare
observation ships with the seeds, and no source is enabled. Each of those is a
deliberate state that would look like a bug to someone who had not read the
brief, so each is pinned by a test that says why.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from db.seeds import airports as airport_seed
from db.seeds import lead_time_buckets as bucket_seed
from db.seeds import methodology as methodology_seed
from db.seeds import routes as route_seed
from db.seeds import seed_all
from db.seeds import sources as source_seed
from schemas.enums import SourceTier
from schemas.models import (
    Airport,
    BasePeriod,
    IndexObservation,
    LeadTimeBucket,
    MethodologyVersion,
    NormalisedQuote,
    RawQuote,
    Route,
    RouteWeight,
    Source,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# idempotency
# ---------------------------------------------------------------------------
def test_seeds_are_idempotent(admin_engine: Engine) -> None:
    """A second run inserts nothing. Running the seeds twice is not a mistake."""
    before = {}
    with admin_engine.connect() as connection:
        for model in (Airport, Route, LeadTimeBucket, Source, MethodologyVersion):
            before[model.__tablename__] = connection.execute(
                select(func.count()).select_from(model)
            ).scalar_one()

    with admin_engine.begin() as connection:
        counts = seed_all(connection)

    assert counts.total == 0, f"a repeat seed run inserted rows: {counts!r}"

    with admin_engine.connect() as connection:
        for model in (Airport, Route, LeadTimeBucket, Source, MethodologyVersion):
            after = connection.execute(select(func.count()).select_from(model)).scalar_one()
            assert after == before[model.__tablename__]


# ---------------------------------------------------------------------------
# airports
# ---------------------------------------------------------------------------
def test_ten_airports_are_seeded(app_session: Session) -> None:
    codes = set(app_session.execute(select(Airport.iata)).scalars())
    assert codes == {"DEL", "BOM", "BLR", "MAA", "CCU", "HYD", "AMD", "COK", "PNQ", "GAU"}
    assert len(codes) == 10


def test_airport_icao_is_null_because_the_brief_did_not_supply_it(
    app_session: Session,
) -> None:
    """Anything the brief does not specify stays NULL. NULL beats a plausible guess."""
    icaos = list(app_session.execute(select(Airport.icao)).scalars())
    assert icaos == [None] * 10


def test_every_airport_is_in_india_standard_time(app_session: Session) -> None:
    zones = set(app_session.execute(select(Airport.tz)).scalars())
    assert zones == {"Asia/Kolkata"}


def test_airport_seed_matches_the_module_constant(app_session: Session) -> None:
    seeded = {
        row.iata: (row.name, row.city, row.state)
        for row in app_session.execute(select(Airport)).scalars()
    }
    for entry in airport_seed.AIRPORTS:
        assert seeded[entry.iata] == (entry.name, entry.city, entry.state)


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------
def test_ten_pairs_become_twenty_directional_routes(app_session: Session) -> None:
    codes = set(app_session.execute(select(Route.code)).scalars())
    assert codes == set(route_seed.directional_codes())
    assert len(codes) == 20


def test_every_pair_is_seeded_in_both_directions(app_session: Session) -> None:
    """DEL-BOM and BOM-DEL are different routes with different fares (ADR-017)."""
    codes = set(app_session.execute(select(Route.code)).scalars())
    for origin, destination in route_seed.PAIRS:
        assert f"{origin}-{destination}" in codes
        assert f"{destination}-{origin}" in codes


def test_all_routes_are_flagged_directional(app_session: Session) -> None:
    flags = set(app_session.execute(select(Route.directional)).scalars())
    assert flags == {True}


def test_undirected_view_collapses_them_to_ten_pairs(app_session: Session) -> None:
    rows = app_session.execute(
        text("SELECT pair_code, directional_count FROM route_undirected")
    ).all()
    assert len(rows) == 10
    assert {row.directional_count for row in rows} == {2}


# ---------------------------------------------------------------------------
# lead-time buckets
# ---------------------------------------------------------------------------
def test_six_buckets_with_the_specified_days(app_session: Session) -> None:
    rows = app_session.execute(
        select(LeadTimeBucket.code, LeadTimeBucket.days).order_by(LeadTimeBucket.days)
    ).all()
    assert [(row.code, row.days) for row in rows] == [
        ("T1", 1),
        ("T7", 7),
        ("T15", 15),
        ("T21", 21),
        ("T30", 30),
        ("T45", 45),
    ]


def test_t21_is_the_only_cpi_comparable_bucket(app_session: Session) -> None:
    """MoSPI's CPI 2024 collects domestic airfare at a 21-day advance-purchase window."""
    comparable = list(
        app_session.execute(
            select(LeadTimeBucket.code).where(LeadTimeBucket.cpi_comparable.is_(True))
        ).scalars()
    )
    assert comparable == ["T21"]


def test_lambda_is_uniform_and_stored_as_decimal(app_session: Session) -> None:
    """A labelled prototype assumption: no public Indian lead-time distribution exists."""
    values = list(app_session.execute(select(LeadTimeBucket.lambda_)).scalars())
    assert len(values) == 6
    assert set(values) == {Decimal("0.166667")}
    assert all(isinstance(value, Decimal) for value in values)
    assert Decimal("0.166667") == bucket_seed.UNIFORM_LAMBDA


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------
def test_eighteen_sources_are_registered(app_session: Session) -> None:
    codes = set(app_session.execute(select(Source.code)).scalars())
    assert codes == {entry.code for entry in source_seed.SOURCES}
    assert len(codes) == 18


def test_every_source_is_disabled(app_session: Session) -> None:
    """Sources are opt-in, never opt-out. Zero enabled is the correct state."""
    enabled = list(
        app_session.execute(select(Source.code).where(Source.enabled.is_(True))).scalars()
    )
    assert enabled == []


def test_source_tiers_match_the_brief(app_session: Session) -> None:
    by_tier: dict[int, set[str]] = {}
    for code, tier in app_session.execute(select(Source.code, Source.tier)):
        by_tier.setdefault(tier, set()).add(code)

    assert by_tier[int(SourceTier.LICENSED_API)] == {"amadeus"}
    assert by_tier[int(SourceTier.REGULATORY_DISCLOSURE)] == {
        "indigo_tariff",
        "airindia_tariff",
        "aix_tariff",
        "akasa_tariff",
        "spicejet_tariff",
    }
    assert by_tier[int(SourceTier.PERMITTED_CRAWL)] == {
        "indigo_web",
        "airindia_web",
        "aix_web",
        "akasa_web",
        "spicejet_web",
    }
    assert by_tier[int(SourceTier.RESTRICTED)] == {
        "makemytrip",
        "yatra",
        "easemytrip",
        "cleartrip",
        "ixigo",
        "goibibo",
    }
    assert by_tier[int(SourceTier.OFFICIAL_STATISTICS)] == {"mospi_cpi"}


def test_tier_four_otas_are_present_and_disabled(app_session: Session) -> None:
    """Seeded so they are auditable and can be rendered as blocked. Never enabled.

    Their robots.txt disallows automated flight-search collection. A source that
    is absent from the register cannot be shown as refused; one that is present
    and disabled can be.
    """
    rows = app_session.execute(
        select(Source.code, Source.enabled).where(Source.tier == int(SourceTier.RESTRICTED))
    ).all()
    assert len(rows) == 6
    assert all(row.enabled is False for row in rows)


def test_no_source_carries_an_invented_base_url(app_session: Session) -> None:
    """The brief supplies no URLs, so none are stored."""
    urls = set(app_session.execute(select(Source.base_url)).scalars())
    assert urls == {None}


def test_source_names_and_adapter_keys_match_the_architect_ruling(
    app_session: Session,
) -> None:
    """Supplied verbatim in the Phase 3 review; not derived, not guessed."""
    stored = {
        row.code: (row.name, row.adapter_key)
        for row in app_session.execute(select(Source)).scalars()
    }
    for entry in source_seed.SOURCES:
        assert stored[entry.code] == (entry.name, entry.adapter_key)

    assert stored["mospi_cpi"] == ("MoSPI eSankhyiki CPI API", "mospi_cpi_v1")
    assert stored["amadeus"] == ("Amadeus Self-Service Flight Offers", "amadeus_flight_offers_v2")
    assert stored["indigo_tariff"][0] == "IndiGo — Published Tariff Sheet"


def test_adapter_keys_are_shared_per_source_family(app_session: Session) -> None:
    """One adapter serves a whole family, so adapter_key is not one-to-one with code."""
    by_key: dict[str, set[str]] = {}
    for code, adapter_key in app_session.execute(select(Source.code, Source.adapter_key)):
        by_key.setdefault(adapter_key, set()).add(code)

    assert len(by_key["airline_tariff_doc_v1"]) == 5
    assert len(by_key["airline_web_v1"]) == 5
    assert len(by_key["ota_web_v1"]) == 6
    assert by_key["mospi_cpi_v1"] == {"mospi_cpi"}
    assert by_key["amadeus_flight_offers_v2"] == {"amadeus"}


# ---------------------------------------------------------------------------
# methodology
# ---------------------------------------------------------------------------
def test_one_methodology_version_is_seeded(app_session: Session) -> None:
    versions = list(app_session.execute(select(MethodologyVersion.version)).scalars())
    assert versions == ["1.1.0"], (
        "The seeded methodology version must match db/seeds/methodology.py. "
        "A version bump is a deliberate act - if this fails, confirm the "
        "changelog records why the methodology changed."
    )


def test_methodology_params_are_exactly_the_frozen_set(app_session: Session) -> None:
    row = app_session.execute(select(MethodologyVersion)).scalars().one()
    assert row.params == methodology_seed.PARAMS
    assert row.params["elementary_formula"] == "jevons_short"
    assert row.params["higher_level_formula"] == "young_modified_laspeyres"
    assert row.params["higher_level_aggregation"] == "weighted_arithmetic_mean"
    assert row.params["base_index_value"] == 100
    assert row.changelog == methodology_seed.CHANGELOG


def test_geometric_below_arithmetic_above(app_session: Session) -> None:
    """MoSPI's deliberate structure, recorded in the data rather than assumed in code."""
    params = app_session.execute(select(MethodologyVersion.params)).scalars().one()
    assert "jevons" in params["elementary_formula"]
    assert "arithmetic" in params["higher_level_aggregation"]


# ---------------------------------------------------------------------------
# what the seeds deliberately do not contain
# ---------------------------------------------------------------------------
def test_route_weight_is_empty(app_session: Session) -> None:
    """Weight evidence (open item O-5) is unresolved. Empty is the correct state.

    A placeholder weight would be indistinguishable from a sourced one in every
    chart, API response and export downstream. This is not a missing seed.
    """
    assert app_session.execute(select(func.count()).select_from(RouteWeight)).scalar_one() == 0


def test_seeds_ship_no_fare_observations(app_session: Session) -> None:
    """Reference data only. No quote, raw or normalised, arrives with the seeds."""
    assert app_session.execute(select(func.count()).select_from(RawQuote)).scalar_one() == 0
    assert (
        app_session.execute(select(func.count()).select_from(NormalisedQuote)).scalar_one() == 0
    )


def test_seeds_ship_no_index_values(app_session: Session) -> None:
    assert (
        app_session.execute(select(func.count()).select_from(IndexObservation)).scalar_one() == 0
    )


def test_base_period_is_empty(app_session: Session) -> None:
    """Established in Phase 9 from real collection dates, not invented now.

    A fabricated reference period would sit underneath every index value ever
    published, which is the same failure mode as a placeholder route weight.
    """
    assert app_session.execute(select(func.count()).select_from(BasePeriod)).scalar_one() == 0
