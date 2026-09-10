# Implementation roadmap

## Phase 1 — foundation

Create database migrations, configuration, authenticated users/workspaces, health checks, a CI workflow, and local object storage. Establish API schemas before wiring the web UI.

## Phase 2 — data lifecycle

Use presigned uploads for CSV/XLSX. Persist dataset and workbook/sheet metadata in Postgres, originals in S3, and a small preview/profile artifact separately. Enforce file size, MIME, row, column, and sheet limits.

## Phase 3 — notebook workflow

Persist notebooks and ordered cells. A question cell selects a dataset version and model. Submit it as a job; stream or poll status; retain the question, model/version, generated plan/code, execution ID, outputs, logs, and timestamps for reproducibility.

## Phase 4 — safe analysis

Do not trust generated Python. Run it outside the API in an ephemeral, network-disabled worker/container with CPU, memory, disk, and wall-time limits. Provide only read-only dataset access and an import/function allowlist. Validate code or prefer a constrained query/plan DSL where possible.

## Phase 5 — deployment

Provision S3, RDS, SQS, ECS/Fargate, Secrets Manager, IAM roles, CloudWatch, and an ALB through Terraform. Keep API and worker deployment units separate. Add lifecycle policies to remove original files and artifacts according to the product retention policy.
