"""collection_request.query_hash must be stable across machines and installations.

The hash is built from the codes (``indigo_web``, ``DEL-BOM``, ``T21``), not the
UUID primary keys, precisely so that the same logical search produces the same
hash on a judge's fresh checkout as it does here. Keys are per-installation;
reproducibility is a requirement.
"""

from __future__ import annotations

import hashlib
from datetime import date

import pytest

from schemas.hashing import compute_query_hash

BASE_ARGS = {
    "source_code": "indigo_web",
    "route_code": "DEL-BOM",
    "bucket_code": "T21",
    "travel_date": date(2026, 3, 24),
    "collected_date": date(2026, 3, 3),
}


def test_matches_the_documented_canonical_form() -> None:
    """The canonical string is source|route|bucket|travel|collected, ISO dates."""
    expected = hashlib.sha256(
        b"indigo_web|DEL-BOM|T21|2026-03-24|2026-03-03"
    ).hexdigest()
    assert compute_query_hash(**BASE_ARGS) == expected


def test_is_lower_case_hex_of_the_right_length() -> None:
    digest = compute_query_hash(**BASE_ARGS)
    assert len(digest) == 64
    assert digest == digest.lower()
    assert all(character in "0123456789abcdef" for character in digest)


def test_is_deterministic() -> None:
    assert compute_query_hash(**BASE_ARGS) == compute_query_hash(**BASE_ARGS)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_code", "amadeus"),
        ("route_code", "BOM-DEL"),
        ("bucket_code", "T7"),
        ("travel_date", date(2026, 3, 25)),
        ("collected_date", date(2026, 3, 4)),
    ],
)
def test_every_component_changes_the_hash(field: str, value: object) -> None:
    """No component may be ignored, or two different searches would collide."""
    changed = {**BASE_ARGS, field: value}
    assert compute_query_hash(**changed) != compute_query_hash(**BASE_ARGS)


def test_direction_matters() -> None:
    """Routes are directional, so DEL-BOM and BOM-DEL are different searches."""
    forward = compute_query_hash(**BASE_ARGS)
    reverse = compute_query_hash(**{**BASE_ARGS, "route_code": "BOM-DEL"})
    assert forward != reverse


def test_surrounding_whitespace_is_ignored() -> None:
    padded = {**BASE_ARGS, "source_code": "  indigo_web  ", "route_code": " DEL-BOM "}
    assert compute_query_hash(**padded) == compute_query_hash(**BASE_ARGS)
