# Data engine

CSV profiling, strict query plans, SQLGlot compilation, and structured execution
results live here. No model-generated Python or raw SQL is accepted for execution.

- `query_plan.py`: structural and semantic validation.
- `query_compiler.py`: trusted JSON-to-AST mapping.
- `execution.py`: server-facing `execute_plan`, policy, and profile catalog adapter.
- `execution_child.py`: private Parquet/DuckDB subprocess.
- `result_types.py`: versioned success/failure and table contracts.

See [query execution](../../docs/query-execution.md) for a runnable example,
serialization rules, resource limits, tests, and production isolation requirements.
