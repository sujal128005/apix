"""Deterministic hashes used as database keys.

``compute_query_hash`` produces ``collection_request.query_hash``, the unique
key that stops the collector issuing the same search twice.

Identity is expressed with the *codes* (``indigo_web``, ``DEL-BOM``, ``T21``),
not the UUID primary keys, so the same logical search hashes identically on a
judge's fresh checkout as on ours. UUIDv7 keys differ per installation; a hash
built from them would not be reproducible across deployments, and bit-for-bit
reproducibility is a stated requirement of this project.
"""

from __future__ import annotations

import hashlib
from datetime import date

_SEPARATOR = "|"


def compute_query_hash(
    *,
    source_code: str,
    route_code: str,
    bucket_code: str,
    travel_date: date,
    collected_date: date,
) -> str:
    """Return the lower-case hex sha256 of the canonical search identity.

    The canonical form is ``source|route|bucket|travel_date|collected_date``
    with dates in ISO-8601 (``YYYY-MM-DD``) and no surrounding whitespace.
    """
    canonical = _SEPARATOR.join(
        (
            source_code.strip(),
            route_code.strip(),
            bucket_code.strip(),
            travel_date.isoformat(),
            collected_date.isoformat(),
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = ["compute_query_hash"]
