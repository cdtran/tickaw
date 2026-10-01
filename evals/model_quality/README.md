# Model-quality evaluations

This corpus checks whether a generated query plan preserves the meaning of a question, in
addition to passing the query-plan validator. It is intentionally provider-neutral and uses
stable model IDs.

`cases.json` is the reviewed product contract. Each live case names its desired outcome and,
for answerable questions, the dimensions, metrics, and filters that must appear. Forbidden
metrics identify tempting but misleading substitutions. The classification fixtures keep
malformed output and semantically valid-but-wrong plans represented without relying on a
live model to produce them.

Run the deterministic corpus checks with the unit suite:

```sh
PYTHONPATH=. uv run --extra dev pytest tests/unit/test_model_quality_evals.py
```

Run all questions against the configured model:

```sh
docker compose run --rm api python -m evals.model_quality.run --model qwen-local
```

Use repeatable `--case` arguments for a targeted, lower-cost run:

```sh
docker compose run --rm api python -m evals.model_quality.run \
  --case average-books-sold-per-day \
  --case revenue-by-category-and-date
```

The runner emits one JSON line per case and exits nonzero if the observed outcome or action
fails the reviewed contract. Missing-measure and semantic safety rejections report
`actual: safe_rejection` and `observed_action: request_clarification`, independently of the
expected outcome label. Safety cases explicitly specify `expected_action`; their pass status
checks that action and `scoring_basis` is `action`. `outcome_label_match` is null for safety
rejections because clarification versus unanswerable is not independently predicted.
A passing safety case establishes rejection behavior, not outcome-label accuracy. A live failure is a regression signal or a known gap to investigate;
do not weaken an expectation merely to make a model pass. Pin model and prompt versions in
saved CI artifacts when comparing changes over time.

Cases carry explicit tier tags: `full` covers all 50; `smoke` covers seven high-value
aggregation, filtering, ranking, and missing-measure checks. Run smoke after prompt or
planner edits with `--tier smoke`. `release` is reserved for explicitly tagged future cases;
an empty selection fails rather than silently passing. Repeatable `--case` overrides tier
selection.

Revision `2026-09-30.3` adds 30 cases covering numeric and date boundaries,
combined predicates, false versus null booleans, missing values, leading-zero text
codes, multiple metrics, ranking by a specified metric, explicit charts, and absent
region, discount, and inventory fields. These cases retain the synthetic demo schema;
they broaden question coverage, not dataset/domain coverage. The previous 20/20 live
result applies to revision `.2`, not this expanded corpus.

New answerable contracts use `exact_metrics` and `exact_filters` to reject extra
operations or predicates. A redundant `is_not_null` predicate on a column already
constrained by a comparison is allowed because comparisons exclude SQL nulls.
Ordering contracts may name a `metric` by operation and
column, resolving its generated alias rather than requiring a particular alias spelling.
Each new answerable case has a deterministic valid-plan fixture proving that the
contract is representable. These fixtures verify the scorer, not live model accuracy.

Reports default to `artifacts/model-quality/latest.json`; override with `--report`.
Each record includes model/provider IDs, prompt and suite versions, attempts, token usage,
duration, outcome, and an initial failure category. Reports contain no questions, dataset
profiles, model payloads, or raw provider errors. Scoring reasons refer only to synthetic
case contracts. Provider failures are reported separately from invalid plans. Manual review
must distinguish `model_failure`, `evaluation_expectation`, `unsupported_product_capability`,
and `provider_runtime_failure`; automatic categories are provisional.

Successful provider responses (including plans subsequently rejected by validation) are
cached under `artifacts/model-quality/cache`. Provider exceptions are never cached. Keys
include the case, schema/profile, request and correction feedback, model IDs, provider and
endpoint, prompt version/text, response schema, and adapter parameters. Update the parameter
fingerprint in `recording.py` when adapter generation settings change. Use `--refresh` to
replace entries or `--no-cache` to bypass caching. Cache files contain model payloads and are
local evaluation artifacts, not shareable reports. Do not use private datasets in this
synthetic corpus. Caches do not identify changed weights behind the same provider model ID;
refresh after a model-server update.

Token counts include cached response usage; cache hits are reported separately. Missing
usage remains null. Optional `--input-rate` and `--output-rate` specify USD per million tokens
for an estimated response cost (including cached responses), not an invoice or fresh-run
spend. Unknown prices remain null. The optional OpenAI route below requires explicit prices.

Persist Docker artifacts on the host:

```sh
docker compose run --rm -v "$PWD/artifacts/model-quality:/eval-artifacts" api \
  python -m evals.model_quality.run --model qwen-local --tier full --refresh \
  --report /eval-artifacts/baseline.json --cache-dir /eval-artifacts/cache
```

Prompt `query-plan-v2.11` removes the dataset-specific category example and all
question-to-value filter injection from `.10`. It uses generic interpretation rules
and passes the question, schema, and profile as evidence. Temporal chart eligibility
is derived only from schema types. Prior live scores used `.10`; they do not measure
this generic prompt. The version change invalidates cached responses for new runs.

## Optional OpenAI route

Set `OPENAI_MODEL` to an explicit Responses API model ID, set `OPENAI_API_KEY`, and
add `openai-analysis` to `LLM_ENABLED_MODELS`. Qwen remains the default. No model or
price is guessed. Check current prices for your model before supplying rates.

Evaluations require per-invocation opt-in, even if `OPENAI_ALLOW_PAID` is enabled for
application workers. For example, with your reviewed rates in shell variables:

```sh
docker compose run --rm api python -m evals.model_quality.run \
  --model openai-analysis --case total-revenue --allow-paid \
  --max-cost-usd 0.10 --max-requests 2 --max-output-tokens 1024 \
  --input-rate "$INPUT_USD_PER_MILLION" --output-rate "$OUTPUT_USD_PER_MILLION"
```

Without opt-in, valid cache hits can still be scored; cache misses report
`paid_run_blocked` without contacting OpenAI. Corrections consume the same request
and dollar limits. The adapter counts input tokens with the official token-count
endpoint, then reserves input cost plus the full output-token allowance before
sending generation. It sends no automatic retries, uses `store: false`, and rejects
refused, incomplete, or malformed responses. Query plans still pass all existing
structural and semantic checks. Discriminated unions are translated to `anyOf` in
the provider schema without weakening local validation.

The summary's `paid_run` reports generation requests and reserved cost separately
from cached response cost. Reservations are retained after success and errors,
including timeouts, because a failed request may have incurred a charge. These
are conservative controls at **your supplied prices**, not invoice reconciliation.
They apply to one evaluation run or one application process, reset on restart, and
are not a shared account limit across workers. For application use, explicitly set
`OPENAI_ALLOW_PAID=true`, the budget, request cap, and both rates; exhausted limits
require a new process. Keep paid application use disabled unless that scope is
appropriate. Token-count failures block generation.

API contracts: [Responses](https://developers.openai.com/api/reference/python/resources/responses/methods/create)
and [token counting](https://developers.openai.com/api/docs/guides/token-counting).
