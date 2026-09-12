"""Dissemination: describing the dataset, and getting it out.

Two jobs kept apart on purpose.

**The dataset definition** — what dimensions the data has, what codes each
dimension takes, what is measured and in what units — is a statement about the
statistic. It does not depend on any exchange format.

**Serialisation** turns that into whatever a consumer needs: SDMX for exchange
with other statistical bodies, CSV for an analyst, JSON for an API client.

Keeping them apart matters because the ministry's dissemination standard has not
been confirmed. SDMX is the usual choice for official statistics and is provided
here, but if MoSPI's stack expects something else, only the serialiser changes —
the definition, which is the part carrying the statistical meaning, does not.

**Only published figures leave.** Every export path filters on publication state
(Phase 21). An export is a publication: a CSV containing an unapproved figure is
as much a disclosure as a web page showing one, and is easier to do by accident.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

__all__ = [
    "APIX_DATASET",
    "Codelist",
    "DatasetDefinition",
    "Dimension",
    "Measure",
    "to_csv",
    "to_json",
    "to_sdmx_structure",
]


@dataclass(frozen=True, slots=True)
class Codelist:
    """The permitted values of a dimension, each with a human-readable name.

    Enumerated rather than free text. A consumer joining on `DEL-BOM` needs to
    know that is the whole set of route codes and what each means, not to infer
    it from whatever happened to appear in one extract.
    """

    id: str
    name: str
    codes: dict[str, str]


@dataclass(frozen=True, slots=True)
class Dimension:
    """One axis of the dataset."""

    id: str
    name: str
    codelist: Codelist | None = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class Measure:
    """What is actually being measured, and in what units."""

    id: str
    name: str
    unit: str
    decimals: int
    description: str = ""


@dataclass(frozen=True, slots=True)
class DatasetDefinition:
    """A complete structural description of the statistic."""

    id: str
    name: str
    agency: str
    version: str
    dimensions: tuple[Dimension, ...]
    measures: tuple[Measure, ...]
    attributes: dict[str, str] = field(default_factory=dict)
    description: str = ""

    def dimension_ids(self) -> tuple[str, ...]:
        return tuple(d.id for d in self.dimensions)


# --------------------------------------------------------------------------
# The APIx dataset
# --------------------------------------------------------------------------

FREQUENCY = Codelist(
    id="CL_FREQ",
    name="Frequency",
    codes={"D": "Daily", "W": "Weekly", "M": "Monthly"},
)

INDEX_LEVEL = Codelist(
    id="CL_APIX_LEVEL",
    name="Aggregation level",
    codes={
        "HEADLINE": "National airfare index",
        "ROUTE": "Route-level index",
        "STRATUM": "Route and advance-purchase window",
    },
)

LEAD_TIME = Codelist(
    id="CL_APIX_LEAD_TIME",
    name="Advance-purchase window",
    codes={
        "T1": "1 day before departure",
        "T7": "7 days before departure",
        "T15": "15 days before departure",
        "T21": "21 days before departure (CPI 2024 comparable)",
        "T30": "30 days before departure",
        "T45": "45 days before departure",
    },
)

APIX_DATASET = DatasetDefinition(
    id="APIX",
    name="Airfare Price Index",
    agency="MoSPI",
    version="1.0",
    description=(
        "Daily price index for Indian domestic airfare, compiled using the CPI 2024 "
        "framework: Jevons short (chain-base) at the elementary level and Young / "
        "Modified Laspeyres above it."
    ),
    dimensions=(
        Dimension(id="FREQ", name="Frequency", codelist=FREQUENCY),
        Dimension(id="TIME_PERIOD", name="Time period", description="ISO 8601 date"),
        Dimension(id="LEVEL", name="Aggregation level", codelist=INDEX_LEVEL),
        Dimension(
            id="ROUTE",
            name="Route",
            description="IATA city pair, ORIG-DEST. Empty at HEADLINE level.",
        ),
        Dimension(
            id="LEAD_TIME",
            name="Advance-purchase window",
            codelist=LEAD_TIME,
            description="Empty above STRATUM level.",
        ),
    ),
    measures=(
        Measure(
            id="OBS_VALUE",
            name="Index value",
            unit="index points",
            decimals=6,
            description=(
                "Base period = 100. The base is APIx's own first collection window, "
                "not CPI's 2024=100, so levels are not comparable with CPI — only "
                "movements are."
            ),
        ),
    ),
    attributes={
        "METHODOLOGY_VERSION": "Methodology version that produced the value",
        "WEIGHT_SET_VERSION": "Route weight set in force",
        "REVISION": "Revision number; 1 is the first publication of this period",
        "OBS_STATUS": "Publication state",
        "STD_ERROR": "Sampling standard error, where estimable",
        "PROVENANCE": "Provenance of the underlying observations",
    },
)


# --------------------------------------------------------------------------
# Serialisation
# --------------------------------------------------------------------------


def to_sdmx_structure(dataset: DatasetDefinition) -> dict[str, Any]:
    """An SDMX-JSON structure message describing the dataset.

    Provided because SDMX is the usual exchange standard between statistical
    bodies. **Confirm the ministry's dissemination stack before relying on it**:
    if they expect a different format, this function is replaced and nothing
    else is.
    """
    return {
        "meta": {
            "schema": "https://raw.githubusercontent.com/sdmx-twg/sdmx-json/master/structure-message/tools/schemas/2.0.0/sdmx-json-structure-schema.json",
            "id": f"IREF-{dataset.id}",
            "prepared": datetime.now(UTC).isoformat(),
            "sender": {"id": dataset.agency},
        },
        "data": {
            "dataStructures": [
                {
                    "id": f"DSD_{dataset.id}",
                    "agencyID": dataset.agency,
                    "version": dataset.version,
                    "name": dataset.name,
                    "description": dataset.description,
                    "dataStructureComponents": {
                        "dimensionList": {
                            "dimensions": [
                                {
                                    "id": d.id,
                                    "name": d.name,
                                    "position": i,
                                    **(
                                        {"localRepresentation": {"enumeration": d.codelist.id}}
                                        if d.codelist
                                        else {}
                                    ),
                                }
                                for i, d in enumerate(dataset.dimensions)
                            ]
                        },
                        "measureList": {
                            "measures": [
                                {
                                    "id": m.id,
                                    "name": m.name,
                                    "localRepresentation": {
                                        "textFormat": {
                                            "textType": "Double",
                                            "decimals": m.decimals,
                                        }
                                    },
                                }
                                for m in dataset.measures
                            ]
                        },
                        "attributeList": {
                            "attributes": [
                                {"id": key, "name": description}
                                for key, description in dataset.attributes.items()
                            ]
                        },
                    },
                }
            ],
            "codelists": [
                {
                    "id": codelist.id,
                    "agencyID": dataset.agency,
                    "version": dataset.version,
                    "name": codelist.name,
                    "codes": [
                        {"id": code, "name": name} for code, name in codelist.codes.items()
                    ],
                }
                for codelist in _codelists(dataset)
            ],
        },
    }


def _codelists(dataset: DatasetDefinition) -> list[Codelist]:
    seen: dict[str, Codelist] = {}
    for dimension in dataset.dimensions:
        if dimension.codelist and dimension.codelist.id not in seen:
            seen[dimension.codelist.id] = dimension.codelist
    return list(seen.values())


def to_csv(rows: list[dict[str, Any]], dataset: DatasetDefinition = APIX_DATASET) -> str:
    """Bulk CSV, with the methodology stamped on every row.

    Per-row rather than in a header comment: extracts get filtered, sorted,
    pasted into spreadsheets and split apart. A provenance line at the top
    survives none of that, and a row that outlives its context is a number
    nobody can attribute.
    """
    columns = [
        *dataset.dimension_ids(),
        *[m.id for m in dataset.measures],
        *dataset.attributes.keys(),
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: _csv_value(row.get(k)) for k in columns})
    return buffer.getvalue()


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return f"{value:f}"
    return str(value)


def to_json(
    rows: list[dict[str, Any]],
    dataset: DatasetDefinition = APIX_DATASET,
    *,
    extracted_at: datetime | None = None,
) -> dict[str, Any]:
    """Bulk JSON, self-describing enough to be read without documentation."""
    return {
        "dataset": {
            "id": dataset.id,
            "name": dataset.name,
            "agency": dataset.agency,
            "version": dataset.version,
            "description": dataset.description,
        },
        "structure": {
            "dimensions": [
                {"id": d.id, "name": d.name, "codes": d.codelist.codes if d.codelist else None}
                for d in dataset.dimensions
            ],
            "measures": [
                {"id": m.id, "name": m.name, "unit": m.unit, "decimals": m.decimals}
                for m in dataset.measures
            ],
            "attributes": dataset.attributes,
        },
        "extracted_at": (extracted_at or datetime.now(UTC)).isoformat(),
        "observations": len(rows),
        "usage": (
            "Index levels are not comparable with CPI, which uses a different base "
            "period. Only movements are comparable. Every observation carries the "
            "methodology version that produced it. Index values are strings, not "
            "JSON numbers, so that a published figure is not altered by binary "
            "floating-point representation in transit."
        ),
        "data": json.loads(json.dumps(rows, default=_json_value)),
    }


def _json_value(value: Any) -> Any:
    """Serialise for JSON without routing money through a float.

    Index values go out as **strings**, not JSON numbers. JSON has no decimal
    type, so ``float(Decimal("110.234567"))`` is the obvious conversion and the
    wrong one: a consumer can receive 110.23456700000001 for a figure published
    as 110.234567, and for an official statistic that is a different number.

    This is what SDMX does with observation values, for the same reason. A
    consumer parsing a string gets exactly what was published.
    """
    if isinstance(value, Decimal):
        return f"{value:f}"
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
