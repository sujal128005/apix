"""Shared contract base and the annotated scalar types used across contracts.

Two properties are enforced here rather than repeated in every model:

* **Money is Decimal, never float.** The annotated aliases mirror the exact
  NUMERIC precision and scale of the corresponding column, so a value that
  would be silently rounded by the database is rejected at the boundary
  instead.
* **Timestamps are timezone-aware.** PostgreSQL will happily accept a naive
  timestamp into a TIMESTAMPTZ column and silently interpret it in the session
  time zone. That is a real correctness hazard for a chained index, so every
  TIMESTAMPTZ field is typed AwareDatetime and a naive value raises
  ValidationError before it reaches the driver.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

# --- money and index scalars ------------------------------------------------
# NUMERIC(12,2) - fares and fare components.
Money = Annotated[Decimal, Field(max_digits=12, decimal_places=2)]
PositiveMoney = Annotated[Decimal, Field(max_digits=12, decimal_places=2, gt=0)]
NonNegativeMoney = Annotated[Decimal, Field(max_digits=12, decimal_places=2, ge=0)]

# NUMERIC(12,6) - index values and contributions.
IndexValue = Annotated[Decimal, Field(max_digits=12, decimal_places=6, gt=0)]
SignedIndexValue = Annotated[Decimal, Field(max_digits=12, decimal_places=6)]

# NUMERIC(10,8) - route weights, bounded by the CHECK on the column.
Weight = Annotated[Decimal, Field(max_digits=10, decimal_places=8, gt=0, le=1)]

# NUMERIC(8,6) - lead-time bucket lambda.
Lambda = Annotated[Decimal, Field(max_digits=8, decimal_places=6)]

# NUMERIC(4,3) - quality score.
QualityScore = Annotated[Decimal, Field(max_digits=4, decimal_places=3)]

# --- string scalars ---------------------------------------------------------
IataCode = Annotated[str, Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")]
IcaoCode = Annotated[str, Field(min_length=4, max_length=4)]
RouteCode = Annotated[str, Field(min_length=7, max_length=7, pattern=r"^[A-Z]{3}-[A-Z]{3}$")]
# IATA airline designators are alphanumeric (6E, AI, QP), so no letter-only pattern.
CarrierCode = Annotated[str, Field(min_length=2, max_length=2)]
NonEmptyText = Annotated[str, Field(min_length=1)]
Sha256Hex = Annotated[str, Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]

Utc = AwareDatetime


class ApixContract(BaseModel):
    """Base for every table contract.

    from_attributes lets a contract be validated straight off a SQLAlchemy
    instance; extra='forbid' means a column added to a model without a matching
    contract field is caught by the round-trip test rather than silently
    ignored.
    """

    model_config = ConfigDict(
        from_attributes=True,
        extra="forbid",
        validate_assignment=True,
    )

    id: UUID
    created_at: Utc


__all__ = [
    "ApixContract",
    "CarrierCode",
    "IataCode",
    "IcaoCode",
    "IndexValue",
    "Lambda",
    "Money",
    "NonEmptyText",
    "NonNegativeMoney",
    "PositiveMoney",
    "QualityScore",
    "RouteCode",
    "Sha256Hex",
    "SignedIndexValue",
    "Utc",
    "Weight",
]
