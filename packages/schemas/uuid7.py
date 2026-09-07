"""UUIDv7 generation (RFC 9562 §5.7).

PostgreSQL 16 has no built-in ``uuidv7()``, so APIx ships two implementations
that must agree on layout:

* this module, used as the SQLAlchemy client-side default for every primary key
* ``uuidv7()`` in PL/pgSQL, installed by migration 0001 as the server-side
  default so that rows inserted by raw SQL (tests, psql, future maintenance
  scripts) get the same shape.

Layout, most significant bit first::

    48 bits  unix_ts_ms   big-endian milliseconds since the Unix epoch
     4 bits  version      0b0111
    12 bits  rand_a       monotonic counter within the millisecond
     2 bits  variant      0b10
    62 bits  rand_b       cryptographically random

The counter in ``rand_a`` implements RFC 9562 §6.2 "Monotonic Random"
so that identifiers minted inside the same millisecond still sort in creation
order. That matters here: index observations and collection requests are read
back in insertion order during lineage traversal.
"""

from __future__ import annotations

import os
import threading
import time
from uuid import UUID

_MAX_TS = (1 << 48) - 1
_MAX_SEQ = (1 << 12) - 1
_MAX_RAND_B = (1 << 62) - 1

_lock = threading.Lock()
_last_timestamp_ms: int = -1
_last_sequence: int = 0


def uuid7() -> UUID:
    """Return a fresh, monotonically increasing UUIDv7."""
    global _last_timestamp_ms, _last_sequence

    with _lock:
        timestamp_ms = time.time_ns() // 1_000_000

        if timestamp_ms > _last_timestamp_ms:
            _last_timestamp_ms = timestamp_ms
            _last_sequence = 0
        else:
            # Same millisecond, or the wall clock moved backwards. Either way we
            # keep the previous timestamp and advance the counter, so ordering
            # never regresses.
            _last_sequence += 1
            if _last_sequence > _MAX_SEQ:
                # Counter exhausted: borrow a millisecond from the future.
                _last_timestamp_ms += 1
                _last_sequence = 0
            timestamp_ms = _last_timestamp_ms

        sequence = _last_sequence

    rand_b = int.from_bytes(os.urandom(8), "big") & _MAX_RAND_B

    value = (timestamp_ms & _MAX_TS) << 80
    value |= 0x7 << 76
    value |= sequence << 64
    value |= 0b10 << 62
    value |= rand_b
    return UUID(int=value)


def timestamp_ms(value: UUID) -> int:
    """Extract the embedded millisecond timestamp from a UUIDv7."""
    if value.version != 7:
        raise ValueError(f"not a UUIDv7: version={value.version}")
    return value.int >> 80


__all__ = ["timestamp_ms", "uuid7"]
