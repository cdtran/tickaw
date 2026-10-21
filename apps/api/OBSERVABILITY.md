# Observability

The API and workers emit versioned JSON events to stderr through the `tickaw.events` logger. These events provide operational visibility without logging questions, spreadsheet contents, column names, filenames, email addresses, cookies, authorization codes, model payloads, SQL, or raw exception messages/tracebacks. They are ready for a future container log collector; no external telemetry service is configured.

## What is recorded

| Event | Meaning |
| --- | --- |
| `http.completed` | Method, allowlisted route template, status, duration, and generated request ID. No URL query or headers. |
| `analysis.enqueued` | Publication success/failure for a committed run; database recovery still covers missed deliveries. |
| `analysis.state` | Committed lifecycle state, stage, attempt count, safe failure code, elapsed time, and retry delay when scheduled. |
| `analysis.stage` | Committed plan/download/execution progress. |
| `model.completed` | One provider response, duration, generation attempt, model route, prompt version, and reported tokens. Includes rejected responses. |
| `model.failed` | Provider failure or local paid-policy block, with attempt/duration. No exception contents. |
| `plan.rejected` | Allowlisted validator or semantic rejection code. No diagnostic messages or column/value details. |
| `plan.accepted` | Validated plan; `correction=true` when the second generation succeeded. |
| `execution.completed` | Successful execution duration from the executor's metadata. |
| `operation.failed` | Safe operational category, e.g. storage/lease/queue; HTTP failures can include an allowlisted exception type. |
| `profiling.started/completed/failed` | Profiling identity, attempts, and safe failure state/code. |

The allowlist lives in `app/core/observability.py`. Unknown error codes become `UNKNOWN`; new model IDs, routes, or codes must be reviewed and added there. Unknown fields are dropped, rather than serializing arbitrary objects. Logger failures do not change application success or retry behavior. This deliberately trades raw exception detail for privacy; use safe codes and targeted synthetic reproductions to investigate failures.

The API returns a generated UUID in `X-Request-ID`. A caller-supplied request ID is not trusted. Events emitted during that request inherit the ID through a context variable. API enqueue/state events connect that request to a `run_id`; worker events use the same run ID. Request IDs are not persisted as a distributed trace. Logs contain pseudonymous resource identifiers and remain access-controlled operational data.

`elapsed_ms` measures wall time since run creation, including queue time, retries, and any wait for clarification. `model.completed.duration_ms` measures the provider call; it excludes validation and includes no failed-call latency in the summary percentiles. `execution.completed.duration_ms` comes from the executor. These timings describe different parts of the workflow and should not be treated interchangeably.

## Read logs and summaries

```sh
docker --host unix:///Users/christran/.docker/run/docker.sock compose logs --since 1h --no-color --no-log-prefix api analysis-worker profiling-worker
```

For a summary that excludes unstructured lines and identifiers:

```sh
docker --host unix:///Users/christran/.docker/run/docker.sock compose logs --since 1h --no-color --no-log-prefix api analysis-worker profiling-worker 2>&1 | PYTHONPATH=.:apps/api .venv/bin/python -m app.scripts.summarize_events
```

The summary reports lifecycle event counts, rejection codes, first rejections requesting correction, successful corrections, model failures, known token totals, available response-cost estimates, and successful-response latency p50/p95. A first rejection with no later correction result may represent a failed correction, an interrupted run, or a log-window boundary. Counts describe the supplied log window; they are not a durable billing or audit ledger and are not automatically unique-user/run counts.

For example, `NEEDS_CLARIFICATION` events show clarification frequency over a consistent collection window. A high `MISSING_MEASURE` count identifies a data/semantic limitation. Many `MODEL_UNAVAILABLE` failures indicate provider availability or configuration problems. `POLICY_BLOCKED` identifies local paid-use restrictions separately. None of these events requires recording a user's question.

## Cost and retention

For successful OpenAI responses, `estimated_response_cost_usd` is calculated from reported input/output tokens and the explicitly configured `OPENAI_INPUT_RATE` and `OPENAI_OUTPUT_RATE` (USD per million tokens). It includes responses later rejected by validation. It is an estimate, not confirmed spend, and does not account for provider-side cache discounts or all billing adjustments. Errors may still incur charges without reporting usable tokens; unavailable usage/cost is omitted, never asserted to be zero. Local model compute costs are not estimated. A summary with no estimates returns `null` cost.

Conservative spend reservations and request limits remain enforced by the existing provider adapter. Response estimates are not reservations and must not be substituted for the spending controls. This change does not enable paid calls or make any live model requests.

Compose limits each API/worker container's JSON log files to 10 MB with three rotated files. Docker's log tail may not include all rotated records. Production collection, retention, access controls, alerts, and dashboards are follow-up deployment work. No public metrics endpoint or access to other users' analysis records has been added.

Raw Uvicorn access logging remains disabled because authentication callback URLs contain codes. Production proxies must also omit or redact query strings. The event allowlist applies to application events; platform/database/proxy logs require their own privacy configuration. It does not remove historical logs.

## Verification

Unit checks cover malicious telemetry fields, private HTTP query/header/path values, sanitized server errors, rejection/correction sequences, semantic safeguards, provider/policy failures, usage/cost handling, and summary parsing. The disposable database harness verifies lifecycle events are emitted only after the corresponding state is visible to another database session, and repeats the existing authentication and isolation checks. Tests use fake provider responses; no paid evaluation is needed.
