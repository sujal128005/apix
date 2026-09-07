"""Seed methodology version 1.0.0.

The parameters below are the frozen index methodology. Geometric below,
arithmetic above: elementary strata use Jevons short (chain-base), higher levels
use Young / modified Laspeyres with a weighted arithmetic mean. That asymmetry is
MoSPI's deliberate structure, not an inconsistency to be tidied up.

No weight set is seeded. ``route_weight`` ships empty because weight evidence
(open item O-5) is unresolved, and a placeholder weight would be
indistinguishable from a sourced one in every downstream artefact.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Connection
from sqlalchemy.dialects.postgresql import insert

from schemas.models import MethodologyVersion

VERSION = "1.0.0"

CHANGELOG = (
    "Initial. Jevons short (chain-base) elementary; Young/Modified Laspeyres "
    "higher-level, weighted arithmetic."
)

PARAMS: dict[str, Any] = {
    "elementary_formula": "jevons_short",
    "higher_level_formula": "young_modified_laspeyres",
    "higher_level_aggregation": "weighted_arithmetic_mean",
    "outlier_method": "mad_log_relatives",
    "outlier_k": 3.5,
    "min_quotes_per_stratum": 3,
    "winsorise_below_n": 5,
    "winsorise_percentiles": [5, 95],
    "imputation": "carry_until_reappearance_no_weight_redistribution",
    "base_index_value": 100,
}


def effective_from() -> date:
    """Today in UTC. Storage is UTC everywhere; IST is a rendering concern."""
    return datetime.now(UTC).date()


def seed(connection: Connection) -> int:
    """Insert methodology 1.0.0 if absent. Returns rows inserted."""
    statement = (
        insert(MethodologyVersion)
        .values(
            [
                {
                    "version": VERSION,
                    "effective_from": effective_from(),
                    "params": PARAMS,
                    "changelog": CHANGELOG,
                }
            ]
        )
        .on_conflict_do_nothing(index_elements=["version"])
        .returning(MethodologyVersion.id)
    )
    return len(connection.execute(statement).fetchall())


__all__ = ["CHANGELOG", "PARAMS", "VERSION", "effective_from", "seed"]
