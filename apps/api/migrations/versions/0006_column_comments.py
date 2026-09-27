"""Document the persisted data model in PostgreSQL column metadata."""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


COLUMN_COMMENTS = {
    "datasets": {
        "id": "Stable identifier for the dataset.",
        "name": "User-facing dataset name.",
        "description": "Optional user-facing description of the dataset.",
        "created_at": "Time the dataset was created.",
    },
    "dataset_versions": {
        "id": "Stable identifier for this dataset snapshot.",
        "dataset_id": "Dataset that owns this immutable version.",
        "version_number": "Monotonic version number within the dataset.",
        "status": "Current upload and profiling lifecycle state.",
        "original_filename": "Filename supplied when this version was uploaded.",
        "file_format": "Validated source format, currently csv or xlsx.",
        "size_bytes": "Size of the original uploaded object in bytes.",
        "storage_bucket": "S3 bucket containing this version's objects.",
        "original_object_key": "Immutable S3 key for the original uploaded file.",
        "normalized_object_key": "S3 key for the normalized Parquet snapshot.",
        "row_count": "Number of rows in the normalized snapshot.",
        "schema_json": "Versioned inferred column schema.",
        "profile_json": "Versioned dataset profiling statistics.",
        "preview_json": "Small JSON-safe preview of normalized rows.",
        "error_code": "Stable machine-readable failure code.",
        "error_message": "Safe human-readable failure description.",
        "created_at": "Time this dataset version was created.",
        "processing_started_at": "Time profiling most recently started.",
        "completed_at": "Time profiling reached a terminal state.",
    },
    "profiling_jobs": {
        "id": "Stable identifier for the profiling job.",
        "dataset_version_id": "Dataset version profiled by this job.",
        "status": "Current profiling job lifecycle state.",
        "attempt_count": "Number of processing attempts started.",
        "error_code": "Stable machine-readable failure code.",
        "error_message": "Safe human-readable failure description.",
        "created_at": "Time the job was created.",
        "started_at": "Time the current processing attempt started.",
        "completed_at": "Time the job reached a terminal state.",
    },
    "notebooks": {
        "id": "Stable identifier for the notebook.",
        "title": "User-facing notebook title.",
        "created_at": "Time the notebook was created.",
        "updated_at": "Time the notebook was last changed.",
    },
    "notebook_cells": {
        "id": "Stable identifier for the notebook cell.",
        "notebook_id": "Notebook containing this question cell.",
        "dataset_version_id": "Exact immutable dataset version used by the question.",
        "question": "User's natural-language question.",
        "status": "Question-cell lifecycle state.",
        "created_at": "Time the cell was created.",
        "updated_at": "Time the cell was last changed.",
    },
    "analysis_runs": {
        "id": "Stable identifier for the analysis run.",
        "notebook_cell_id": "Question cell that requested this analysis.",
        "dataset_version_id": "Exact immutable dataset version used for execution.",
        "status": "Current analysis execution lifecycle state.",
        "stable_model_id": "Stable identifier for the model configuration that produced the plan.",
        "prompt_version": "Version of the prompt used to produce the plan.",
        "plan_json": "Normalized, validated model-generated query plan.",
        "plan_sha256": "SHA-256 of the canonical normalized query plan.",
        "result_json": "Bounded execution result and reconstructable chart spec.",
        "result_sha256": "SHA-256 of the canonical persisted result artifact.",
        "result_size_bytes": "Canonical result artifact size in UTF-8 bytes.",
        "result_version": "Schema version of the persisted result artifact.",
        "error_code": "Stable machine-readable failure code.",
        "error_message": "Safe human-readable failure description.",
        "created_at": "Time the run was created.",
        "started_at": "Time execution started.",
        "completed_at": "Time the run reached a terminal state.",
    },
}


def upgrade():
    for table_name, columns in COLUMN_COMMENTS.items():
        for column_name, description in columns.items():
            op.alter_column(table_name, column_name, comment=description)


def downgrade():
    for table_name, columns in COLUMN_COMMENTS.items():
        for column_name, description in columns.items():
            op.alter_column(
                table_name,
                column_name,
                comment=None,
                existing_comment=description,
            )
