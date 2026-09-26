"""Run one known-answer example through the real Parquet execution boundary.

From repository root: python -m examples.query_plans.run_example top_region
"""

import argparse
import json
import tempfile
from pathlib import Path

import duckdb

from packages.data_engine.execution import execute_plan


def main():
    root = Path(__file__).resolve().parent
    cases = {path.name.removesuffix(".case.json"): path for path in root.glob("*.case.json")}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=sorted(cases), default="revenue_by_region", nargs="?")
    args = parser.parse_args()
    case = json.loads(cases[args.case].read_text())
    fixture = json.loads((root / case["fixture"]).read_text())
    with tempfile.TemporaryDirectory(prefix="tickaw-example-") as directory:
        path = Path(directory) / "fixture.parquet"
        with duckdb.connect() as connection:
            connection.execute(
                "CREATE TABLE fixture(region VARCHAR, product VARCHAR, revenue DOUBLE, "
                "sold_on DATE, refunded BOOLEAN)"
            )
            connection.executemany("INSERT INTO fixture VALUES (?, ?, ?, ?, ?)", fixture["rows"])
            connection.execute("COPY fixture TO ? (FORMAT PARQUET)", [str(path)])
        result = execute_plan(
            case["plan"],
            parquet_path=path,
            dataset_version_id="example-sales-v1",
            columns=fixture["columns"],
        )
    print(result.model_dump_json(indent=2))
    if result.status == "failed":
        raise SystemExit(1)
    if result.table.rows != case["expected_rows"]:
        raise SystemExit("Executed result differs from the independently expected answer")


if __name__ == "__main__":
    main()
