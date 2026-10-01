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

## Follow-up: active-record semantic guard

The narrow active-record rule rejected the cached `count_non_null(active)` plan. The
existing single correction attempt then produced a valid row count with an active filter.
The targeted case passed using one cache hit and one fresh Qwen request (prompt version
unchanged). Metadata is saved locally in `artifacts/model-quality/active-guard.json`.
This demonstrates correction for the observed failure; the original 17/20 baseline above
remains the historical reference, and no new full-suite pass rate is claimed.

## Follow-up: Books filters and independent safety actions

A prose-only prompt (`query-plan-v2.9`) still missed both Books filters in fresh targeted
responses. Prompt `query-plan-v2.10` adds explicit value-filter hints, including the narrow
whole-word `book` to sampled `category = Books` mapping. Both Books regressions then passed
on the first attempt. No semantic category-matching rule was added.

Five fresh targeted cases passed: both Books regressions, average books sold, quantity
language without quantity, and total revenue. The two missing-measure cases asserted the
observed `request_clarification` action and reported `safe_rejection` with a null
`outcome_label_match`; they did not establish clarification versus unanswerable accuracy.
The safety action contract is now separate from the preserved expected outcome labels.
Metadata is saved locally in `artifacts/model-quality/books-safety-v2.10.json`.
All 164 Python unit tests passed. The historical full baseline remains 17/20; this targeted
five-case run does not establish a new full-suite rate.
