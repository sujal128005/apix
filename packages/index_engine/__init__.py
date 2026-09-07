"""APIx index engine: deterministic, pure, and reproducible.

No I/O. The engine is a function of (matched pairs, previous index, weights,
methodology parameters), which is what makes reproducibility testable rather
than aspirational.

Elementary level: Jevons short (chain-base), geometric.
Higher levels:    Young / Modified Laspeyres, weighted arithmetic.

Both follow MoSPI's published CPI 2024 method - see INDEX-METHODOLOGY.md v0.2.
"""

from __future__ import annotations

from index_engine.aggregate import (
    AggregateResult,
    Component,
    Contribution,
    weighted_arithmetic,
)
from index_engine.jevons import (
    ElementaryResult,
    MatchedPair,
    OutlierVerdict,
    jevons_short,
    mad_screen,
)

__all__ = [
    "AggregateResult",
    "Component",
    "Contribution",
    "ElementaryResult",
    "MatchedPair",
    "OutlierVerdict",
    "jevons_short",
    "mad_screen",
    "weighted_arithmetic",
]
