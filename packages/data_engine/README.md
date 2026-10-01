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

See the [query-plan examples](../../examples/query_plans/README.md) for runnable
execution examples and checks. [Execution policies](execution.py) define resource
limits, and [result types](result_types.py) define the serialization contract.

`PlanError` exposes stable codes and structured facts for unknown columns, metric and
filter type mismatches, temporal/timezone mismatches, unsupported Boolean comparisons,
duplicate dimensions/aliases/order fields, alias collisions, invalid ordering references,
and chart dimension/metric constraints. The API bounds diagnostic strings and lists and
preserves numeric counts; filter values and rejected plan payloads are not retained.
Structurally malformed JSON remains a bounded `MALFORMED_PLAN` diagnostic.

`question_semantics.py` rejects explicit substitutions for recognized business measures.
The model-quality baseline also supports a narrow active-record count check: with a
Boolean `active` field, explicit “count active records” and “how many active records”
requests require row count and `active = true` (or `active != false`). This check accepts
an optional grouping phrase naming a catalog column and abstains on broader wording,
non-Boolean schemas, and resumed clarification answers. It does not infer arbitrary
category filters or singular/plural category names. Semantic failures receive the same
single correction attempt as validator failures before execution is refused.
