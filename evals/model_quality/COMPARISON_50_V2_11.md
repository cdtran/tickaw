# Generic-prompt 50-case comparison

Prompt `query-plan-v2.11`; suite `2026-09-30.3`. All responses fresh.

| Model | Overall | Answerable | Missing-data safety | Mean time/case |
| --- | --- | --- | --- | --- |
| Qwen3 8B | 39/50 | 32/40 | 7/10 | 11.25s |
| GPT-5.4 mini | 46/50 | 39/40 | 7/10 | 1.84s |

Mini estimated response cost: $0.051598. Conservative reservations: $0.266860; these are budget accounting, not invoice reconciliation.

The historical v2.10 comparison scored Qwen 43/50 and mini 47/50. That prompt included dataset-specific category examples and automatic equality-filter hints, removed in v2.11.

## Qwen3 8B failures

- `book-transaction-rows-per-day` (semantically_misleading_substitution): missing required filter {'column': 'category', 'op': 'eq', 'value': 'Books'}
- `average-book-revenue-per-day` (semantically_misleading_substitution): dimensions were [], expected ['date']; missing required filter {'column': 'category', 'op': 'eq', 'value': 'Books'}
- `revenue-by-category-and-date` (invalid_model_output): CHART_DIMENSION_COUNT; CHART_DIMENSION_COUNT
- `missing-revenue-rows` (semantically_misleading_substitution): dimensions were [], expected ['category']
- `active-records-by-category` (invalid_model_output): MISSING_REQUIRED_FILTER; MISSING_REQUIRED_FILTER
- `inactive-rows` (semantically_misleading_substitution): missing required filter {'column': 'active', 'op': 'eq', 'value': False}; unexpected number of metrics; unexpected number of filters
- `books-high-revenue` (semantically_misleading_substitution): missing required filter {'column': 'category', 'op': 'eq', 'value': 'Books'}; unexpected number of filters
- `inactive-games-known-revenue` (semantically_misleading_substitution): missing required filter {'column': 'category', 'op': 'eq', 'value': 'Games'}; missing required filter {'column': 'active', 'op': 'eq', 'value': False}; unexpected number of filters
- `missing-region` (semantically_misleading_substitution): used misleading substitute metric {'op': 'sum', 'column': 'revenue'}
- `missing-discount` (semantically_misleading_substitution): used misleading substitute metric {'op': 'avg', 'column': 'revenue'}
- `missing-inventory` (semantically_misleading_substitution): used misleading substitute metric {'op': 'sum', 'column': 'revenue'}

## GPT-5.4 mini failures

- `games-average-revenue` (semantically_misleading_substitution): dimensions were ['category'], expected []
- `missing-region` (semantically_misleading_substitution): used misleading substitute metric {'op': 'sum', 'column': 'revenue'}
- `missing-discount` (semantically_misleading_substitution): used misleading substitute metric {'op': 'avg', 'column': 'revenue'}
- `missing-inventory` (semantically_misleading_substitution): used misleading substitute metric {'op': 'sum', 'column': 'revenue'}

## Limits

- All 50 cases fresh for both models; zero cache hits.
- Same suite, scorer, planner validation, and semantic guards. No prompt or contract changes during run.
- Single-run end-to-end results, not raw model accuracy or a reliability estimate.
- Mean durations include token counting, correction attempts, and provider time. Models ran concurrently.
- Prior v2.10 comparison reused 20 cached mini responses and retried provider errors; historical score changes are descriptive, not causal estimates.
- Safety labels are scored by observed rejection action. Region, discount, and inventory remain gaps in existing guards.
