"""Allowlisted JSON events. Never pass request bodies, plans, or exceptions to logs."""

import json
import logging
import math
import re
from contextvars import ContextVar
from datetime import UTC, datetime
from uuid import UUID

from packages.llm_gateway.prompts import PROMPT_VERSION

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
LOGGER = logging.getLogger("tickaw.events")
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False

EVENTS = {
    "http.completed",
    "model.completed",
    "model.failed",
    "plan.rejected",
    "plan.accepted",
    "analysis.state",
    "analysis.stage",
    "analysis.enqueued",
    "execution.completed",
    "operation.failed",
    "profiling.started",
    "profiling.completed",
    "profiling.failed",
}
CODES = {
    "UNKNOWN",
    "MALFORMED_PLAN",
    "POLICY_BLOCKED",
    "MODEL_UNAVAILABLE",
    "ANALYSIS_ERROR",
    "ATTEMPTS_EXHAUSTED",
    "CATALOG_COLUMN_COLLISION",
    "CHART_DIMENSION_COUNT",
    "CHART_METRIC_COUNT",
    "CHART_METRIC_TYPE_MISMATCH",
    "DUPLICATE_DIMENSION",
    "DUPLICATE_METRIC_ALIAS",
    "DUPLICATE_ORDERING_FIELD",
    "EXECUTION_TIMEOUT",
    "FILE_TOO_LARGE",
    "FILTER_OPERATION_MISMATCH",
    "FILTER_TYPE_MISMATCH",
    "INVALID_CATALOG",
    "INVALID_PLAN",
    "INVALID_PROFILE",
    "INVALID_RESULT",
    "INVALID_SCHEMA",
    "INVALID_SOURCE",
    "INVALID_TEMPORAL_FILTER",
    "LINE_DIMENSION_TYPE_MISMATCH",
    "METADATA_LIMIT",
    "METRIC_ALIAS_COLLISION",
    "METRIC_TYPE_MISMATCH",
    "MISSING_MEASURE",
    "MISSING_REQUIRED_FILTER",
    "PARSER_FAILED",
    "PROCESSING_ERROR",
    "PROFILE_TIMEOUT",
    "RESULT_LIMIT",
    "RESULT_TOO_LARGE",
    "RUN_NOT_FOUND",
    "SEMANTIC_SUBSTITUTION",
    "SOURCE_LIMIT",
    "SOURCE_SIZE_MISMATCH",
    "SOURCE_UNAVAILABLE",
    "STORAGE_ERROR",
    "UNANSWERABLE_WITH_DATA",
    "UNKNOWN_COLUMN",
    "UNKNOWN_ORDERING_FIELD",
    "UNSUPPORTED_SEMANTICS",
    "WORKER_FAILED",
}
ENUMS = {
    "exception_type": {
        "RuntimeError",
        "ValueError",
        "TypeError",
        "AttributeError",
        "KeyError",
        "TimeoutError",
        "OSError",
        "IntegrityError",
        "OperationalError",
        "DBAPIError",
        "HTTPStatusError",
        "ReadTimeout",
        "ConnectionError",
        "ClientError",
        "BotoCoreError",
        "RedisError",
        "UnknownError",
    },
    "prompt_version": {PROMPT_VERSION},
    "route": {
        "/health",
        "/api/v1/auth/login",
        "/api/v1/auth/callback",
        "/api/v1/auth/me",
        "/api/v1/auth/logout",
        "/api/v1/models",
        "/api/v1/datasets",
        "/api/v1/datasets/upload-config",
        "/api/v1/datasets/uploads",
        "/api/v1/datasets/versions/{version_id}",
        "/api/v1/datasets/versions/{version_id}/profile",
        "/api/v1/notebooks",
        "/api/v1/notebooks/{notebook_id}",
        "/api/v1/notebooks/{notebook_id}/cells",
        "/api/v1/notebooks/{notebook_id}/cells/{cell_id}/analysis-runs",
        "/api/v1/analysis-runs/{run_id}",
        "/api/v1/analysis-runs/{run_id}/result",
        "/api/v1/analysis-runs/{run_id}/clarification",
        "unmatched",
    },
    "status": {"QUEUED", "PROCESSING", "SUCCEEDED", "FAILED", "NEEDS_CLARIFICATION"},
    "stage": {
        "QUEUED",
        "RETRY_WAIT",
        "GENERATING_PLAN",
        "DOWNLOADING_DATA",
        "EXECUTING",
        "COMPLETED",
        "FAILED",
        "NEEDS_CLARIFICATION",
    },
    "method": {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"},
    "provider": {"openai", "ollama", "openai-compatible"},
    "model_id": {"qwen-local", "openai-analysis"},
    "operation": {
        "http",
        "storage_upload",
        "storage_download",
        "enqueue",
        "lease_renewal",
        "analysis",
        "analysis_queue",
        "analysis_recovery",
        "analysis_iteration",
        "queue_message",
        "profiling",
        "profiling_iteration",
    },
}
IDS = {"run_id", "request_id", "dataset_version_id", "job_id"}
NUMBERS = {"duration_ms", "elapsed_ms", "estimated_response_cost_usd"}
INTEGERS = {
    "attempt",
    "generation_attempt",
    "input_tokens",
    "output_tokens",
    "status_code",
    "retry_delay_seconds",
}
BOOLEANS = {"correction", "success"}


def route_label(path: str) -> str:
    # Nested FastAPI routers may expose only a local route path in request.scope.
    # Match only reviewed templates; never serialize the supplied path itself.
    for template in ENUMS["route"] - {"unmatched"}:
        pattern = "".join(
            "[^/]+" if part.startswith("{") else re.escape(part)
            for part in re.split(r"(\{[^{}]+\})", template)
        )
        if re.fullmatch(pattern, path):
            return template
    return "unmatched"


def event(name: str, **fields) -> None:
    """Discard unknown fields and invalid values rather than serialize arbitrary objects."""
    if not isinstance(name, str) or name not in EVENTS:
        return
    record = {"schema_version": 1, "event": name, "timestamp": datetime.now(UTC).isoformat()}
    fields.setdefault("request_id", request_id.get())
    for key, value in fields.items():
        if value is None:
            continue
        if key in IDS:
            if not isinstance(value, (UUID, str)):
                continue
            try:
                record[key] = str(UUID(str(value)))
            except (ValueError, TypeError, AttributeError):
                continue
        elif key in ENUMS:
            if isinstance(value, str) and value in ENUMS[key]:
                record[key] = value
        elif key == "error_code":
            record[key] = value if isinstance(value, str) and value in CODES else "UNKNOWN"
        elif (
            key in NUMBERS
            and type(value) in (float, int)
            and math.isfinite(value)
            and value >= 0
            or key in INTEGERS
            and type(value) is int
            and value >= 0
            or key in BOOLEANS
            and type(value) is bool
        ):
            record[key] = value
    # Telemetry must not turn a committed successful operation into a failure.
    try:
        LOGGER.info(json.dumps(record, separators=(",", ":"), allow_nan=False))
    except Exception:  # noqa: BLE001,S110 -- logging failure must not alter application state.
        pass


def analysis_state(run, *, retry_delay_seconds=None):
    elapsed = None
    if run.created_at is not None:
        elapsed = max(0.0, (datetime.now(UTC) - run.created_at).total_seconds() * 1000)
    event(
        "analysis.state",
        run_id=run.id,
        status=run.status,
        stage=run.processing_stage,
        attempt=run.attempt_count,
        error_code=run.error_code,
        elapsed_ms=elapsed,
        retry_delay_seconds=retry_delay_seconds,
    )
