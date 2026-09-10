# CSV upload milestone

## Try it

The API and web containers must run with migration 0002 and a local upload bucket:

```sh
docker compose up -d --build api web
docker compose exec -T api alembic upgrade head
docker compose exec -T api python -m scripts.init_storage
```

Open http://localhost:5173, choose a CSV, and click **Upload CSV**. A sample is at
`tests/fixtures/sales.csv`. Leave the destination as **Create a new dataset** to
create a dataset named after the file. Select an existing dataset to add a new
version instead. Uploading a filename twice does not implicitly merge datasets.
The list persists through reloads because it comes from Postgres.

A successful version reads **Uploaded · awaiting profiling**. It is not READY;
CSV parsing, schema/profile extraction, Parquet and analysis are the next milestone.
The destination selector uses the current page of datasets; page through the list
to select older datasets. No authentication/ownership checks exist yet: this remains
local development, with all datasets visible to the local user.

## Follow a request through the code

1. `apps/web/src/App.tsx` sends the selected browser `File` as the HTTP body to
   `POST /api/v1/datasets/uploads?filename=sales.csv`. An optional `dataset_id`
   selects an existing dataset. This is a raw-body upload, not multipart/form-data.
2. Vite proxies `/api` to `http://api:8000` inside Compose. The browser uses its own
   origin and never needs to resolve Docker's `api` hostname. A future production
   reverse proxy must provide the same route; Vite's dev proxy isn't in the build.
3. `apps/api/app/api/v1/endpoints/datasets.py` checks the metadata, counts streamed
   bytes and does basic text validation. It calls synchronous persistence in a
   thread pool so SQLAlchemy and boto3 don't block the async event loop.
4. `apps/api/app/services/dataset_service.py` creates or locks the parent dataset,
   allocates its next version, and commits an UPLOADING record. The row lock is
   released before storage I/O. The unique constraint remains the final guard.
5. `apps/api/app/services/object_storage.py` writes the exact original bytes with
   `If-None-Match: *` to `datasets/{dataset_uuid}/versions/{version_uuid}/original.csv`.
   The filename never controls the storage path. Existing keys cannot be overwritten
   through this write path; no overwrite/delete endpoint is exposed.
6. The service commits UPLOADED after storage acknowledges success. The response
   includes dataset/version metadata, and the UI refreshes its list.

GET `/api/v1/datasets` returns datasets with versions (newest first), with dataset
pagination via `offset` and `limit` (default 50, max 100). GET
`/api/v1/datasets/upload-config` returns the configured maximum byte count. Version
histories are currently returned in full; a large-history API will need separate
version pagination.

## Validation boundary

- Plain filenames only, no path separators, control characters, or surrounding
  whitespace; maximum 255 UTF-8 bytes and a nonempty `.csv` basename.
- Case-insensitive `.csv` extension; XLSX is intentionally not accepted yet.
- MIME allowlist: `text/csv`, `application/csv`, `text/plain`, and
  `application/vnd.ms-excel` (a common CSV browser mapping). Parameters such as
  `charset=utf-8` are allowed. Missing MIME is rejected by the API; the UI supplies
  `text/csv` when the browser has no MIME guess.
- Default size: **10 MiB**, configured by `MAX_UPLOAD_BYTES`. Both a declared
  Content-Length and actual streamed bytes are checked. Empty files are rejected.
- UTF-8 (including BOM) text only; binary control characters are rejected. This
  does not yet validate CSV structure, consistent rows, or schema. Plain text with
  a CSV extension may be stored, but is never declared analysis-ready.

The endpoint buffers the bounded file in memory. It avoids unbounded multipart
spooling but does not yet limit aggregate memory across concurrent requests or
implement upload timeouts/rate limits. Direct presigned uploads will eventually
remove the API from the byte-transfer path.

## Reliability and immutability limits

Postgres and S3 have separate transactions. A storage exception marks the reserved
version FAILED with an error code/message and completion time; the API returns
503. A transport error can be ambiguous: the object may have reached storage even
when the caller didn't receive confirmation. We preserve that object rather than
risk overwriting or deleting it.

A process crash or database error after reservation can leave UPLOADING. Future
reconciliation must compare storage and database state and recover or fail stale
uploads. There are no queues, retries or request idempotency keys in this milestone;
submitting again creates another version. After an uncertain response, inspect the
list before retrying. A failed version remains visible.

The conditional write protects originals through this application. A local MinIO
administrator can still delete or replace objects using separate credentials. AWS
IAM/bucket policies, retention and stronger storage controls remain deployment work.
The local initializer uses existing MinIO credentials; AWS bucket provisioning
belongs in Terraform and the client uses the ECS task role when no local endpoint
is configured.

## Verification

```sh
docker compose exec -T api python -m tests.check_migrations
docker compose exec -T web npm run build
```

The integration harness creates a disposable Postgres database and a uniquely named
MinIO bucket, then cleans them up. It checks migrations and model agreement, upload
persistence, exact original bytes, immutable writes, filename/MIME/text/size errors,
missing datasets, storage failure, and concurrent version allocation. The frontend
build type-checks the React code. Browser verification: upload the sample, reload,
then select its dataset and upload again; expect versions 2 and 1.

Migration 0002's downgrade refuses to remove UPLOADED when such rows exist rather
than silently assigning them a misleading status. The empty disposable database
allows the full downgrade/re-upgrade check.
