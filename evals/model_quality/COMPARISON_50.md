# 50-case comparison — September 30, 2026

Suite 2026-09-30.3; prompt query-plan-v2.10.

| Model | Overall | Answerable | Missing-data safety | Mean time/new case |
| --- | --- | --- | --- | --- |
| Qwen3 8B | 43/50 | 36/40 | 7/10 | 14.57s |
| GPT-5.4 mini | 47/50 | 40/40 | 7/10 | 1.87s |

Mini estimated successful new-response cost: $0.032248; conservative reservations for this comparison: $0.197578. Neither is invoice reconciliation.

## Qwen3 8B failures

- `missing-revenue-rows`: missing required filter {'column': 'revenue', 'op': 'is_null'}
- `books-total-revenue`: dimensions were ['category'], expected []
- `games-average-revenue`: dimensions were ['category'], expected []
- `exclude-books`: missing required filter {'column': 'category', 'op': 'ne', 'value': 'Books'}
- `missing-region`: used misleading substitute metric {'op': 'sum', 'column': 'revenue'}
- `missing-discount`: used misleading substitute metric {'op': 'avg', 'column': 'revenue'}
- `missing-inventory`: used misleading substitute metric {'op': 'sum', 'column': 'revenue'}

## GPT-5.4 mini failures

- `missing-region`: used misleading substitute metric {'op': 'sum', 'column': 'revenue'}
- `missing-discount`: used misleading substitute metric {'op': 'avg', 'column': 'revenue'}
- `missing-inventory`: used misleading substitute metric {'op': 'sum', 'column': 'revenue'}

## Interpretation

- Single end-to-end planner/validator/guard run, not a reliability estimate.
- Mini reused 20 older responses; Qwen made fresh requests for all 50. Latency compares the 30 new cases, including correction time and token counting; excludes failed initial mini provider calls.
- Six mini provider failures were retried successfully; reservations retain their possible cost.
- A redundant non-null check on an already compared column was accepted by the corrected scorer for both models.
- Missing-data safety pass establishes rejection action, not independent outcome-label classification.

The semantic guard has no concept rules for region, discount, or inventory. Review these as shared product safety gaps as well as model behavior. No planner prompt or product guard was changed during this comparison.

The current prompt also requires an equality filter whenever a sample value is mentioned, conflicting with exclusion questions. Qwen failed `exclude-books` under that shared prompt; mini preserved the requested exclusion. Scalar-shape failures are scored against the existing contract even when filtering to one category can produce a numerically equivalent grouped result.
