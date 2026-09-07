"""Turn raw quotes into canonical observations, and observations into matched pairs.

Two jobs, deliberately separated.

**Normalisation** maps a source's field names onto the canonical schema and
decomposes fares. It knows about sources. It does not know about the index.

**Pairing** finds the same priced unit in two consecutive periods, which is what
a chained Jevons index consumes. It knows about the index. It does not know
about sources.

The matched-pair identity is ``(carrier, flight_no, fare_brand)``. That choice
is the most consequential thing in this module and it is an assumption, labelled
PA-7 in the methodology. The tempting alternative - "cheapest fare on the route
today versus cheapest yesterday" - is wrong in a way that produces perfectly
plausible numbers: if yesterday's cheapest was a 6E saver and today's is a
SpiceJet promo, the ratio records a product substitution as a price change. A
constant-quality index has to compare like with like, which is the whole reason
CPI uses Structured Product Descriptions.

Quotes that cannot be paired are not errors. A flight that did not operate
yesterday simply has no ratio today; it enters the index when it has a
predecessor.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from index_engine.jevons import MatchedPair
from schemas.enums import Confidence, MissingReason, Provenance, QualityStatus

__all__ = [
    "NormalisationError",
    "NormalisedFields",
    "ObservedQuote",
    "StratumKey",
    "build_matched_pairs",
    "group_by_stratum",
    "normalise_payload",
    "score_quality",
]


class NormalisationError(ValueError):
    """A raw payload cannot become a canonical observation."""


@dataclass(frozen=True, slots=True)
class StratumKey:
    """The elementary aggregate: one route, one lead-time bucket, one day."""

    route_id: UUID
    bucket_id: UUID
    collected_date: date

    def __str__(self) -> str:
        return f"{self.route_id}|{self.bucket_id}|{self.collected_date.isoformat()}"


@dataclass(frozen=True, slots=True)
class NormalisedFields:
    """Canonical fields extracted from one source payload."""

    carrier: str
    flight_no: str | None
    fare_brand: str | None
    total_fare: Decimal
    currency: str
    components: dict[str, Decimal]
    component_confidence: str
    quality_status: str
    missing_reason: str

    @property
    def pair_key(self) -> str:
        """The priced-unit identity. See the module docstring on why this shape."""
        return f"{self.carrier}|{self.flight_no or '?'}|{self.fare_brand or '?'}"


@dataclass(frozen=True, slots=True)
class ObservedQuote:
    """A canonical observation, ready to be paired."""

    stratum: StratumKey
    pair_key: str
    total_fare: Decimal
    provenance: str
    imputed: bool = False


def _to_decimal(value: Any, field: str) -> Decimal:
    """Parse money strictly. Floats are refused rather than silently converted."""
    if isinstance(value, float):
        raise NormalisationError(
            f"{field} arrived as a float ({value!r}). Money must not pass through "
            "binary floating point; sources must supply a string or an integer."
        )
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(",", "").replace("\u20b9", "").strip())
    except (InvalidOperation, AttributeError) as exc:
        raise NormalisationError(f"{field} is not a parseable amount: {value!r}") from exc


def normalise_payload(payload: dict[str, Any]) -> NormalisedFields:
    """Map an adapter's normalised payload onto canonical fields.

    Adapters have already renamed their own fields; this validates and
    decomposes. A missing component breakdown is *not* fatal - the total is the
    index price, and a source that reports a total without a breakdown is giving
    us a usable observation with an unusable decomposition.
    """
    carrier = str(payload.get("carrier", "")).strip().upper()
    if len(carrier) != 2:
        raise NormalisationError(
            f"carrier must be a 2-character IATA code, got {carrier!r}"
        )

    total = _to_decimal(payload.get("total_fare"), "total_fare")
    if total <= 0:
        raise NormalisationError(
            f"total_fare must be positive, got {total}. A zero or negative fare is "
            "a data error, not a free flight."
        )

    currency = str(payload.get("currency", "INR")).strip().upper()
    if currency != "INR":
        raise NormalisationError(
            f"currency {currency!r} is out of scope; APIx collects INR fares only. "
            "Converting would introduce an exchange-rate series into a price index."
        )

    components: dict[str, Decimal] = {}
    for key, field in (("base_fare", "BASE"), ("taxes", "TAX"), ("udf", "UDF"),
                       ("convenience_fee", "CONVENIENCE")):
        if payload.get(key) is not None:
            components[field] = _to_decimal(payload[key], key)

    confidence = Confidence.HIGH
    missing_reason = MissingReason.NONE
    quality = QualityStatus.COMPLETE

    if not components:
        confidence = Confidence.LOW
        missing_reason = MissingReason.PARTIAL_COMPONENTS
        quality = QualityStatus.PARTIAL
    else:
        component_sum = sum(components.values(), Decimal(0))
        if component_sum > total:
            # The total is the price the consumer pays and is still usable; only
            # the breakdown is wrong. Flag it, keep the observation.
            confidence = Confidence.LOW
            missing_reason = MissingReason.PARTIAL_COMPONENTS
            quality = QualityStatus.PARTIAL
        elif component_sum < total:
            confidence = Confidence.MEDIUM

    return NormalisedFields(
        carrier=carrier,
        flight_no=(str(payload["flight_no"]).strip() if payload.get("flight_no") else None),
        fare_brand=(str(payload["fare_brand"]).strip() if payload.get("fare_brand") else None),
        total_fare=total,
        currency=currency,
        components=components,
        component_confidence=confidence,
        quality_status=quality,
        missing_reason=missing_reason,
    )


def score_quality(fields: NormalisedFields, *, provenance: str) -> Decimal:
    """A 0-1 score summarising how much of an observation we actually know.

    Used for reporting and for filtering out unusable records; it does not
    weight an observation inside the index. Weighting by a quality heuristic
    would let an undocumented judgement move a published number.
    """
    score = Decimal("1.000")
    if not fields.flight_no:
        score -= Decimal("0.250")  # cannot be matched across days
    if not fields.fare_brand:
        score -= Decimal("0.150")  # fare-brand drift becomes invisible
    if not fields.components:
        score -= Decimal("0.200")
    elif fields.component_confidence == Confidence.LOW:
        score -= Decimal("0.100")
    if provenance == Provenance.SIMULATED_DEMO:
        score -= Decimal("0.500")
    return max(score, Decimal("0.000"))


def group_by_stratum(quotes: list[ObservedQuote]) -> dict[StratumKey, list[ObservedQuote]]:
    """Bucket observations into elementary aggregates."""
    grouped: dict[StratumKey, list[ObservedQuote]] = defaultdict(list)
    for quote in quotes:
        grouped[quote.stratum].append(quote)
    return dict(grouped)


def build_matched_pairs(
    previous: list[ObservedQuote],
    current: list[ObservedQuote],
) -> tuple[list[MatchedPair], list[str], list[str]]:
    """Pair the same priced unit across two periods.

    Returns ``(pairs, unmatched_current, disappeared)``. The two unmatched lists
    are not failures - a new flight has no predecessor and a withdrawn one has no
    successor - but they are reported, because a stratum where most units churn
    every day is telling us something about the index's stability.

    Duplicate keys within a period are collapsed to their lowest fare, on the
    view that two offers for the same flight and brand are the same product at
    different points in an inventory ladder, and the cheapest is what a consumer
    facing that product would pay.
    """
    def collapse(quotes: list[ObservedQuote]) -> dict[str, ObservedQuote]:
        best: dict[str, ObservedQuote] = {}
        for quote in quotes:
            existing = best.get(quote.pair_key)
            if existing is None or quote.total_fare < existing.total_fare:
                best[quote.pair_key] = quote
        return best

    before = collapse(previous)
    after = collapse(current)

    pairs = [
        MatchedPair(key=key, previous=before[key].total_fare, current=after[key].total_fare)
        for key in sorted(before.keys() & after.keys())
    ]
    unmatched = sorted(after.keys() - before.keys())
    disappeared = sorted(before.keys() - after.keys())
    return pairs, unmatched, disappeared
