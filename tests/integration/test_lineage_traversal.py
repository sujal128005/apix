"""One query walks a published headline all the way down to a single fare.

    index_observation (HEADLINE)
      -> index_contribution -> route
      -> normalised_quote (route, bucket, collected_date)
      -> raw_quote -> raw_response -> collection_request -> compliance_decision -> source
      -> cleaning_event (every rule that touched the quote)

This is the traversal the whole traceability story rests on. If a judge asks
"where did this number come from", the answer has to be one query away, and it
has to end at a fare with its value, its source, when it was collected, what
provenance it carries and every cleaning rule that saw it.

The query lives here rather than in the package because Phase 3 ships no API and
no read layer; building one would be building ahead. What Phase 3 owes is proof
that the schema supports the traversal, which is what this asserts.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from schemas.enums import IndexLevel, Provenance
from tests.support.builders import (
    SeedRefs,
    add_contribution,
    make_index_observation,
    make_weight_set,
)
from tests.support.golden import load_golden_day

pytestmark = pytest.mark.integration

# A single statement. Every join in the chain, and the cleaning rules aggregated
# per quote so one row is one fare with its complete history.
LINEAGE_QUERY = """
SELECT
    observation.obs_date,
    observation.level,
    observation.index_value,
    observation.prev_index_value,
    observation.input_hash,
    contribution.contribution,
    route.code                          AS route_code,
    bucket.code                         AS bucket_code,
    quote.id                            AS quote_id,
    quote.flight_no,
    quote.total_fare,
    quote.currency,
    quote.collected_at,
    quote.provenance,
    quote.quality_status,
    source.code                         AS source_code,
    source.tier                         AS source_tier,
    compliance.decision                 AS compliance_decision,
    compliance.decided_at               AS compliance_decided_at,
    compliance.robots_sha256,
    request.query_hash,
    response.payload_ref,
    response.sha256                     AS payload_sha256,
    response.fetched_at,
    raw.ordinal                         AS raw_ordinal,
    array_remove(array_agg(DISTINCT cleaning.rule_id), NULL) AS cleaning_rules
FROM index_observation  AS observation
JOIN index_contribution AS contribution
     ON contribution.index_observation_id = observation.id
JOIN route
     ON route.id = contribution.route_id
JOIN normalised_quote   AS quote
     ON quote.route_id = route.id
    AND quote.collected_date = observation.obs_date
    AND (observation.bucket_id IS NULL OR quote.bucket_id = observation.bucket_id)
JOIN lead_time_bucket   AS bucket
     ON bucket.id = quote.bucket_id
JOIN raw_quote          AS raw
     ON raw.id = quote.raw_quote_id
JOIN raw_response       AS response
     ON response.id = raw.raw_response_id
JOIN collection_request AS request
     ON request.id = response.request_id
JOIN compliance_decision AS compliance
     ON compliance.request_id = request.id
JOIN source
     ON source.id = request.source_id
LEFT JOIN cleaning_event AS cleaning
     ON cleaning.quote_id = quote.id
WHERE observation.id = :observation_id
  AND observation.level = 'HEADLINE'
GROUP BY
    observation.obs_date, observation.level, observation.index_value,
    observation.prev_index_value, observation.input_hash, contribution.contribution,
    route.code, bucket.code, quote.id, quote.flight_no, quote.total_fare,
    quote.currency, quote.collected_at, quote.provenance, quote.quality_status,
    source.code, source.tier, compliance.decision, compliance.decided_at,
    compliance.robots_sha256, request.query_hash, response.payload_ref,
    response.sha256, response.fetched_at, raw.ordinal
ORDER BY quote.total_fare
"""


@pytest.fixture
def headline_scenario(app_session: Session, refs: SeedRefs, golden_day: dict[str, Any]):
    """The golden day, published as a headline index value with one contributing route."""
    loaded = load_golden_day(app_session, refs, golden_day)

    weight_set = make_weight_set(
        app_session,
        version="test_weight_set_lineage",
        effective_from=date(2026, 1, 1),
        source_note="synthetic weight set built inside a test; never sourced evidence",
    )
    observation = make_index_observation(
        app_session,
        refs,
        obs_date=loaded.current_date,
        level=IndexLevel.HEADLINE.value,
        weight_set=weight_set,
        index_value=Decimal(golden_day["expected_stratum_index"]),
        prev_index_value=Decimal(golden_day["prior_stratum_index"]),
        input_quote_count=4,
        routes_in_basket=1,
        input_hash="e" * 64,
    )
    add_contribution(
        app_session,
        refs,
        observation,
        route_code=loaded.route_code,
        contribution=Decimal("102.313000"),
    )
    app_session.flush()
    return loaded, observation


def run_lineage(session: Session, observation_id: object) -> list[Any]:
    return session.execute(text(LINEAGE_QUERY), {"observation_id": observation_id}).all()


# ---------------------------------------------------------------------------
def test_lineage_traversal(app_session: Session, headline_scenario) -> None:
    """The whole chain, in one query, ending at individual fares."""
    loaded, observation = headline_scenario
    rows = run_lineage(app_session, observation.id)

    assert len(rows) == 4, "one row per contributing fare on the observation date"

    for row in rows:
        # the published value
        assert row.level == "HEADLINE"
        assert row.obs_date == loaded.current_date
        assert row.index_value == Decimal("102.313000")
        assert row.prev_index_value == Decimal("100.000000")
        assert row.input_hash == "e" * 64

        # the fare it rests on
        assert row.route_code == "DEL-BOM"
        assert row.bucket_code == "T7"
        assert isinstance(row.total_fare, Decimal)
        assert row.total_fare > 0
        assert row.currency == "INR"

        # where it came from
        assert row.source_code == "indigo_web"
        assert row.source_tier == 3
        assert row.collected_at is not None
        assert row.collected_at.utcoffset().total_seconds() == 0
        assert row.provenance == Provenance.LIVE_COLLECTED

        # that we were allowed to fetch it
        assert row.compliance_decision == "ALLOWED"
        assert row.compliance_decided_at is not None
        assert row.robots_sha256 is not None

        # the bytes behind it
        assert len(row.payload_sha256) == 64
        assert row.payload_ref.startswith("s3://apix-raw/")
        assert len(row.query_hash) == 64

        # and every rule that touched it
        assert "R-NORMALISE-CURRENCY" in row.cleaning_rules


def test_one_fare_answers_the_five_questions(app_session: Session, headline_scenario) -> None:
    """Value, source, collected_at, provenance, cleaning rules - for a single fare."""
    _loaded, observation = headline_scenario
    rows = run_lineage(app_session, observation.id)

    fare = next(row for row in rows if row.flight_no == "6E2117")

    assert fare.total_fare == Decimal("5610.00")
    assert fare.source_code == "indigo_web"
    assert fare.collected_at.isoformat() == "2026-03-03T06:30:00+00:00"
    assert fare.provenance == "LIVE_COLLECTED"
    assert sorted(fare.cleaning_rules) == ["R-NORMALISE-CURRENCY"]


def test_the_outlier_carries_both_rules_that_touched_it(
    app_session: Session, headline_scenario
) -> None:
    _loaded, observation = headline_scenario
    rows = run_lineage(app_session, observation.id)

    outlier = next(row for row in rows if row.total_fare == Decimal("20000.00"))
    assert sorted(outlier.cleaning_rules) == [
        "R-NORMALISE-CURRENCY",
        "R-OUTLIER-MAD-LOG-RELATIVES",
    ]


def test_the_traversal_reaches_every_contributing_fare(
    app_session: Session, headline_scenario
) -> None:
    _loaded, observation = headline_scenario
    rows = run_lineage(app_session, observation.id)

    fares = sorted(row.total_fare for row in rows)
    assert fares == [
        Decimal("5000.00"),
        Decimal("5610.00"),
        Decimal("6300.00"),
        Decimal("20000.00"),
    ]
    assert len({row.quote_id for row in rows}) == 4


def test_it_really_is_one_query(app_session: Session, headline_scenario) -> None:
    """No temporary tables, no application-side stitching, no second round trip."""
    assert LINEAGE_QUERY.strip().rstrip(";").count(";") == 0
    assert LINEAGE_QUERY.strip().upper().startswith("SELECT")

    _loaded, observation = headline_scenario
    plan = app_session.execute(
        text("EXPLAIN " + LINEAGE_QUERY), {"observation_id": observation.id}
    ).scalars().all()
    assert plan, "the planner produced no plan, so this is not a single executable query"


def test_the_prior_day_is_not_pulled_in(app_session: Session, headline_scenario) -> None:
    """The observation date pins the traversal; t-1 fares belong to the previous value."""
    loaded, observation = headline_scenario
    rows = run_lineage(app_session, observation.id)

    collected_dates = {row.collected_at.date() for row in rows}
    assert collected_dates == {loaded.current_date}
    assert loaded.previous_date not in collected_dates


def test_a_headline_with_no_contribution_returns_nothing(
    app_session: Session, refs: SeedRefs, golden_day: dict[str, Any]
) -> None:
    """An index value with no recorded contribution is untraceable, and reads as such."""
    load_golden_day(app_session, refs, golden_day)
    weight_set = make_weight_set(
        app_session,
        version="test_weight_set_lineage_empty",
        effective_from=date(2026, 1, 1),
        source_note="synthetic weight set built inside a test; never sourced evidence",
    )
    observation = make_index_observation(
        app_session,
        refs,
        obs_date=date(2026, 3, 3),
        level=IndexLevel.HEADLINE.value,
        weight_set=weight_set,
        index_value=Decimal("102.313000"),
    )
    app_session.flush()

    assert run_lineage(app_session, observation.id) == []
