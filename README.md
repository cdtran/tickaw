# tickaw

**tickaw** is a notebook-style data-analysis application for asking natural-language
questions about uploaded tabular data. A model translates each question into a constrained
JSON query plan; tickaw validates the plan, compiles application-owned SQL, executes it in a
bounded DuckDB child process, and renders the persisted table and chart.

The product name is **tickaw** (lowercase). Its domain is **tickaw.com**, but the application
is not currently deployed there.

## Current functionality

- CSV uploads with independent datasets and immutable dataset versions.
- Background profiling, previews, schema inference, and normalized Parquet snapshots.
- Persistent notebooks whose question cells pin an exact dataset version and model ID.
- User-selectable model routing through a provider-neutral LLM gateway.
- Local Qwen 3 support through Ollama's native API with thinking disabled for fast,
  structured planning.
- Versioned query-plan JSON, semantic validation, and SQLGlot AST compilation.
- Resource-bounded DuckDB execution against immutable Parquet snapshots.
- Durable analysis results, integrity hashes, safe failure records, and frontend polling.
- Automatic table, bar-chart, and temporal line-chart rendering.
- Redis Stream analysis queue with consumer acknowledgments and a PostgreSQL recovery
  scan for missed deliveries or abandoned work.

## Analysis lifecycle

Question submission inserts the notebook cell and its analysis run in one transaction. The
API returns immediately; it does not wait for the model or DuckDB.

```text
Browser
  │ POST question
  ▼
FastAPI ── one transaction ──► notebook_cells + analysis_runs (QUEUED)
                                      │
                                      │ Redis Stream message
                                      ▼
                               analysis worker
                                      │
                 GENERATING_PLAN ─────┤ Qwen/Ollama
                 DOWNLOADING_DATA ────┤ MinIO/S3 Parquet
                 EXECUTING ───────────┤ bounded DuckDB child
                                      ▼
                              COMPLETED or FAILED
                                      │
                                      ▼
                         persisted chart and table
```

PostgreSQL is the source of truth for each run. The API publishes its committed run ID to a
Redis Stream; the worker acknowledges it after the database run reaches a terminal state.
The worker also scans PostgreSQL every 30 seconds so a broker outage between database commit
and publish cannot lose a run. One analysis-worker process handles all analysis stages; the
stage names are progress states, not separate services.

## Stack and layout

- `apps/web` — React, TypeScript, Vite, and Recharts frontend
- `apps/api` — FastAPI, SQLAlchemy, Alembic, and background workers
- `packages/data_engine` — profiling, query-plan validation, SQL compilation, and execution
- `packages/llm_gateway` — model registry, versioned prompts, and provider adapters
- `packages/charting` — deterministic persisted chart specifications
- `docker` — local container build definitions
- `infra/terraform` — future AWS deployment scaffold
- `evals/model_quality` — model-quality cases, scoring, and live evaluation runner
- `examples/query_plans` — query-plan fixtures and runnable execution examples

The local stack runs the API, web development server, profiling worker, analysis worker,
PostgreSQL, MinIO, and Redis in Docker. Redis stores the analysis queue with append-only
persistence enabled locally. Ollama runs on the host machine.

The API and both workers can initially run as containers on one application host; they do
not require separate physical servers. PostgreSQL, S3-compatible storage, and the model
provider can later be managed services.

## Authentication

Google sign-in through Cognito uses backend-managed, revocable cookie sessions and per-user dataset/notebook ownership. Provider setup is required; anonymous data access is disabled. See the [authentication walkthrough](apps/api/AUTHENTICATION.md) for the flow, setup, legacy-data migration, and validation.

## Local development

### Prerequisites

- Docker with Compose
- Ollama
- Enough memory to run `qwen3:8b` (the default local model is approximately 5 GB)

Copy the environment template without replacing an existing local file:

```sh
cp -n .env.example .env
```

Install the local model and ensure Ollama is running:

```sh
ollama pull qwen3:8b
ollama serve
```

On systems where Ollama already runs as a background service, `ollama serve` is unnecessary.

Start the stateful services and application containers, apply migrations, initialize object
storage, and then start the workers:

```sh
docker compose up -d --build postgres redis minio api web
docker compose exec -T api alembic upgrade head
docker compose exec -T api python -m scripts.init_storage
docker compose up -d profiling-worker analysis-worker
```

Open:

- Web application: http://localhost:5173
- API documentation: http://localhost:8000/docs
- MinIO console: http://localhost:9001

The internal database name `data_notebook` and bucket name `data-notebook-dev` are retained
for compatibility with existing local data. They are resource identifiers, not the product
name; changing them requires a data migration.

## Model configuration

The UI and persisted cells use stable product-owned model IDs rather than raw provider model
names. The default route is:

```text
qwen-local → native Ollama adapter → qwen3:8b
```

Relevant `.env` settings:

```dotenv
LLM_DEFAULT_MODEL=qwen-local
LLM_ENABLED_MODELS=qwen-local
QWEN_BASE_URL=http://host.docker.internal:11434/v1
QWEN_MODEL=qwen3:8b
QWEN_TIMEOUT_SECONDS=120
```

The native Ollama adapter removes the `/v1` suffix internally and calls `/api/chat` with
`think: false`. Provider-specific controls stay inside their adapter; shared prompts and the
rest of the application remain model-agnostic. API-key-backed models can be added as new
registry routes and adapters without changing notebook or analysis-run contracts.

## Analysis safety properties

- The model never emits executable SQL; it returns a constrained JSON plan.
- Column names and operations are validated against the pinned server-owned schema.
- SQL is built as a SQLGlot AST and targets only the registered `dataset` relation.
- The execution child has time, memory, row, cell, source-size, and result-size bounds.
- Workers download only the immutable normalized object belonging to the pinned version.
- Plans become immutable once assigned, and terminal runs are immutable.
- Active analysis runs hold 30-second database leases renewed by 10-second heartbeats;
  another worker reclaims only an expired lease.
- Transient model and storage failures retry at most three total attempts with persisted
  exponential backoff. Permanent validation and source errors fail immediately.
- Question submissions carry durable idempotency keys, so replaying a request after a lost
  response returns the original cell and run instead of creating duplicate work.
- Notebook progress shows elapsed time, execution stage, attempt count, and retry countdown;
  terminal failures can be retried as a new auditable run on the same question cell.
- Result artifacts include dataset and plan fingerprints.
- Temporal line charts are emitted only when profiled samples and returned x-axis values are
  uniformly valid ISO dates or timestamps.

See the [data engine](packages/data_engine/README.md) and
[runnable query-plan examples](examples/query_plans/README.md) for more detail.

## Verification

Run the Python unit suite and frontend production build:

```sh
PYTHONPATH=. uv run --extra dev pytest tests/unit
npm --prefix apps/web run build
```

Run the live, provider-neutral model-quality corpus separately (it requires the configured
model server and intentionally fails when a known semantic gap is observed):

```sh
docker compose run --rm api python -m evals.model_quality.run --model qwen-local
```

See [model-quality evaluations](evals/model_quality/README.md) for the case contract and
scoring rules.

Run the disposable database, migration, API, profiling, and analysis integration harness:

```sh
docker compose exec -T api python -m tests.check_migrations
```

The migration harness creates and removes its own temporary PostgreSQL database. It verifies
fresh upgrades, schema agreement, downgrade/re-upgrade behavior, queue insertion,
database constraints, and durable result persistence.

## Next priorities

- Expand model-quality evaluations with representative questions and expected query plans.
- Add an API-key-backed model route while preserving the stable model-selection contract.
- Remove unused Celery scaffolding if analysis continues to use Redis Streams directly.
- Complete production deployment, observability, and worker-concurrency configuration.

Additional guides:

- [API and workers](apps/api/README.md)
- [Web frontend](apps/web/README.md)
- [LLM gateway](packages/llm_gateway/README.md)
- [Terraform deployment scaffold](infra/terraform/README.md)
