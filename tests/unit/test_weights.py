"""Route weights: closure, evidence, and the honesty of a labelled proxy."""

from __future__ import annotations

from decimal import Decimal

import pytest

from pipeline.weights import (
    WeightCandidate,
    WeightSet,
    WeightValidationError,
    build_equal_weights,
    build_from_traffic,
    validate_weight_set,
)


def test_traffic_weights_are_proportional_and_closed() -> None:
    ws = build_from_traffic(
        {"DEL-BOM": 5_000_000, "DEL-BLR": 3_000_000, "BOM-BLR": 2_000_000},
        version="t1", evidence_rung=1, evidence_ref="DGCA Handbook 2024-25, Table X",
    )
    assert ws.total == Decimal("1.00000000")
    weights = {c.route_code: c.weight for c in ws.candidates}
    assert weights["DEL-BOM"] == Decimal("0.50000000")
    assert weights["BOM-BLR"] == Decimal("0.20000000")


def test_weights_close_to_exactly_one_even_when_they_do_not_divide_evenly() -> None:
    """Three equal routes give 0.33333333 each; the residue must not be lost.

    A basket summing to 0.99999999 is not reproducible in the sense an auditor
    means, so the rounding residue is placed on the largest weight.
    """
    ws = build_equal_weights(["A-B", "C-D", "E-F"], version="e1", reason="O-5 unresolved")
    assert ws.total == Decimal("1.00000000")


def test_equal_weights_are_rung_four_and_say_so() -> None:
    ws = build_equal_weights(["A-B", "C-D"], version="e1", reason="O-5 unresolved")
    assert all(c.evidence_rung == 4 for c in ws.candidates)
    assert ws.worst_rung == 4
    assert ws.any_proxy is True
    assert "EQUAL WEIGHTS" in ws.note
    assert "Not derived from traffic data" in ws.note


def test_the_worst_rung_is_reported_not_the_best() -> None:
    """A basket is only as defensible as its least-supported weight."""
    ws = WeightSet(
        version="mixed",
        candidates=(
            WeightCandidate("A-B", Decimal("0.5"), 1, "DGCA city-pair volumes"),
            WeightCandidate("C-D", Decimal("0.5"), 4, "no evidence available"),
        ),
        note="mixed",
    )
    assert ws.worst_rung == 4


def test_an_unclosed_basket_is_refused() -> None:
    ws = WeightSet(
        version="bad",
        candidates=(
            WeightCandidate("A-B", Decimal("0.5"), 1, "ref"),
            WeightCandidate("C-D", Decimal("0.4"), 1, "ref"),
        ),
        note="",
    )
    with pytest.raises(WeightValidationError, match="sum to"):
        validate_weight_set(ws)


def test_a_weight_without_evidence_is_refused() -> None:
    """Especially a proxy. An uncited weight looks identical to a sourced one."""
    ws = WeightSet(
        version="bad",
        candidates=(WeightCandidate("A-B", Decimal("1"), 4, "   "),),
        note="",
    )
    with pytest.raises(WeightValidationError, match="no evidence_ref"):
        validate_weight_set(ws)


def test_a_duplicate_route_is_refused() -> None:
    ws = WeightSet(
        version="bad",
        candidates=(
            WeightCandidate("A-B", Decimal("0.5"), 1, "ref"),
            WeightCandidate("A-B", Decimal("0.5"), 1, "ref"),
        ),
        note="",
    )
    with pytest.raises(WeightValidationError, match="duplicate"):
        validate_weight_set(ws)


def test_an_empty_basket_is_refused() -> None:
    with pytest.raises(WeightValidationError, match="no routes"):
        validate_weight_set(WeightSet(version="x", candidates=(), note=""))


def test_a_route_with_no_passengers_is_refused() -> None:
    with pytest.raises(WeightValidationError, match="non-positive traffic"):
        build_from_traffic({"A-B": 100, "C-D": 0}, version="x", evidence_rung=1, evidence_ref="r")


def test_weights_are_deterministic() -> None:
    traffic = {"DEL-BOM": 5_000_000, "DEL-BLR": 3_000_000}
    first = build_from_traffic(traffic, version="v", evidence_rung=1, evidence_ref="r")
    second = build_from_traffic(dict(reversed(list(traffic.items()))), version="v",
                                evidence_rung=1, evidence_ref="r")
    assert [(c.route_code, c.weight) for c in first.candidates] == [
        (c.route_code, c.weight) for c in second.candidates
    ]
