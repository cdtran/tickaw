# Day 2: dataset metadata foundation

## Mental model

A **dataset** is a named collection, such as “Monthly sales.” A **dataset version**
is one snapshot of that collection. Uploading corrected sales creates version 2;
it does not replace version 1. A notebook cell will eventually reference the
version's UUID, not a dataset's “latest” version. Datasets have no notebook foreign
key: the same version can support multiple notebooks.

`datasets (1) → (many) dataset_versions`

## What we store

| Location | Contents |
| --- | --- |
| `datasets` | Stable UUID, editable name/description, creation timestamp |
| `dataset_versions` | UUID, parent dataset, positive version number, status, source filename/format, size, bucket/object keys, schema/profile/preview JSON, row count, timestamps and failure details |
| S3 / local MinIO (later) | Original upload and normalized Parquet, addressed by the stored keys |

UUIDs identify records independently of filenames. Version numbers are human
labels scoped to a dataset; `(dataset_id, version_number)` is unique. That unique
index also supports listing versions by dataset. Concurrent version allocation
will need locking or a retry when we implement writes; `max + 1` alone is unsafe.

Schema/profile use Postgres JSONB because every file may have different columns.
For example, `schema_json` might contain
`{"columns": [{"name": "revenue", "type": "integer"}]}`. These columns never become
Postgres columns. JSON shapes and preview size caps will be validated at the
service boundary in the ingestion milestone; JSONB alone does not validate them.
Unset JSON values use SQL NULL, so readiness constraints can detect missing data.

Keys are durable object addresses; presigned URLs are temporary permissions and
are not stored. The bucket and original key are unique together to prevent two
versions from claiming the same original object. Actual key-prefix validation,
object existence, content validation, and overwrite prevention arrive with uploads.

For XLSX, selecting sheets and deciding the normalized table representation remain
an ingestion design step. This migration does not imply silently merging sheets.

## Lifecycle and immutability

Expected flow: `UPLOADING → UPLOADED → PROCESSING → READY` or `FAILED`.
UPLOADED was added in migration 0002 for the API-mediated CSV milestone; it means
the original is stored, but profiling has not started.

The database checks the allowed status values. READY requires a normalized key,
schema, profile, preview, row count and completion time; FAILED requires error code,
message and completion time. The migration freezes version identity and source
fields immediately, and all fields once READY. This is enforced by a Postgres
trigger even if a script bypasses SQLAlchemy. Dataset names remain editable.

State-transition ordering, retries and worker claims are **not** implemented yet.
The future ingestion-job model should own attempts, retry counts, idempotency keys
and execution timing. Version status summarizes data availability; it is not a
substitute for the job's execution history. READY updates are rejected; retries
must eventually recognize completed work and return without rewriting it.

The trigger does not prohibit explicit deletion. Dataset deletion is blocked while
versions exist (a restrictive foreign key), so nothing is silently cascaded. A later
retention workflow must coordinate version deletion, notebook references and S3
cleanup. S3 objects must also become immutable for reproducibility to hold.

## Python pieces

- `app/core/config.py`: reads DATABASE_URL from the environment; SecretStr masks
  normal settings display. Compose injects the root `.env`; Python does not load
  that file on its own.
- `app/db/base.py`: shared SQLAlchemy table registry and consistent constraint names.
- `app/models/dataset.py`: typed Python mappings for the two tables.
- `app/db/session.py`: lazily creates an engine (connection pool) and session factory.
  `pool_pre_ping` checks reused connections. A session scopes database work; callers
  explicitly commit. Closing an unfinished session rolls its transaction back.
- `migrations/`: Alembic's versioned schema history. Revision 0001 defines the tables
  independently of live model classes, so later model edits cannot rewrite history.

We use synchronous SQLAlchemy to keep this first step straightforward. Future API
handlers doing synchronous DB work should be regular `def` handlers, which FastAPI
runs in its thread pool, or explicitly offload that work. Do not block an async
handler's event loop with these sessions. Each request/job gets its own session.

Migrations run explicitly, separately from API startup. `upgrade head` applies
pending revisions and records the current revision in `alembic_version`; repeating
it is a no-op. `alembic check` compares mapped tables with the database, but does
not validate custom triggers; the integration checks exercise those directly.

## Test and inspect

From the repository root, with the API and Postgres running:

```sh
docker compose exec -T api python -m tests.check_migrations
docker compose exec -T api alembic upgrade head
docker compose exec -T api alembic current
docker compose exec -T postgres psql -U postgres -d data_notebook -c '\d dataset_versions'
```

The test harness creates a uniquely named disposable database, checks upgrade,
model/schema agreement, relationships, JSON round trips, invalid writes and READY
immutability, then downgrade/re-upgrade. It removes only its disposable database.
It requires the local database user's create/drop database permissions. Fixture
writes are rolled back. Never exercise `downgrade base` on a database whose data
you want to retain: it drops the tables.

## Next small milestone

The [CSV upload milestone](csv-uploads.md) now adds typed responses, a dataset list,
and original CSV storage. Profiling/Parquet, notebook models, queue jobs,
authentication/tenancy and LLM integration are still deferred.
