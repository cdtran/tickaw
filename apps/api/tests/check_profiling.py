"""Golden profiling cases plus real worker/database/object-storage integration."""
import io
import json
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pandas as pd
from app.db.session import get_session_factory
from app.models import DatasetVersion, ProfilingJob
from app.workers.profiling import run_job
from botocore.exceptions import EndpointConnectionError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from packages.data_engine.profiling import ProfileError, profile_csv
from tests import check_uploads

GOLDEN = (b"category,revenue,active,code,missing,date\n"
          b"Books,120,true,001,,2026-01-01\n"
          b"Games,,false,002,,2026-01-02\n"
          b"Books,180,true,003,,2026-01-03\n")


class ProfilerTests(unittest.TestCase):
    def profile(self, data):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, parquet = root / "input.csv", root / "data.parquet"
            source.write_bytes(data)
            result = profile_csv(source, parquet, 10 * 1024**2)
            return result, pd.read_parquet(parquet)

    def test_golden_values_and_types(self):
        result, frame = self.profile(GOLDEN)
        self.assertEqual(result["row_count"], 3)
        self.assertEqual([c["inferred_type"] for c in result["schema_json"]["columns"]],
                         ["string", "integer", "boolean", "string", "unknown", "date"])
        self.assertEqual([c["null_count"] for c in result["profile_json"]["columns"]], [0, 1, 0, 0, 3, 0])
        self.assertEqual(result["profile_json"]["columns"][1]["sample_values"], [120, 180])
        self.assertEqual(result["preview_json"][1], {"category": "Games", "revenue": None,
                         "active": False, "code": "002", "missing": None, "date": "2026-01-02"})
        self.assertEqual(frame["revenue"].sum(), 300)
        self.assertEqual(frame["code"].tolist(), ["001", "002", "003"])
        json.dumps(result, allow_nan=False)

    def test_empty_data_bom_quotes_and_null_policy(self):
        result, _ = self.profile(b"a,b\n")
        self.assertEqual(result["row_count"], 0)
        self.assertEqual(result["preview_json"], [])
        result, _ = self.profile('\ufeffname,value\n"hello, world",NA\n"two\nlines",NULL\n'.encode())
        self.assertEqual(result["row_count"], 2)
        self.assertEqual(result["preview_json"][0]["name"], "hello, world")
        self.assertEqual(result["preview_json"][1]["value"], "NULL")

    def test_bounded_metadata_and_full_parquet(self):
        data = ("name\n" + ("x" * 300 + "\n") * 12).encode()
        result, frame = self.profile(data)
        self.assertEqual(len(result["preview_json"]), 10)
        self.assertEqual(len(result["profile_json"]["columns"][0]["sample_values"]), 5)
        self.assertEqual(len(result["preview_json"][0]["name"]), 257)
        self.assertEqual(len(frame.iloc[0, 0]), 300)

    def test_invalid_csv_and_limits(self):
        cases = [b"", b"a,a\n1,2\n", b"a,\n1,2\n", b"a,b\n1,2,3\n", b"a,b\n1\n",
                 b'a,b\n"unterminated,2', b"a\n\xff", b"a\n\x00", b"a\n" + b"x" * 16385]
        for data in cases:
            with self.subTest(data=data[:30]), self.assertRaises(ProfileError):
                self.profile(data)
        with patch("packages.data_engine.profiling.MAX_ROWS", 1), self.assertRaises(ProfileError):
            self.profile(b"a\n1\n2\n")
        with patch("packages.data_engine.profiling.MAX_COLUMNS", 1), self.assertRaises(ProfileError):
            self.profile(b"a,b\n1,2\n")

    def test_numeric_precision_and_mixed_types(self):
        result, _ = self.profile(b"large,mixed,decimal\n9007199254740993,1,1.5\n9007199254740994,x,2.5\n")
        self.assertEqual(result["preview_json"][0]["large"], "9007199254740993")
        self.assertEqual(result["schema_json"]["columns"][1]["inferred_type"], "string")
        self.assertEqual(result["schema_json"]["columns"][2]["inferred_type"], "number")

    def test_quoted_empty_whitespace_and_crlf_are_preserved(self):
        result, frame = self.profile(b'name\r\n""\r\n   \r\n"two\r\nlines"\r\n\r\n')
        self.assertEqual(result["row_count"], 3)
        self.assertEqual(result["preview_json"], [{"name": None}, {"name": "   "}, {"name": "two\r\nlines"}])
        self.assertEqual(frame.iloc[2, 0], "two\r\nlines")

    def test_very_long_numeric_identifier_stays_text(self):
        result, frame = self.profile(("identifier\n" + "9" * 5000 + "\n").encode())
        self.assertEqual(result["schema_json"]["columns"][0]["inferred_type"], "string")
        self.assertEqual(len(frame.iloc[0, 0]), 5000)

    def test_error_codes_and_delimiter_policy(self):
        cases = [(b"a\n\xff", "UNSUPPORTED_ENCODING"),
                 (b"a\n" + b"x" * 16385, "FIELD_LIMIT"),
                 (b"a;b\n1;2\n", "UNSUPPORTED_DELIMITER"),
                 (b"a\tb\n1\t2\n", "UNSUPPORTED_DELIMITER"),
                 (b"a|b\n1|2\n", "UNSUPPORTED_DELIMITER"),
                 (b"<html><body>export failed</body></html>", "UNSUPPORTED_FORMAT")]
        for data, code in cases:
            with self.subTest(code=code), self.assertRaises(ProfileError) as failure:
                self.profile(data)
            self.assertEqual(failure.exception.code, code)
        result, _ = self.profile(b'"a;b"\n"x;y"\n')
        self.assertEqual(result["preview_json"], [{"a;b": "x;y"}])



class WorkerTests(check_uploads.UploadTests):
    # Reuse disposable DB/bucket setup and run the upload regression cases too.
    def uploaded_job(self, data=GOLDEN, dataset_id=None):
        response = self.upload(data=data, dataset_id=dataset_id)
        self.assertEqual(response.status_code, 201, response.text)
        dataset = response.json()
        version_id = dataset["versions"][0]["id"]
        with get_session_factory()() as session:
            job = session.scalar(select(ProfilingJob).where(ProfilingJob.dataset_version_id == version_id))
            return dataset, version_id, job.id

    def test_worker_persists_profile_and_exact_version(self):
        dataset, version_id, job_id = self.uploaded_job()
        self.assertTrue(run_job(job_id))
        result = self.client.get(f"/api/v1/datasets/versions/{version_id}").json()
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["row_count"], 3)
        self.assertEqual(result["job"]["status"], "SUCCEEDED")
        self.assertEqual(result["preview_json"][1]["revenue"], None)
        with get_session_factory()() as session:
            version = session.get(DatasetVersion, version_id)
            obj = self.storage.get_object(Bucket=self.bucket, Key=version.normalized_object_key)
            frame = pd.read_parquet(io.BytesIO(obj["Body"].read()))
            self.assertEqual(frame["revenue"].sum(), 300)
            original = self.storage.get_object(Bucket=self.bucket, Key=version.original_object_key)
            self.assertEqual(original["Body"].read(), GOLDEN)
        self.assertEqual(self.client.post(f"/api/v1/datasets/versions/{version_id}/profile").status_code, 202)
        self.assertFalse(run_job(job_id))
        _, second_id, second_job = self.uploaded_job(b"category,revenue\nBooks,5\n", dataset["id"])
        run_job(second_job)
        self.assertEqual(self.client.get(f"/api/v1/datasets/versions/{second_id}").json()["row_count"], 1)
        self.assertEqual(self.client.get(f"/api/v1/datasets/versions/{version_id}").json(), result)

    def test_duplicate_requests_and_concurrent_workers(self):
        _, version_id, job_id = self.uploaded_job()
        for _ in range(2):
            self.assertEqual(self.client.post(f"/api/v1/datasets/versions/{version_id}/profile").status_code, 202)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run_job, [job_id, job_id]))
        self.assertEqual(sorted(results), [False, True])
        detail = self.client.get(f"/api/v1/datasets/versions/{version_id}").json()
        self.assertEqual(detail["job"]["attempt_count"], 1)

    def test_parse_failure_and_timeout(self):
        _, version_id, job_id = self.uploaded_job(b"a,a\n1,2\n")
        run_job(job_id)
        result = self.client.get(f"/api/v1/datasets/versions/{version_id}").json()
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["job"]["error_code"], "DUPLICATE_COLUMNS")
        self.assertIsNone(result["schema_json"])
        _, version_id, job_id = self.uploaded_job()
        with patch("app.workers.profiling.subprocess.run", side_effect=subprocess.TimeoutExpired("parser", 45)):
            run_job(job_id)
        result = self.client.get(f"/api/v1/datasets/versions/{version_id}").json()
        self.assertEqual(result["job"]["error_code"], "PROFILE_TIMEOUT")
        self.assertEqual(result["status"], "FAILED")

    def test_transient_storage_retry_and_interrupted_job_recovery(self):
        _, version_id, job_id = self.uploaded_job()
        with patch("app.workers.profiling.execute_profile", side_effect=EndpointConnectionError(endpoint_url="test")):
            run_job(job_id)
        detail = self.client.get(f"/api/v1/datasets/versions/{version_id}").json()
        self.assertEqual(detail["job"]["status"], "QUEUED")
        with get_session_factory()() as session:
            job = session.get(ProfilingJob, job_id)
            job.status = "PROCESSING"  # Simulate process death with no remaining lock.
            session.commit()
        run_job(job_id)
        result = self.client.get(f"/api/v1/datasets/versions/{version_id}").json()
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["job"]["attempt_count"], 2)
        self.assertIsNone(result["error_message"])

    def test_existing_upload_can_be_enqueued(self):
        _, version_id, job_id = self.uploaded_job()
        with get_session_factory()() as session:
            session.delete(session.get(ProfilingJob, job_id))
            session.commit()
        self.assertEqual(self.client.post(f"/api/v1/datasets/versions/{version_id}/profile").status_code, 202)
        with get_session_factory()() as session:
            new_job = session.scalar(select(ProfilingJob).where(ProfilingJob.dataset_version_id == version_id))
            self.assertNotEqual(new_job.id, job_id)
            new_job_id = new_job.id
        run_job(new_job_id)
        self.assertEqual(self.client.get(f"/api/v1/datasets/versions/{version_id}").json()["status"], "READY")

    def test_sample_files_end_to_end(self):
        fixtures = Path(__file__).parent / "fixtures" / "csv"
        manifest = json.loads((fixtures / "manifest.json").read_text())
        for case in manifest["cases"]:
            with self.subTest(file=case["file"]):
                original = (fixtures / case["file"]).read_bytes()
                _, version_id, job_id = self.uploaded_job(original)
                self.assertTrue(run_job(job_id))
                result = self.client.get(f"/api/v1/datasets/versions/{version_id}").json()
                self.assertEqual(result["status"], case["status"])
                self.assertEqual(result["job"]["attempt_count"], 1)
                self.assertIsNotNone(result["job"]["completed_at"])
                with get_session_factory()() as session:
                    version = session.get(DatasetVersion, version_id)
                    stored = self.storage.get_object(Bucket=self.bucket, Key=version.original_object_key)
                    self.assertEqual(stored["Body"].read(), original)
                    if case["status"] == "FAILED":
                        self.assertIsNone(version.normalized_object_key)
                if case["status"] == "READY":
                    self.assertEqual(result["row_count"], case["row_count"])
                    self.assertEqual(result["preview_json"], case["preview"])
                    self.assertEqual([c["inferred_type"] for c in result["schema_json"]["columns"]], case["types"])
                    self.assertEqual([c["null_count"] for c in result["profile_json"]["columns"]], case["nulls"])
                    self.assertEqual(result["profile_json"]["profiler_version"], "csv-v3")
                else:
                    self.assertEqual(result["error_code"], case["error_code"])
                    self.assertEqual(result["job"]["error_code"], case["error_code"])
                    self.assertIsNone(result["preview_json"])
                    self.assertIsNone(result["profile_json"])
                    self.assertIsNone(result["schema_json"])
                    self.assertFalse(run_job(job_id))

    def test_corrected_upload_preserves_failed_version(self):
        dataset, bad_id, bad_job = self.uploaded_job(b"a,a\n1,2\n")
        run_job(bad_job)
        failed = self.client.get(f"/api/v1/datasets/versions/{bad_id}").json()
        _, good_id, good_job = self.uploaded_job(GOLDEN, dataset["id"])
        run_job(good_job)
        self.assertEqual(self.client.get(f"/api/v1/datasets/versions/{good_id}").json()["status"], "READY")
        self.assertEqual(self.client.get(f"/api/v1/datasets/versions/{bad_id}").json(), failed)
        with get_session_factory()() as session:
            with self.assertRaises(IntegrityError):
                session.delete(session.get(DatasetVersion, good_id))
                session.flush()  # A job references this version; deletion cannot silently cascade.
            session.rollback()

    def test_unexpected_processing_error_becomes_terminal(self):
        _, version_id, job_id = self.uploaded_job()
        with patch("app.workers.profiling.execute_profile", side_effect=ValueError("test internal failure")):
            run_job(job_id)
        result = self.client.get(f"/api/v1/datasets/versions/{version_id}").json()
        self.assertEqual(result["error_code"], "PROCESSING_ERROR")
        self.assertEqual(result["status"], "FAILED")
        self.assertIsNone(result["profile_json"])

    def test_attempt_exhaustion_and_missing_version(self):
        _, version_id, job_id = self.uploaded_job()
        with get_session_factory()() as session:
            job = session.get(ProfilingJob, job_id)
            job.status, job.attempt_count = "PROCESSING", 3
            session.commit()
        run_job(job_id)
        detail = self.client.get(f"/api/v1/datasets/versions/{version_id}").json()
        self.assertEqual(detail["job"]["error_code"], "ATTEMPTS_EXHAUSTED")
        self.assertEqual(detail["status"], "FAILED")
        self.assertEqual(self.client.get(f"/api/v1/datasets/versions/{uuid4()}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
