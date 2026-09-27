# Data engine

CSV profiling, strict query plans, SQLGlot compilation, and structured execution
results live here. No model-generated Python or raw SQL is accepted for execution.

CSV profiling conservatively recognizes ISO dates and timestamps. Offset-aware
timestamps normalize to UTC, while naive timestamps remain naive. Profiling does
not create rows for missing time periods; a future explicit query-plan operation
will control whether a time series fills gaps with zeroes.

- `query_plan.py`: structural and semantic validation.
- `query_compiler.py`: trusted JSON-to-AST mapping.
- `execution.py`: server-facing `execute_plan`, policy, and profile catalog adapter.
- `execution_child.py`: private Parquet/DuckDB subprocess.
- `result_types.py`: versioned success/failure and table contracts.

See [query execution](../../docs/query-execution.md) for a runnable example,
serialization rules, resource limits, tests, and production isolation requirements.
