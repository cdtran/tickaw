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

The runner emits one JSON line per case and exits nonzero if actual outcomes differ from the
reviewed expectations. A live failure is a regression signal or a known gap to investigate;
do not weaken an expectation merely to make a model pass. Pin model and prompt versions in
saved CI artifacts when comparing changes over time.

Cases carry explicit tier tags: `full` covers all 20; `smoke` covers seven high-value
aggregation, filtering, ranking, and missing-measure checks. Run smoke after prompt or
planner edits with `--tier smoke`. `release` is reserved for explicitly tagged future cases;
an empty selection fails rather than silently passing. Repeatable `--case` overrides tier
selection.

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
spend. Unknown prices remain null. No paid providers are currently configured.

Persist Docker artifacts on the host:

```sh
docker compose run --rm -v "$PWD/artifacts/model-quality:/eval-artifacts" api \
  python -m evals.model_quality.run --model qwen-local --tier full --refresh \
  --report /eval-artifacts/baseline.json --cache-dir /eval-artifacts/cache
```
