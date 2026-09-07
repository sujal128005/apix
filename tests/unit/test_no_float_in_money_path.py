"""No float touches money, anywhere.

Binary floating point cannot represent 0.10, so a fare that goes through a float
comes back subtly wrong, and an index chained from wrong fares is wrong forever
after. The rule is absolute: ``Decimal`` in Python, ``NUMERIC`` in PostgreSQL.

The scan is AST-based rather than a text grep, so it looks at what the code
actually does - a ``float`` annotation or a ``float()`` call - and is not fooled
by the word appearing in a comment or by a comment hiding a real one.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
import sqlalchemy as sa

from db.settings import REPO_ROOT
from schemas.models import Base

SCANNED_ROOTS = (
    REPO_ROOT / "packages",
    REPO_ROOT / "db",
    REPO_ROOT / "scripts",
    REPO_ROOT / "tests" / "support",
)

BANNED_COLUMN_TYPES = (sa.Float, sa.REAL, sa.DOUBLE_PRECISION, sa.Double)


def python_files() -> list[Path]:
    found: list[Path] = []
    for root in SCANNED_ROOTS:
        found.extend(sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts))
    return found


def float_uses(path: Path) -> list[str]:
    """Return every place this module names `float` as a type or a conversion."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offences: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = node.func
            if isinstance(callee, ast.Name) and callee.id == "float":
                offences.append(f"line {node.lineno}: float() conversion")
            elif isinstance(callee, ast.Attribute) and callee.attr in {
                "Float",
                "REAL",
                "Double",
                "DOUBLE_PRECISION",
            }:
                offences.append(f"line {node.lineno}: {callee.attr} column type")
        elif isinstance(node, ast.AnnAssign | ast.arg) and node.annotation is not None:
            for name in ast.walk(node.annotation):
                if isinstance(name, ast.Name) and name.id == "float":
                    offences.append(f"line {node.lineno}: float annotation")
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.returns is not None:
            for name in ast.walk(node.returns):
                if isinstance(name, ast.Name) and name.id == "float":
                    offences.append(f"line {node.lineno}: float return annotation")

    return offences


def test_source_never_names_float() -> None:
    """Not in the schemas, not in the migrations, not in the seeds, not in the builders."""
    scanned = python_files()
    assert scanned, "the float scan found no files to scan, which means it proves nothing"

    offences = {
        str(path.relative_to(REPO_ROOT)): uses
        for path in scanned
        if (uses := float_uses(path))
    }
    assert not offences, f"float found on a money path: {json.dumps(offences, indent=2)}"


@pytest.mark.parametrize("table_name", sorted(Base.metadata.tables))
def test_no_floating_point_columns(table_name: str) -> None:
    table = Base.metadata.tables[table_name]
    for column in table.columns:
        assert not isinstance(column.type, BANNED_COLUMN_TYPES), (
            f"{table_name}.{column.name} is {column.type!r}; money and index "
            "values are NUMERIC"
        )


@pytest.mark.parametrize("table_name", sorted(Base.metadata.tables))
def test_numeric_columns_return_decimal(table_name: str) -> None:
    """asdecimal must stay on, or the driver hands back floats at read time."""
    table = Base.metadata.tables[table_name]
    for column in table.columns:
        if isinstance(column.type, sa.Numeric):
            assert column.type.asdecimal is True, (
                f"{table_name}.{column.name} would be read back as a float"
            )


def test_money_columns_have_the_specified_precision() -> None:
    """The brief fixes these precisions; a wider or narrower one changes results."""
    expected = {
        ("normalised_quote", "total_fare"): (12, 2),
        ("fare_component", "amount"): (12, 2),
        ("index_observation", "index_value"): (12, 6),
        ("index_observation", "prev_index_value"): (12, 6),
        ("index_contribution", "contribution"): (12, 6),
        ("route_weight", "weight"): (10, 8),
        ("lead_time_bucket", "lambda"): (8, 6),
        ("normalised_quote", "quality_score"): (4, 3),
        ("benchmark_observation", "value"): (14, 4),
    }
    for (table_name, column_name), (precision, scale) in expected.items():
        column = Base.metadata.tables[table_name].columns[column_name]
        assert isinstance(column.type, sa.Numeric)
        assert (column.type.precision, column.type.scale) == (precision, scale), (
            f"{table_name}.{column_name} is NUMERIC"
            f"({column.type.precision},{column.type.scale}), expected "
            f"NUMERIC({precision},{scale})"
        )


def test_golden_day_fares_are_exact_decimal_strings(golden_day: dict[str, object]) -> None:
    """The fixture stores money as strings so JSON parsing cannot turn it into a float."""
    from decimal import Decimal

    pairs = golden_day["pairs"]
    assert isinstance(pairs, list)
    for pair in pairs:
        for key in ("previous_fare", "current_fare"):
            raw = pair[key]
            assert isinstance(raw, str), f"{pair['pair']}.{key} must be a JSON string"
            assert Decimal(raw) == Decimal(raw).quantize(Decimal("0.01"))
