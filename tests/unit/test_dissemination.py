"""Dataset definition and export formats."""

from __future__ import annotations

from decimal import Decimal

from pipeline.dissemination import (
    APIX_DATASET,
    to_csv,
    to_json,
    to_sdmx_structure,
)


def row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "FREQ": "D",
        "TIME_PERIOD": "2026-09-15",
        "LEVEL": "ROUTE",
        "ROUTE": "DEL-BOM",
        "LEAD_TIME": "",
        "OBS_VALUE": Decimal("110.234567"),
        "METHODOLOGY_VERSION": "1.1.0",
        "WEIGHT_SET_VERSION": "2026.2-airport-proxy-rung3",
        "REVISION": 1,
        "OBS_STATUS": "PUBLISHED",
    }
    base.update(overrides)
    return base


# -- the dataset definition ------------------------------------------------


def test_the_cpi_comparable_window_is_named_in_the_codelist() -> None:
    """A consumer must not have to know from elsewhere why T21 matters."""
    lead_time = next(d for d in APIX_DATASET.dimensions if d.id == "LEAD_TIME")
    assert lead_time.codelist is not None
    assert "CPI 2024 comparable" in lead_time.codelist.codes["T21"]


def test_the_measure_states_that_levels_are_not_comparable_with_cpi() -> None:
    """The caveat travels with the structure, not just the dashboard."""
    measure = APIX_DATASET.measures[0]
    assert "not comparable with CPI" in measure.description
    assert "movements" in measure.description


def test_every_dimension_with_a_fixed_domain_has_a_codelist() -> None:
    """Free text where a domain exists forces a consumer to infer it from
    whatever happened to appear in one extract."""
    enumerated = {d.id for d in APIX_DATASET.dimensions if d.codelist}
    assert {"FREQ", "LEVEL", "LEAD_TIME"} <= enumerated


# -- SDMX ------------------------------------------------------------------


def test_the_structure_message_declares_dimensions_in_order() -> None:
    message = to_sdmx_structure(APIX_DATASET)
    dimensions = message["data"]["dataStructures"][0]["dataStructureComponents"][
        "dimensionList"
    ]["dimensions"]
    assert [d["id"] for d in dimensions] == list(APIX_DATASET.dimension_ids())
    assert [d["position"] for d in dimensions] == list(range(len(dimensions)))


def test_codelists_are_emitted_once_each() -> None:
    codelists = to_sdmx_structure(APIX_DATASET)["data"]["codelists"]
    ids = [c["id"] for c in codelists]
    assert len(ids) == len(set(ids))


def test_index_values_are_declared_to_six_decimals() -> None:
    measures = to_sdmx_structure(APIX_DATASET)["data"]["dataStructures"][0][
        "dataStructureComponents"
    ]["measureList"]["measures"]
    assert measures[0]["localRepresentation"]["textFormat"]["decimals"] == 6


# -- CSV -------------------------------------------------------------------


def test_every_csv_row_carries_its_methodology() -> None:
    """Per row, not in a header comment.

    Extracts get filtered, sorted, and pasted into spreadsheets. A provenance
    line at the top of the file survives none of that, and a row that outlives
    its context is a number nobody can attribute.
    """
    lines = to_csv([row(), row(TIME_PERIOD="2026-09-16")]).strip().splitlines()
    assert len(lines) == 3
    for line in lines[1:]:
        assert "1.1.0" in line
        assert "2026.2-airport-proxy-rung3" in line


def test_decimals_are_not_rendered_in_scientific_notation() -> None:
    """A spreadsheet reading 1.1E+2 is a different number to most people."""
    assert "110.234567" in to_csv([row()])
    assert "E+" not in to_csv([row()])


def test_missing_attributes_become_empty_not_none() -> None:
    assert ",None," not in to_csv([row(STD_ERROR=None)])


def test_the_csv_columns_follow_the_dataset_definition() -> None:
    header = to_csv([row()]).splitlines()[0]
    for dimension in APIX_DATASET.dimension_ids():
        assert dimension in header
    assert "OBS_VALUE" in header


# -- JSON ------------------------------------------------------------------


def test_the_json_extract_is_self_describing() -> None:
    """Readable without fetching separate documentation."""
    payload = to_json([row()])
    assert payload["dataset"]["agency"] == "MoSPI"
    assert payload["structure"]["dimensions"]
    assert payload["observations"] == 1
    assert "extracted_at" in payload


def test_the_json_extract_states_how_it_may_be_used() -> None:
    """The levels caveat must not be lost when data leaves the dashboard."""
    usage = to_json([row()])["usage"]
    assert "not comparable with CPI" in usage
    assert "movements" in usage


def test_index_values_are_serialised_as_strings_not_json_numbers() -> None:
    """JSON has no decimal type, and float() is the wrong conversion here.

    float(Decimal("110.234567")) can reach a consumer as 110.23456700000001.
    For an official statistic that is a different number from the one
    published. SDMX serialises observation values as strings for the same
    reason.
    """
    import json

    payload = to_json([row()])
    encoded = json.dumps(payload)

    assert '"110.234567"' in encoded
    assert "110.23456700" not in encoded
    assert payload["data"][0]["OBS_VALUE"] == "110.234567"
    assert isinstance(payload["data"][0]["OBS_VALUE"], str)
