"""UUIDv7 primary keys must be well-formed and time-ordered.

Ordering is not cosmetic: lineage traversal reads rows back in insertion order,
and a chained index depends on knowing which observation came first.
"""

from __future__ import annotations

import time
from uuid import UUID

import pytest

from schemas.uuid7 import timestamp_ms, uuid7

SAMPLE_SIZE = 5_000


def test_version_and_variant_bits() -> None:
    value = uuid7()
    assert value.version == 7
    # RFC 9562 variant is 0b10 in the two most significant bits of byte 8.
    assert (value.bytes[8] & 0xC0) == 0x80


def test_identifiers_are_unique() -> None:
    generated = {uuid7() for _ in range(SAMPLE_SIZE)}
    assert len(generated) == SAMPLE_SIZE


def test_identifiers_are_monotonic_even_within_one_millisecond() -> None:
    """The 12-bit counter in rand_a keeps ordering inside a single millisecond."""
    generated = [uuid7() for _ in range(SAMPLE_SIZE)]
    assert generated == sorted(generated, key=lambda value: value.int)


def test_embedded_timestamp_tracks_wall_clock() -> None:
    before = time.time_ns() // 1_000_000
    value = uuid7()
    after = time.time_ns() // 1_000_000
    assert before <= timestamp_ms(value) <= after + 1


def test_timestamp_ms_rejects_other_uuid_versions() -> None:
    uuid4_like = UUID("f47ac10b-58cc-4372-a567-0e02b2c3d479")
    with pytest.raises(ValueError, match="not a UUIDv7"):
        timestamp_ms(uuid4_like)


def test_string_form_is_a_normal_uuid() -> None:
    value = uuid7()
    assert UUID(str(value)) == value
    assert len(str(value)) == 36
