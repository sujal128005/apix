"""Load the golden-day fixture into the database, with its full evidence chain.

Shared by the round-trip test and the lineage traversal test, so both work on
exactly the same rows.

Departure times in the fixture are local Indian clock times. They are converted
to UTC on the way in, because storage is UTC and IST is applied only when
rendering. A fixed +05:30 offset is exact: India observes no daylight saving.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from schemas.enums import Provenance, QualityStatus
from schemas.models import NormalisedQuote
from tests.support.builders import (
    Collection,
    SeedRefs,
    add_cleaning_event,
    add_quote,
    build_collection,
)

IST = timezone(timedelta(hours=5, minutes=30), name="IST")


@dataclass
class LoadedGoldenDay:
    """Everything the fixture produced, addressable by pair letter."""

    route_code: str
    bucket_code: str
    source_code: str
    previous_date: date
    current_date: date
    previous_collection: Collection
    current_collection: Collection
    previous_quotes: dict[str, NormalisedQuote] = field(default_factory=dict)
    current_quotes: dict[str, NormalisedQuote] = field(default_factory=dict)

    @property
    def all_quotes(self) -> list[NormalisedQuote]:
        return [*self.previous_quotes.values(), *self.current_quotes.values()]


def _departure(day: date, clock: str) -> datetime:
    """Local Indian departure time, stored as UTC."""
    hour, minute, second = (int(part) for part in clock.split(":"))
    return datetime.combine(day, time(hour, minute, second), tzinfo=IST).astimezone(UTC)


def load_golden_day(
    session: Session, refs: SeedRefs, fixture: dict[str, Any]
) -> LoadedGoldenDay:
    """Persist both collection days of the fixture with lineage intact."""
    route_code = fixture["route"]
    bucket_code = fixture["bucket"]
    source_code = fixture["source"]
    carrier = fixture["carrier"]
    provenance = Provenance(fixture["provenance"])
    quality_status = QualityStatus(fixture["quality_status"])

    previous = fixture["previous"]
    current = fixture["current"]
    previous_date = date.fromisoformat(previous["collected_date"])
    current_date = date.fromisoformat(current["collected_date"])
    previous_travel = date.fromisoformat(previous["travel_date"])
    current_travel = date.fromisoformat(current["travel_date"])
    previous_collected_at = datetime.fromisoformat(previous["collected_at"])
    current_collected_at = datetime.fromisoformat(current["collected_at"])

    previous_collection = build_collection(
        session,
        refs,
        source_code=source_code,
        route_code=route_code,
        bucket_code=bucket_code,
        travel_date=previous_travel,
        collected_date=previous_date,
        fetched_at=previous_collected_at,
    )
    current_collection = build_collection(
        session,
        refs,
        source_code=source_code,
        route_code=route_code,
        bucket_code=bucket_code,
        travel_date=current_travel,
        collected_date=current_date,
        fetched_at=current_collected_at,
        job=previous_collection.job,
    )

    loaded = LoadedGoldenDay(
        route_code=route_code,
        bucket_code=bucket_code,
        source_code=source_code,
        previous_date=previous_date,
        current_date=current_date,
        previous_collection=previous_collection,
        current_collection=current_collection,
    )

    base_events = fixture["cleaning_events"]["all_quotes"]
    outlier_events = fixture["cleaning_events"]["outlier_only"]

    for entry in fixture["pairs"]:
        for (
            collection,
            collected_date,
            collected_at,
            travel_date,
            fare_key,
            target,
        ) in (
            (
                previous_collection,
                previous_date,
                previous_collected_at,
                previous_travel,
                "previous_fare",
                loaded.previous_quotes,
            ),
            (
                current_collection,
                current_date,
                current_collected_at,
                current_travel,
                "current_fare",
                loaded.current_quotes,
            ),
        ):
            quote = add_quote(
                session,
                refs,
                collection,
                route_code=route_code,
                bucket_code=bucket_code,
                source_code=source_code,
                carrier=carrier,
                flight_no=entry["flight_no"],
                fare_brand=entry["fare_brand"],
                total_fare=Decimal(entry[fare_key]),
                departure_ts=_departure(travel_date, entry["departure_time"]),
                collected_at=collected_at,
                collected_date=collected_date,
                provenance=provenance,
                quality_status=quality_status,
            )
            target[entry["pair"]] = quote

            for event in base_events:
                add_cleaning_event(
                    session,
                    quote,
                    rule_id=event["rule_id"],
                    action=event["action"],
                    reason=event["reason"],
                )

        if entry.get("outlier"):
            for event in outlier_events:
                add_cleaning_event(
                    session,
                    loaded.current_quotes[entry["pair"]],
                    rule_id=event["rule_id"],
                    action=event["action"],
                    reason=event["reason"],
                    threshold=Decimal(event["threshold"]) if event.get("threshold") else None,
                    observed=Decimal(event["observed"]) if event.get("observed") else None,
                )

    session.flush()
    return loaded


__all__ = ["IST", "LoadedGoldenDay", "load_golden_day"]
