"""Seed the six advance-purchase strata.

T21 is the reason this list has six entries rather than the five in the problem
statement. MoSPI's CPI 2024 collects domestic airfare at a **21-day**
advance-purchase window (Expert Group Report section 3.9), which makes T21 the
only bucket directly comparable to the official index. It is not optional and it
is not a renumbering of T15 or T30.

lambda is uniform at 1/6 across all six buckets. That is a **labelled prototype
assumption**, not a finding: no public Indian booking-lead-time distribution was
located, so no bucket can be claimed to carry more weight than another. It is
recorded here so the assumption is visible in the data rather than buried in
code, and it must not be tuned to make output look better.
"""

from __future__ import annotations

from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import Connection
from sqlalchemy.dialects.postgresql import insert

from schemas.models import LeadTimeBucket


class BucketSeed(NamedTuple):
    """One lead-time bucket, exactly as specified in build brief section 7."""

    code: str
    days: int
    lambda_: Decimal
    cpi_comparable: bool


# Uniform lambda, stated to six decimal places to match NUMERIC(8,6).
UNIFORM_LAMBDA = Decimal("0.166667")

BUCKETS: tuple[BucketSeed, ...] = (
    BucketSeed("T1", 1, UNIFORM_LAMBDA, False),
    BucketSeed("T7", 7, UNIFORM_LAMBDA, False),
    BucketSeed("T15", 15, UNIFORM_LAMBDA, False),
    BucketSeed("T21", 21, UNIFORM_LAMBDA, True),
    BucketSeed("T30", 30, UNIFORM_LAMBDA, False),
    BucketSeed("T45", 45, UNIFORM_LAMBDA, False),
)


def seed(connection: Connection) -> int:
    """Insert the six buckets, skipping any already present. Returns rows inserted."""
    statement = (
        insert(LeadTimeBucket)
        .values(
            [
                {
                    "code": bucket.code,
                    "days": bucket.days,
                    "lambda": bucket.lambda_,
                    "cpi_comparable": bucket.cpi_comparable,
                }
                for bucket in BUCKETS
            ]
        )
        .on_conflict_do_nothing(index_elements=["code"])
        .returning(LeadTimeBucket.id)
    )
    return len(connection.execute(statement).fetchall())


__all__ = ["BUCKETS", "UNIFORM_LAMBDA", "BucketSeed", "seed"]
