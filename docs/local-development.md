# Local development

## Services

`docker compose up --build` starts the local development stack:

| Service | Address | Purpose |
| --- | --- | --- |
| Web | http://localhost:5173 | React development UI |
| API | http://localhost:8000 | FastAPI service |
| API documentation | http://localhost:8000/docs | OpenAPI browser |
| PostgreSQL | localhost:5432 | Application metadata (datasets and versions) |
| Redis | localhost:6379 | Scaffold service; future jobs use SQS |
| MinIO API | http://localhost:9000 | S3-compatible local object storage |
| MinIO console | http://localhost:9001 | Object storage administration |

Copy `.env.example` to `.env` only when you want to override defaults or add
provider credentials. Do not commit `.env`.

## Day 1 checks

After the containers are healthy:

1. Open the web app and confirm the status page appears.
2. Open `/docs` and call `GET /health`; it should return `status: ok`.
3. Open the MinIO console and sign in with the local development credentials
   from `.env.example`.
4. Run `docker compose ps` and confirm all services are running.

No buckets, database tables, uploads, queues, or LLM calls are created in this
first local-stack milestone.

## Day 2 checks

Rebuild the API image to install SQLAlchemy, psycopg (the Postgres driver), and Alembic:

```sh
docker compose up -d --build api
docker compose exec -T api python -m tests.check_migrations
docker compose exec -T api alembic upgrade head
docker compose exec -T api alembic current
```

Run commands from the repository root. `exec -T api` runs inside the existing API
container without an interactive terminal. The API bind mount exposes migration
files immediately; changes to installed dependencies require rebuilding the image.
Inside Compose, `postgres` is the database hostname; on the host it is `localhost`.

See [the dataset model walkthrough](dataset-metadata.md) for architecture, session
usage, constraints, and test details. `/health` remains a process-health check and
does not assert database readiness.

## CSV uploads

See [CSV uploads](csv-uploads.md) for setup, validation, API flow and the sample file.
Migration `0002` adds UPLOADED, distinguishing stored originals from READY data.
The migration test harness now also needs MinIO for upload integration tests.
