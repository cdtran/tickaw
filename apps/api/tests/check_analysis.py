"""Analysis result persistence checks; run through the disposable migration harness."""

from datetime import UTC, datetime
from uuid import uuid4

from app.db.session import get_session_factory
from app.main import app
from app.models import AnalysisRun, Dataset, DatasetVersion, Notebook, NotebookCell
from app.services.analysis_service import complete_run, create_run, load_result
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError, IntegrityError

from packages.data_engine.query_plan import QueryPlan
from packages.data_engine.result_types import (
    ExecutionMetadata,
    ExecutionSuccess,
    ResultCheck,
    ResultColumn,
    TableResult,
)


def rejected(session, operation):
    try:
        with session.begin_nested():
            operation()
            session.flush()
    except (DBAPIError, IntegrityError):
        return
    raise AssertionError("Expected database to reject invalid analysis state")


def main():
    plan = QueryPlan.model_validate(
        {
            "plan_version": 1,
            "dimensions": ["region"],
            "metrics": [{"op": "sum", "column": "revenue", "alias": "total_revenue"}],
            "filters": [],
            "order_by": [],
            "limit": 100,
        }
    )
    with get_session_factory()() as session:
        dataset = Dataset(name="Analysis fixture")
        session.add(dataset)
        session.flush()
        version = DatasetVersion(
            dataset_id=dataset.id,
            version_number=1,
            status="READY",
            original_filename="sales.csv",
            file_format="csv",
            size_bytes=10,
            storage_bucket="test",
            original_object_key=str(uuid4()),
            normalized_object_key=str(uuid4()),
            schema_json={"version": 1, "columns": []},
            profile_json={},
            preview_json=[],
            row_count=2,
            completed_at=datetime.now(UTC),
        )
        notebook = Notebook(title="Analysis")
        session.add_all([version, notebook])
        session.flush()
        cell = NotebookCell(
            notebook_id=notebook.id,
            dataset_version_id=version.id,
            question="Revenue by region?",
        )
        session.add(cell)
        session.commit()

        run = create_run(
            session,
            cell.id,
            plan,
            stable_model_id="analysis-default",
            prompt_version="prompt-v1",
        )
        execution = ExecutionSuccess(
            table=TableResult(
                columns=[
                    ResultColumn(
                        name="region", logical_type="text", database_type="VARCHAR", encoding="json"
                    ),
                    ResultColumn(
                        name="total_revenue",
                        logical_type="number",
                        database_type="DOUBLE",
                        encoding="json",
                    ),
                ],
                rows=[["East", 10.0], ["West", 20.0]],
                returned_rows=2,
                requested_limit=100,
                truncated=False,
                warnings=[],
                checks=[ResultCheck(name="output_columns", status="passed")],
            ),
            metadata=ExecutionMetadata(
                execution_id=str(run.id),
                dataset_version_id=str(version.id),
                plan_sha256=run.plan_sha256,
                plan_version=1,
                compiler_version="2",
                executor_version="2",
                sqlglot_version="28.10.1",
                engine_version="1.4.1",
                started_at=datetime.now(UTC).isoformat(),
                duration_ms=5,
            ),
        )
        complete_run(session, run.id, execution)
        stored = load_result(session.get(AnalysisRun, run.id))
        assert stored.execution.table.rows == [["East", 10.0], ["West", 20.0]]
        assert stored.chart and stored.chart.type == "bar" and stored.chart.x == "region"
        assert stored.chart.series[0].column == "total_revenue"

        client = TestClient(app)
        detail = client.get(f"/api/v1/notebooks/{notebook.id}").json()
        assert detail["cells"][0]["latest_analysis"]["id"] == str(run.id)
        response = client.get(f"/api/v1/analysis-runs/{run.id}/result")
        assert response.status_code == 200 and response.json()["chart"]["type"] == "bar"
        assert client.get(f"/api/v1/analysis-runs/{uuid4()}/result").status_code == 404

        rejected(
            session,
            lambda: session.execute(
                update(AnalysisRun).where(AnalysisRun.id == run.id).values(result_sha256="0" * 64)
            ),
        )
        rejected(session, lambda: session.delete(cell))
        rejected(session, lambda: session.delete(version))
        session.rollback()
    print("PASS: durable result JSON, chart spec, integrity metadata, API reload, immutability")


if __name__ == "__main__":
    main()
