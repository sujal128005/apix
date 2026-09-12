"""Every table has a contract, and no contract has drifted from its table.

A contract that silently loses a column is worse than no contract: it validates
successfully while dropping data. So the parity checks here are exact in both
directions - fields and nullability.
"""

from __future__ import annotations

import types
import typing
from decimal import Decimal

import pytest
from sqlalchemy import inspect

from schemas.contracts import CONTRACT_BY_TABLE, ApixContract
from schemas.models import ALL_MODELS, ALL_TABLES, Base

MODEL_BY_TABLE = {model.__tablename__: model for model in ALL_MODELS}


def _base_types(annotation: object) -> set[object]:
    """Flatten an annotation to the concrete types it can hold.

    Unwraps ``Annotated[...]`` (the contracts use it to carry NUMERIC precision)
    and ``X | None`` unions, so a check can look at the underlying type.
    """
    origin = typing.get_origin(annotation)
    if origin is typing.Annotated:
        return _base_types(typing.get_args(annotation)[0])
    if origin in (typing.Union, types.UnionType):
        found: set[object] = set()
        for argument in typing.get_args(annotation):
            found |= _base_types(argument)
        return found
    return {annotation}


def _allows_none(annotation: object) -> bool:
    """True if the annotation is Optional/`| None`."""
    return type(None) in _base_types(annotation)


def test_every_table_has_a_contract() -> None:
    assert set(CONTRACT_BY_TABLE) == set(ALL_TABLES)


def test_every_contract_maps_to_a_real_table() -> None:
    assert set(CONTRACT_BY_TABLE) == set(Base.metadata.tables)


def test_the_schema_has_twenty_three_tables() -> None:
    """21 from build brief section 5, plus base_period (Phase 3 review) and
    publication (Phase 21 release lifecycle).

    Asserted as an exact count so that adding a table is a deliberate act: a new
    table without a contract would otherwise slip through, and every table in
    this schema is part of the audit trail.
    """
    assert len(ALL_TABLES) == 23


@pytest.mark.parametrize("table", sorted(ALL_TABLES))
def test_contract_fields_match_orm_columns(table: str) -> None:
    """Field for field, in both directions."""
    model = MODEL_BY_TABLE[table]
    contract = CONTRACT_BY_TABLE[table]

    orm_attributes = {attr.key for attr in inspect(model).mapper.column_attrs}
    contract_fields = set(contract.model_fields)

    assert orm_attributes == contract_fields, (
        f"{table}: only on the model {sorted(orm_attributes - contract_fields)}, "
        f"only on the contract {sorted(contract_fields - orm_attributes)}"
    )


@pytest.mark.parametrize("table", sorted(ALL_TABLES))
def test_contract_nullability_matches_the_columns(table: str) -> None:
    """A nullable column is optional on the contract, and nothing else is."""
    model = MODEL_BY_TABLE[table]
    contract = CONTRACT_BY_TABLE[table]
    mapper = inspect(model).mapper

    mismatches: list[str] = []
    for attribute in mapper.column_attrs:
        column = attribute.columns[0]
        field = contract.model_fields[attribute.key]
        optional_on_contract = _allows_none(field.annotation)
        if column.nullable != optional_on_contract:
            mismatches.append(
                f"{attribute.key}: column nullable={column.nullable}, "
                f"contract optional={optional_on_contract}"
            )

    assert not mismatches, f"{table}: " + "; ".join(mismatches)


@pytest.mark.parametrize("table", sorted(ALL_TABLES))
def test_contracts_derive_from_the_shared_base(table: str) -> None:
    contract = CONTRACT_BY_TABLE[table]
    assert issubclass(contract, ApixContract)
    assert contract.model_config["extra"] == "forbid"
    assert contract.model_config["from_attributes"] is True


@pytest.mark.parametrize("table", sorted(ALL_TABLES))
def test_numeric_columns_are_decimal_on_the_contract(table: str) -> None:
    """No NUMERIC column may be typed as float on the way in or out."""
    model = MODEL_BY_TABLE[table]
    contract = CONTRACT_BY_TABLE[table]
    mapper = inspect(model).mapper

    for attribute in mapper.column_attrs:
        column = attribute.columns[0]
        if column.type.__class__.__name__ not in {"Numeric", "NUMERIC"}:
            continue
        annotation = contract.model_fields[attribute.key].annotation
        candidates = _base_types(annotation)
        assert Decimal in candidates, (
            f"{table}.{attribute.key} is NUMERIC in the database but "
            f"{annotation!r} on the contract; money and index values are Decimal"
        )
