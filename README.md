# tickaw

An AI-assisted data-analysis application for asking questions about uploaded tabular data in notebook-style cells.

The product name is **tickaw** (lowercase). Its domain is **tickaw.com**; domain registration does not mean the application is deployed there. Use this name for new UI copy, documentation, and project metadata.

## Current functionality

- CSV uploads with independent datasets and immutable dataset versions.
- Background profiling into schema, samples, previews, and normalized Parquet.
- Persistent notebooks and question cells referencing an exact dataset version.

The v1 aggregate query-plan schema, SQLGlot compiler, and isolated local Parquet executor are implemented with typed JSON results and known-answer DuckDB tests. See the [execution walkthrough](docs/query-execution.md). Notebook job integration, production deployment, charts, and LLM integration are upcoming milestones. The analysis flow is LLM-generated JSON plans, deterministic validation, application-owned SQLGlot AST compilation, target SQL execution, and result checks. See the [query-plan design](docs/query-plan.md).

## Stack and layout

- `apps/web` — React, TypeScript, and Vite frontend
- `apps/api` — FastAPI API, SQLAlchemy models, Alembic migrations, and profiling worker
- `packages/data_engine` — ingestion and profiling with pandas
- `packages/llm_gateway` — scaffold for provider-neutral model integration
- `packages/charting` — scaffold for chart specifications
- `docker` — container build definitions
- `infra/terraform` — infrastructure scaffold for future AWS deployment
- `docs` — architecture, local development, and learning guides

Postgres stores metadata. MinIO stores original files and normalized Parquet locally;
S3 is planned for AWS. The profiling worker currently polls Postgres.

## Local development

For first-time setup, copy `.env.example` to `.env`; preserve an existing `.env`.
Then run:

```sh
docker compose build api profiling-worker
docker compose up -d api web
docker compose exec -T api alembic upgrade head
docker compose exec -T api python -m scripts.init_storage
docker compose up -d profiling-worker
```

Frontend: http://localhost:5173 · API docs: http://localhost:8000/docs ·
MinIO console: http://localhost:9001

The internal database name `data_notebook` and bucket name `data-notebook-dev`
are retained for compatibility with existing local data. They are resource
identifiers, not the product name; renaming them requires a separate data migration.

See the [local development guide](docs/local-development.md),
[implementation workbook](docs/implementation-workbook.md), and
[notebook foundation walkthrough](docs/notebook-foundation.md).
