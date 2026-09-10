# API service

FastAPI owns request validation, authorization, presigned uploads, metadata retrieval, model discovery, and job orchestration. It should not run user- or model-authored analysis code directly.

Implementation order:

1. Add settings, health endpoint, database session, and migrations.
2. Define the versioned schemas in `app/schemas`.
3. Add dataset upload and profile jobs.
4. Add notebook/cell and analysis job endpoints.
5. Integrate authentication and tenancy before exposing uploads publicly.
