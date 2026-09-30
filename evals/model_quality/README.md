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

The runner emits one JSON line per case and exits nonzero if actual outcomes differ from the
reviewed expectations. A live failure is a regression signal or a known gap to investigate;
do not weaken an expectation merely to make a model pass. Pin model and prompt versions in
saved CI artifacts when comparing changes over time.
