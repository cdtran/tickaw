"""Temporal inference, Parquet typing, and query execution with known answers."""

import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from packages.data_engine.execution import catalog_from_profile, execute_plan
from packages.data_engine.profiling import profile_csv
from packages.data_engine.query_plan import PlanError, validate_plan


def profile(tmp_path, values):
    source, parquet = tmp_path / "input.csv", tmp_path / "data.parquet"
    source.write_text("when,revenue\n" + "".join(f"{value},1\n" for value in values))
    result = profile_csv(source, parquet, 1024**2)
    return result, parquet


def query():
    return {
        "plan_version": 2,
        "dimensions": ["when"],
        "metrics": [{"op": "sum", "column": "revenue", "alias": "total"}],
        "filters": [],
        "order_by": [],
        "limit": 100,
        "presentation": {"type": "line"},
    }


@pytest.mark.parametrize(
    "values,kind,arrow_type,expected",
    [
        (["2024-02-29", "", "2025-01-01"], "date", pa.date32(), ["2024-02-29", None, "2025-01-01"]),
        (
            ["2025-01-01T12:30:00.123456", "2025-01-01 12:30", ""],
            "timestamp",
            pa.timestamp("us"),
            ["2025-01-01T12:30:00.123456", "2025-01-01T12:30:00", None],
        ),
        (
            ["2025-01-01T01:00:00+02:00", "2024-12-31T23:00:00Z", ""],
            "timestamp_tz",
            pa.timestamp("us", tz="UTC"),
            ["2024-12-31T23:00:00+00:00"] * 2 + [None],
        ),
    ],
)
def test_typed_parquet_and_json_preview(tmp_path, values, kind, arrow_type, expected):
    result, parquet = profile(tmp_path, values)
    assert result["schema_json"]["columns"][0]["inferred_type"] == kind
    assert pq.read_schema(parquet).field("when").type == arrow_type
    assert [row["when"] for row in result["preview_json"]] == expected
    assert result["profile_json"]["columns"][0]["null_count"] == 1
    assert result["profile_json"]["profiler_version"] == "csv-v3"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    "values",
    [
        ["01/02/2025", "02/03/2025"],
        ["2025-02-29", "2024-02-29"],
        ["2025-01-01", "not a date"],
        ["2025-01-01", "2025-01-01T00:00:00"],
        ["2025-01-01T00:00:00", "2025-01-01T00:00:00Z"],
        ["2025-01-01T24:00:00"],
        ["2025-01-01T00:00:60Z"],
        ["2025-01-01T00:00:00+00:99"],
        ["2025-01-01T00:00:00-00:00"],
        ["2025-01-01T00:00:00.123456789Z"],
        ["2025-01-01T00:00:00 PST"],
    ],
)
def test_ambiguous_invalid_or_lossy_dates_stay_text(tmp_path, values):
    result, parquet = profile(tmp_path, values)
    assert result["schema_json"]["columns"][0]["inferred_type"] == "string"
    assert pq.read_table(parquet).column("when").to_pylist() == values


def test_numeric_dates_not_guessed_and_all_null_unknown(tmp_path):
    result, _ = profile(tmp_path, ["20250101", "20250102"])
    assert result["schema_json"]["columns"][0]["inferred_type"] == "integer"
    result, _ = profile(tmp_path, ["", ""])
    assert result["schema_json"]["columns"][0]["inferred_type"] == "unknown"


@pytest.mark.parametrize(
    "values,expected,kind",
    [
        (
            ["2025-01-01", "2025-01-03", "2025-01-01"],
            [["2025-01-01", 2], ["2025-01-03", 1]],
            "date",
        ),
        (
            ["2025-01-01T12:00:00", "2025-01-01T13:00:00", "2025-01-01T12:00:00"],
            [["2025-01-01T12:00:00", 2], ["2025-01-01T13:00:00", 1]],
            "timestamp",
        ),
        (
            ["2025-01-01T01:00:00+02:00", "2024-12-31T23:00:00Z", "2025-01-02T23:00:00Z"],
            [["2024-12-31T23:00:00+00:00", 2], ["2025-01-02T23:00:00+00:00", 1]],
            "timestamp_tz",
        ),
    ],
)
def test_csv_to_execution_grouping_keeps_gaps(tmp_path, values, expected, kind):
    result, parquet = profile(tmp_path, values)
    catalog = catalog_from_profile(result["schema_json"])
    executed = execute_plan(
        query(), parquet_path=parquet, dataset_version_id="temporal-v1", columns=catalog
    )
    assert executed.status == "succeeded", executed
    assert executed.table.rows == expected
    assert executed.table.columns[0].logical_type == kind


@pytest.mark.parametrize(
    "values,bound,expected",
    [
        (
            ["2025-01-01T11:00:00", "2025-01-01T12:00:00"],
            "2025-01-01T12:00:00",
            [["2025-01-01T12:00:00", 1]],
        ),
        (
            ["2025-01-01T11:00:00Z", "2025-01-01T12:00:00Z"],
            "2025-01-01T14:00:00+02:00",
            [["2025-01-01T12:00:00+00:00", 1]],
        ),
    ],
)
def test_timestamp_filters_are_typed(tmp_path, values, bound, expected):
    result, parquet = profile(tmp_path, values)
    payload = query() | {"filters": [{"column": "when", "op": "gte", "value": bound}]}
    executed = execute_plan(
        payload,
        parquet_path=parquet,
        dataset_version_id="typed-filter",
        columns=catalog_from_profile(result["schema_json"]),
    )
    assert executed.status == "succeeded", executed
    assert executed.table.rows == expected


@pytest.mark.parametrize(
    "kind,value",
    [
        ("date", "2025-01-01T00:00:00"),
        ("timestamp", "2025-01-01"),
        ("timestamp", "2025-01-01T00:00:00Z"),
        ("timestamp_tz", "2025-01-01T00:00:00"),
        ("timestamp_tz", "2025-01-01T00:00:00.1234567Z"),
    ],
)
def test_filter_requires_matching_temporal_kind(kind, value):
    payload = query() | {"filters": [{"column": "when", "op": "eq", "value": value}]}
    with pytest.raises(PlanError):
        validate_plan(payload, {"when": kind, "revenue": "integer"})


def test_timestamp_min_max(tmp_path):
    result, parquet = profile(
        tmp_path, ["2025-01-01T12:00:00.123456Z", "2025-01-01T12:00:00.123455Z"]
    )
    payload = query() | {
        "dimensions": [],
        "metrics": [
            {"op": "min", "column": "when", "alias": "first"},
            {"op": "max", "column": "when", "alias": "last"},
        ],
        "presentation": {"type": "table"},
    }
    executed = execute_plan(
        payload,
        parquet_path=parquet,
        dataset_version_id="minmax",
        columns=catalog_from_profile(result["schema_json"]),
    )
    assert executed.status == "succeeded", executed
    assert executed.table.rows == [
        ["2025-01-01T12:00:00.123455+00:00", "2025-01-01T12:00:00.123456+00:00"]
    ]
