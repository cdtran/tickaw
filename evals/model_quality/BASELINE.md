# Qwen baseline — September 30, 2026

Full synthetic corpus: **17/20 passed (85%)**. Model ID `qwen-local`, provider
`ollama`, provider model `qwen3:8b`, prompt `query-plan-v2.8`, suite format version 1,
revision `2026-09-30.1`. One fresh run, no cache hits. There were 24 requests,
11,041 input tokens, 1,483 output tokens, and 240.55 seconds of provider/cache time.
Cost is unpriced (local provider). Raw metadata is saved locally in
`artifacts/model-quality/baseline.json`; cached responses are intentionally ignored by Git.

Every failure was reviewed against the question, synthetic schema/profile, required
contract, and cached plan:

| Case | Classification | Evidence and decision |
| --- | --- | --- |
| `book-transaction-rows-per-day` | Genuine model failure | Daily row count omitted `category = Books`, counting all categories. The dataset supplies Books as a category sample. Keep the required filter. |
| `average-book-revenue-per-day` | Genuine model failure | Daily average revenue omitted `category = Books`. Grouped average and category filtering are supported. Keep the required filter. |
| `active-records-by-category` | Genuine model failure | Used `count_non_null(active)` with no filter. Both true and false values are non-null; the question requires row count with `active = true`. Keep both requirements. |

No failed case was caused by an overly strict expectation, unsupported product capability,
or provider/runtime error. No expectations or planner prompts were weakened or changed.
Prioritize prompt evidence for singular “book” category references and Boolean record
counts, then rerun smoke with `--refresh` to measure improvements.

The seven-case smoke subset passed 4/7. Successful coverage includes scalar/grouped revenue,
explicit category-value filters, null filtering, non-null counts, ranking, temporal minimum,
and conservative missing-measure rejection.

Interpretation limits: these are end-to-end planner/validator/semantic-guard results, not
raw model accuracy. Missing-measure cases pass when the existing product safety path blocks
them. The existing runner maps that safety path to the case's reviewed clarification versus
unanswerable label; those two labels are not independently predicted by the product. A
future evaluation should assert the observed safety action separately. One deterministic
local run establishes a reference, not a statistical reliability estimate. The cache uses
model names rather than weight digests; refresh when local model weights change.

Full cache replay reproduced all 20 outcomes with 24 cache hits and zero fresh requests.
