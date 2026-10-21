"""Verify lifecycle events describe committed database state, without private inputs."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from app.core.config import get_settings
from app.core.observability import LOGGER
from app.db.session import get_session_factory
from app.models import AnalysisRun, Dataset, DatasetVersion, Notebook, NotebookCell
from app.services.analysis_service import (
    answer_clarification,
    create_run,
    fail_run,
    request_clarification,
    schedule_retry,
    start_run,
)
from sqlalchemy.engine import make_url


def main():
    if not make_url(get_settings().database_url.get_secret_value()).database.startswith(
        "migration_test_"
    ):
        raise RuntimeError("Observability integration checks require a disposable database.")
    private = "private-question-column-credential-not-for-logs"
    records = []
    committed = []

    def capture(message):
        record = json.loads(message)
        records.append(record)
        if record["event"] == "analysis.state":
            with get_session_factory()() as observer:
                stored = observer.get(AnalysisRun, record["run_id"])
                committed.append((record["status"], stored.status))

    with (
        patch.object(LOGGER, "info", side_effect=capture),
        patch("app.services.analysis_service.enqueue_run"),
        get_session_factory()() as session,
    ):
        dataset, notebook = Dataset(name=private), Notebook(title=private)
        session.add_all([dataset, notebook])
        session.flush()
        version = DatasetVersion(
            dataset_id=dataset.id,
            version_number=1,
            status="READY",
            original_filename="private.csv",
            file_format="csv",
            storage_bucket="fixture",
            original_object_key=str(uuid4()),
            normalized_object_key=str(uuid4()),
            schema_json={"version": 1, "columns": []},
            profile_json={},
            preview_json=[],
            row_count=0,
            completed_at=datetime.now(UTC),
        )
        session.add(version)
        session.flush()
        cell = NotebookCell(
            notebook_id=notebook.id,
            dataset_version_id=version.id,
            question=private,
            stable_model_id="qwen-local",
        )
        session.add(cell)
        session.commit()
        run = create_run(session, cell.id)
        start_run(session, run.id)
        schedule_retry(session, run.id, "MODEL_UNAVAILABLE", private)
        run.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
        start_run(session, run.id)
        request_clarification(
            session, run.id, private, [{"code": "UNKNOWN_COLUMN", "column": private}]
        )
        answer_clarification(session, run.id, private)
        start_run(session, run.id)
        fail_run(session, run.id, "INVALID_PLAN", private)
    assert [e["status"] for e in records] == [
        "QUEUED",
        "PROCESSING",
        "QUEUED",
        "PROCESSING",
        "NEEDS_CLARIFICATION",
        "QUEUED",
        "PROCESSING",
        "FAILED",
    ]
    assert all(expected == actual for expected, actual in committed)
    assert len(committed) == 8
    assert records[2]["retry_delay_seconds"] == 2
    assert records[-1]["error_code"] == "INVALID_PLAN"
    assert private not in json.dumps(records)
    print("PASS: lifecycle/retry/clarification events follow committed state and omit private data")


if __name__ == "__main__":
    main()
