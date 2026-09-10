# Data Notebook

An AI-assisted data-analysis application. Users upload CSV or Excel workbooks, ask questions in notebook-style cells, choose an analysis model, and receive reproducible tables and charts.

This repository is intentionally a **scaffold only**. No upload, LLM, data-processing, execution, database, or UI behavior has been implemented.

## Recommended stack

| Concern | Choice | Why |
| --- | --- | --- |
| Web app | React + TypeScript + Vite | Lightweight, fast development, strong chart/component ecosystem |
| API | FastAPI + Pydantic | Python-native, typed contracts, async-ready |
| Analysis | pandas (later Polars option) | Matches the planned code-generation workflow |
| Database | PostgreSQL | Durable metadata, conversations, jobs, and audit records |
| File storage | Amazon S3 | Scalable storage for source files and generated artifacts |
| Background jobs | Celery + Redis (or SQS in AWS) | Keeps long analysis runs out of request handlers |
| Execution | Isolated container/job | Essential boundary for LLM-generated Python |
| Deployment | ECS Fargate + RDS + S3 | Managed AWS path without Kubernetes overhead |

## Architecture

```text
Browser (React notebook)
        |
        v
FastAPI API  -----> PostgreSQL (datasets, cells, jobs, model settings)
   |    |
   |    +-----------> S3 (uploaded files, previews, charts, exports)
   v
Queue / worker ------------> isolated Python execution environment
   |
   +-----------------------> configured LLM provider(s)
```

The API should store uploaded files in S3, create a dataset record in Postgres, and queue profiling. For a question, a worker should load the approved dataset into pandas, give the model a constrained dataset profile and question, validate the returned code, run it in an isolated environment, save resulting table/chart artifacts, and return a structured cell result. Never execute model-generated code in the API process.

## Quick start (when implementation begins)

```bash
cp .env.example .env
docker compose up --build
```

Frontend: `http://localhost:5173` · API docs: `http://localhost:8000/docs` ·
MinIO console: `http://localhost:9001`

## Layout

- `apps/api` — FastAPI application and API contracts
- `apps/web` — React notebook UI
- `packages/data_engine` — ingestion, profiling, execution policy, result serialization
- `packages/llm_gateway` — provider-agnostic LLM middleware, adapters, and model registry
- `packages/charting` — chart-spec generation and artifact helpers
- `infra/terraform` — AWS infrastructure modules and environments
- `docs` — architectural decisions and implementation notes

Read [docs/local-development.md](docs/local-development.md), [docs/implementation-roadmap.md](docs/implementation-roadmap.md), and [docs/llm-middleware.md](docs/llm-middleware.md) before building behavior.
