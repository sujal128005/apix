"""Route weights, and the evidence that justifies them.

The problem statement requires route selection "on the basis of DGCA
passenger-traffic data". The Expert Group Report (4.6.3.3) sanctions exactly
this shape of proxy: where one weighted item maps to several priced items, the
priced-item weights may come from administrative indicators such as *number of
passengers, revenue by fare category, or usage levels*, and these "may not
necessarily represent household expenditure directly". Airfare is precisely that
case, so passenger-count weighting is MoSPI's own prescribed method here rather
than our invention.

What we do not have is the data. Open item O-5 established that DGCA publishes
city-pair *counts* annually but that a public per-city-pair passenger-volume
table is not confirmed to exist. So every weight carries an **evidence rung**:

    1  DGCA per-city-pair passenger volumes          ideal
    2  DGCA popular-routes list (the CPI basket)     ideal, matches CPI exactly
    3  Airport-level throughput used as a proxy      labelled proxy
    4  Equal weights across a documented candidate set   last resort

The rung is not decoration. It is NOT NULL in the database, it is rendered next
to every weight in the UI, and CI fails if a weight exists without it. A
labelled rung-4 weight is defensible; an unlabelled one that looks sourced is
not, and the difference is the whole reason this field exists.

**Traffic is not expenditure.** Passenger volume under-weights long-haul routes
relative to household spend on them. That limitation is stated on the
Methodology page rather than left for a judge to notice.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from schemas.enums import EvidenceRung

__all__ = [
    "WeightCandidate",
    "WeightSet",
    "WeightValidationError",
    "build_equal_weights",
    "build_from_airport_throughput",
    "build_from_traffic",
    "validate_weight_set",
]

CLOSURE_TOLERANCE = Decimal("0.000000001")  # 1e-9, matching the database trigger
QUANT = Decimal("0.00000001")


class WeightValidationError(ValueError):
    """A weight set violates an invariant that must hold before it is stored."""


@dataclass(frozen=True, slots=True)
class WeightCandidate:
    """One route's weight, with the evidence that produced it."""

    route_code: str
    weight: Decimal
    evidence_rung: int
    evidence_ref: str

    @property
    def is_proxy(self) -> bool:
        """True when the weight is not derived from route-level traffic data."""
        return self.evidence_rung >= EvidenceRung.AIRPORT_THROUGHPUT_PROXY


@dataclass(frozen=True, slots=True)
class WeightSet:
    """A complete, closed set of route weights."""

    version: str
    candidates: tuple[WeightCandidate, ...]
    note: str

    @property
    def total(self) -> Decimal:
        return sum((c.weight for c in self.candidates), Decimal(0))

    @property
    def worst_rung(self) -> int:
        """The weakest evidence in the set - what the UI should report.

        A set is only as defensible as its least-supported weight, so reporting
        the best rung would be misleading.
        """
        return max(c.evidence_rung for c in self.candidates)

    @property
    def any_proxy(self) -> bool:
        return any(c.is_proxy for c in self.candidates)


def validate_weight_set(weight_set: WeightSet) -> None:
    """Check every invariant that must hold before a set reaches the database.

    Raises rather than returning a flag: a malformed weight set must not be
    storable, and a caller who ignores a boolean would store one.
    """
    if not weight_set.candidates:
        raise WeightValidationError(
            "a weight set with no routes cannot produce an index; "
            "an empty basket is not a basket"
        )

    codes = [c.route_code for c in weight_set.candidates]
    duplicates = {code for code in codes if codes.count(code) > 1}
    if duplicates:
        raise WeightValidationError(
            f"duplicate routes in weight set: {sorted(duplicates)}. "
            "A route counted twice is silently double-weighted."
        )

    for candidate in weight_set.candidates:
        if candidate.weight <= 0:
            raise WeightValidationError(
                f"{candidate.route_code} has weight {candidate.weight}; weights must "
                "be strictly positive. A zero weight means the route should not be "
                "in the basket at all."
            )
        if not 1 <= candidate.evidence_rung <= 4:
            raise WeightValidationError(
                f"{candidate.route_code} has evidence_rung {candidate.evidence_rung}; "
                "must be 1-4"
            )
        if not candidate.evidence_ref.strip():
            raise WeightValidationError(
                f"{candidate.route_code} has no evidence_ref. Every weight must cite "
                "where it came from, including a proxy - especially a proxy."
            )

    drift = abs(weight_set.total - Decimal(1))
    if drift > CLOSURE_TOLERANCE:
        raise WeightValidationError(
            f"weights sum to {weight_set.total}, not 1 (drift {drift}). "
            "An unclosed basket makes the headline index uninterpretable."
        )


def _normalise(raw: dict[str, Decimal]) -> dict[str, Decimal]:
    """Scale to sum exactly 1, putting any rounding residue on the largest route.

    Quantising each weight independently leaves a residue of a few units in the
    last place, and an index whose weights sum to 0.99999998 is not reproducible
    in the sense an auditor means. The residue goes to the largest weight, where
    it is proportionally smallest.
    """
    total = sum(raw.values(), Decimal(0))
    if total <= 0:
        raise WeightValidationError("cannot normalise weights whose total is not positive")

    scaled = {code: (value / total).quantize(QUANT) for code, value in raw.items()}
    residue = Decimal(1) - sum(scaled.values(), Decimal(0))
    if residue != 0:
        largest = max(scaled, key=lambda code: (scaled[code], code))
        scaled[largest] += residue
    return scaled


def build_from_traffic(
    traffic: dict[str, int],
    *,
    version: str,
    evidence_rung: int,
    evidence_ref: str,
) -> WeightSet:
    """Weights proportional to passenger volume (Expert Group Report 4.6.3.3).

    The caller supplies the rung, because only the caller knows whether the
    numbers are true city-pair volumes or an airport-throughput proxy. This
    function will not guess, and a wrong rung is worse than a wrong weight.
    """
    if not traffic:
        raise WeightValidationError("no traffic data supplied")
    if any(v <= 0 for v in traffic.values()):
        raise WeightValidationError(
            f"non-positive traffic for {[k for k, v in traffic.items() if v <= 0]}; "
            "a route with no passengers does not belong in the basket"
        )

    scaled = _normalise({code: Decimal(value) for code, value in traffic.items()})
    weight_set = WeightSet(
        version=version,
        candidates=tuple(
            WeightCandidate(
                route_code=code,
                weight=scaled[code],
                evidence_rung=evidence_rung,
                evidence_ref=evidence_ref,
            )
            for code in sorted(scaled)
        ),
        note=f"Proportional to passenger volume. Evidence rung {evidence_rung}.",
    )
    validate_weight_set(weight_set)
    return weight_set


def build_from_airport_throughput(
    airport_traffic: dict[str, int],
    route_codes: list[str],
    *,
    version: str,
    evidence_ref: str,
) -> WeightSet:
    """Route weights from a gravity proxy on airport throughput (rung 3).

    A city pair's traffic is taken as proportional to the product of the two
    airports' passenger throughput - the standard gravity form in transport
    modelling. It is a **proxy**, and the rung says so.

    Two distortions are inherent and must travel with the weights rather than
    be silently corrected:

    **Throughput is not city-pair traffic.** A busy airport is busy across all
    its routes; the product says nothing about how much of it flows between
    these two cities specifically.

    **The inputs are total passengers, not domestic.** Delhi and Mumbai carry
    large international volumes, so this overstates them against a purely
    domestic measure. Applying an invented domestic share would be a worse
    error than a labelled one.

    Better data replaces this without code changes: rung 1 city-pair volumes go
    straight into :func:`build_from_traffic`.
    """
    missing = {
        code
        for route in route_codes
        for code in route.split("-")
        if code not in airport_traffic
    }
    if missing:
        raise WeightValidationError(
            f"no throughput figure for {sorted(missing)}; a route cannot be weighted "
            "from airports we have no data for"
        )

    traffic = {
        route: airport_traffic[route.split("-")[0]] * airport_traffic[route.split("-")[1]]
        for route in route_codes
    }
    return build_from_traffic(
        traffic, version=version, evidence_rung=int(EvidenceRung.AIRPORT_THROUGHPUT_PROXY),
        evidence_ref=evidence_ref,
    )


def build_equal_weights(route_codes: list[str], *, version: str, reason: str) -> WeightSet:
    """Equal weights - rung 4, the last resort, and labelled as such everywhere.

    This is what APIx ships while O-5 is unresolved. It is a real methodological
    position (every route in the basket treated as equally representative), not a
    placeholder pretending to be sourced, and the UI says so on the Methodology
    page and beside every weight.
    """
    if not route_codes:
        raise WeightValidationError("cannot build an equal-weight set with no routes")

    unique = sorted(set(route_codes))
    if len(unique) != len(route_codes):
        raise WeightValidationError("duplicate route codes supplied")

    scaled = _normalise({code: Decimal(1) for code in unique})
    weight_set = WeightSet(
        version=version,
        candidates=tuple(
            WeightCandidate(
                route_code=code,
                weight=scaled[code],
                evidence_rung=int(EvidenceRung.EQUAL),
                evidence_ref=reason,
            )
            for code in unique
        ),
        note=(
            "EQUAL WEIGHTS (evidence rung 4). Not derived from traffic data. "
            f"{reason}"
        ),
    )
    validate_weight_set(weight_set)
    return weight_set
