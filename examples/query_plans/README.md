# Query-plan v1 examples

`query-plan.schema.json` is generated from `QueryPlan.model_json_schema()` in
`packages/data_engine/query_plan.py`. The Pydantic types are the source of truth.
This is a provider-neutral validation schema; provider adapters may need to lower
its discriminated unions to the provider's supported structured-output subset.

Each `*.case.json` contains:

- `case_version`, `id`, and `fixture`: evaluation identity and input dataset.
- `questions`: equivalent question phrasings for future planner evals.
- `plan`: the exact JSON object the model should produce.
- `expected_columns` and `expected_rows`: independently calculated answers.

Only `plan` is model output. Expected results and fixture metadata are test-owned.
Tests currently execute the hand-written plans; they do not call or evaluate an LLM.
The fixture is small on purpose: group sizes, nulls, ties, and a year boundary expose
wrong aggregates, grouping keys, filters, and tie behavior.

For example, inspect `revenue_by_region.case.json`, then compare
`average_by_region.case.json` and `revenue_by_product.case.json`.

## Compile a plan

From the repository root in a Python 3.12+ environment with project dependencies:

```python
import json
from pathlib import Path
from packages.data_engine.query_compiler import build_ast, compile_sql

root = Path("examples/query_plans")
case = json.loads((root / "revenue_by_region.case.json").read_text())
fixture = json.loads((root / "sales.fixture.json").read_text())

ast = build_ast(case["plan"], fixture["columns"])
print(ast.dump())
print(compile_sql(case["plan"], fixture["columns"]))
```

The compiler builds expression objects directly. It does not parse SQL strings
supplied by the model. It targets a fixed quoted relation named `dataset`; a future
execution adapter will register the question's pinned dataset under that name.
Values are typed AST literals rendered by SQLGlot, not interpolated SQL fragments.
The [Parquet executor](../../docs/query-execution.md) now runs these plans in a bounded child process. Notebook/storage orchestration is still pending.

## Run the checks

Install the versions declared in `pyproject.toml` (including dev dependencies), then:

```sh
python -m pytest tests/unit/test_query_plans.py -q
```

DuckDB is a runtime dependency for the Parquet executor. Notebook execution is not
wired up yet. SQLGlot and DuckDB are pinned because compiler/engine behavior is versioned.

To regenerate the schema after an intentional contract change:

```sh
python -c 'import json; from pathlib import Path; from packages.data_engine.query_plan import QueryPlan; Path("examples/query_plans/query-plan.schema.json").write_text(json.dumps(QueryPlan.model_json_schema(), indent=2) + "\n")'
```

A schema drift test ensures the committed artifact matches the Python contract.


## Execute and return structured JSON

```sh
python -m examples.query_plans.run_example revenue_by_region
python -m examples.query_plans.run_example top_region
```

The demo writes the fixture to Parquet, runs the real subprocess executor, prints
the structured result, and compares rows with the independent expected answer.
See `execution-result.schema.json` for the versioned success/failure contract.
