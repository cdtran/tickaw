"""Integration checks against a migrated disposable Postgres database.

Run from /app: python -m tests.check_database
Uses only installed runtime dependencies. All fixture writes are rolled back.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.session import get_session_factory
from app.models import Dataset, DatasetVersion


def rejected(session, operation):
    try:
        with session.begin_nested():
            operation()
            session.flush()
    except DBAPIError:
        return
    raise AssertionError("Expected database to reject invalid write")


def main():
    with get_session_factory()() as session:
        dataset = Dataset(name="Sales")
        session.add(dataset)
        session.flush()

        def version(number=1, **overrides):
            fields = dict(dataset_id=dataset.id, version_number=number,
                          original_filename="sales.csv", file_format="csv",
                          storage_bucket="test", original_object_key=str(uuid4()))
            fields.update(overrides)
            return DatasetVersion(**fields)

        first = version()
        session.add(first)
        session.flush()
        assert first.status == "UPLOADING"
        assert first.created_at.tzinfo is not None
        rejected(session, lambda: session.add(version()))
        rejected(session, lambda: session.add(version(2, dataset_id=uuid4())))
        rejected(session, lambda: session.add(version(0)))
        rejected(session, lambda: session.add(version(2, size_bytes=-1)))
        rejected(session, lambda: session.add(version(2, file_format="exe")))
        rejected(session, lambda: session.add(version(2, status="INVALID")))
        rejected(session, lambda: session.add(version(2, status="READY")))
        rejected(session, lambda: session.add(version(2, status="FAILED")))
        rejected(session, lambda: session.add(version(2, original_object_key=first.original_object_key)))
        rejected(session, lambda: session.execute(
            update(DatasetVersion).where(DatasetVersion.id == first.id).values(version_number=3)))
        first.status = "PROCESSING"
        first.processing_started_at = datetime.now(timezone.utc)
        session.flush()
        first.schema_json = {"columns": [{"name": "revenue", "type": "integer"}]}
        first.profile_json = {"null_counts": {"revenue": 0}}
        first.preview_json = [{"revenue": 42}]
        first.row_count = 1
        first.normalized_object_key = "normalized/test.parquet"
        first.completed_at = datetime.now(timezone.utc)
        first.status = "READY"
        session.flush()
        session.expire(first)
        assert first.preview_json == [{"revenue": 42}]
        rejected(session, lambda: session.execute(
            update(DatasetVersion).where(DatasetVersion.id == first.id).values(row_count=2)))
        rejected(session, lambda: session.delete(dataset))
        session.add(version(2))
        session.flush()
        assert len(session.scalars(select(DatasetVersion).where(
            DatasetVersion.dataset_id == dataset.id)).all()) == 2
        session.rollback()
    print("PASS: relationships, JSON, statuses, uniqueness, constraints, and immutability")


if __name__ == "__main__":
    main()
