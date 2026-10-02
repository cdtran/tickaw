"""Real Postgres + MinIO API integration tests, only in a disposable test database."""
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

from botocore.exceptions import ClientError, EndpointConnectionError
from tests.auth_helpers import authenticated_client
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.main import app
from app.models import Dataset, DatasetVersion, ProfilingJob
from app.services.object_storage import get_storage_client, store_original

CSV = b"category,revenue\nBooks,120\nGames,240\n"


class UploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = get_settings()
        if not make_url(cls.settings.database_url.get_secret_value()).database.startswith("migration_test_"):
            raise RuntimeError("Run through tests.check_migrations: these tests need a disposable database.")
        cls.bucket = "upload-test-" + uuid4().hex
        cls.settings.object_storage_bucket = cls.bucket
        cls.storage = get_storage_client()
        cls.storage.create_bucket(Bucket=cls.bucket)
        cls.client, cls.user_id = authenticated_client()

    def tearDown(self):
        with get_session_factory()() as session:
            session.execute(delete(ProfilingJob))
            session.execute(delete(DatasetVersion))
            session.execute(delete(Dataset))
            session.commit()

    @classmethod
    def tearDownClass(cls):
        # Only our uniquely named test bucket; never the development upload bucket.
        for page in cls.storage.get_paginator("list_objects_v2").paginate(Bucket=cls.bucket):
            for obj in page.get("Contents", []):
                cls.storage.delete_object(Bucket=cls.bucket, Key=obj["Key"])
        cls.storage.delete_bucket(Bucket=cls.bucket)
        cls.client.close()

    def upload(self, filename="sales.csv", data=CSV, mime="text/csv", dataset_id=None):
        params = {"filename": filename}
        if dataset_id:
            params["dataset_id"] = dataset_id
        return self.client.post("/api/v1/datasets/uploads", params=params,
                                content=data, headers={"Content-Type": mime})

    def test_upload_versions_list_and_immutable_bytes(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.text)
        first = response.json()
        second = self.upload(data=CSV + b"Books,5\n", dataset_id=first["id"])
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual([v["version_number"] for v in second.json()["versions"]], [2, 1])
        self.assertEqual(first["versions"][0]["status"], "UPLOADED")
        with get_session_factory()() as session:
            versions = session.scalars(select(DatasetVersion).order_by(DatasetVersion.version_number)).all()
            key = versions[0].original_object_key
            self.assertNotEqual(key, versions[1].original_object_key)
            self.assertTrue(key.startswith(f"datasets/{first['id']}/versions/"))
            self.assertEqual(self.storage.get_object(Bucket=self.bucket, Key=key)["Body"].read(), CSV)
            with self.assertRaises(ClientError) as failure:
                store_original(self.bucket, key, b"replacement")
            self.assertEqual(failure.exception.response["ResponseMetadata"]["HTTPStatusCode"], 412)
            self.assertEqual(self.storage.get_object(Bucket=self.bucket, Key=key)["Body"].read(), CSV)
        listed = self.client.get("/api/v1/datasets").json()
        self.assertEqual(len(listed), 1)
        self.assertEqual(len(listed[0]["versions"]), 2)
        self.assertEqual(self.client.get("/api/v1/datasets?offset=1").json(), [])

    def test_reject_invalid_input_without_records(self):
        cases = [("../sales.csv", CSV, "text/csv", 422),
                 ("folder\\sales.csv", CSV, "text/csv", 422),
                 ("bad\x00.csv", CSV, "text/csv", 422),
                 (".csv", CSV, "text/csv", 422),
                 ("sales.xlsx", CSV, "text/csv", 422),
                 ("sales.csv", CSV, "application/pdf", 415),
                 ("sales.csv", CSV, "", 415),
                 ("sales.csv", b"", "text/csv", 422),
                 ("sales.csv", b"\xff\xfe", "text/csv", 422),
                 ("sales.csv", b"a\x00b", "text/csv", 422)]
        for filename, data, mime, code in cases:
            with self.subTest(filename=filename, data=data, mime=mime):
                self.assertEqual(self.upload(filename, data, mime).status_code, code)
        self.assertEqual(self.upload(dataset_id=str(uuid4())).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/datasets").json(), [])

    def test_size_limit_with_and_without_declared_length(self):
        with patch.object(self.settings, "max_upload_bytes", len(CSV)):
            self.assertEqual(self.upload().status_code, 201)
            self.assertEqual(self.upload(data=CSV + b"x").status_code, 413)
            response = self.client.post("/api/v1/datasets/uploads?filename=sales.csv",
                                        content=iter([CSV, b"x"]), headers={"Content-Type": "text/csv"})
            self.assertEqual(response.status_code, 413)

    def test_invalid_uploads_leave_no_objects_versions_or_jobs(self):
        before = self.storage.list_objects_v2(Bucket=self.bucket).get("KeyCount", 0)
        for filename, data, mime, expected in [
            (" bad.csv", CSV, "text/csv", 422),
            ("é" * 126 + ".csv", CSV, "text/csv", 422),
            ("bad.csv", b" \n\t", "text/csv", 422),
            ("bad.csv", b"\xef\xbb\xbf", "text/csv", 422),
            ("bad.csv", b"\xff\xfea\x00", "text/csv", 422),
            ("bad.csv", CSV, "application/octet-stream", 415),
            ("book.xlsx", CSV, "application/vnd.ms-excel", 422),
        ]:
            with self.subTest(filename=filename, mime=mime):
                response = self.upload(filename, data, mime)
                self.assertEqual(response.status_code, expected, response.text)
                self.assertTrue(response.json()["detail"])
        with get_session_factory()() as session:
            self.assertEqual(session.scalars(select(DatasetVersion)).all(), [])
            self.assertEqual(session.scalars(select(ProfilingJob)).all(), [])
        self.assertEqual(self.storage.list_objects_v2(Bucket=self.bucket).get("KeyCount", 0), before)

    def test_browser_mime_variants_and_uppercase_extension(self):
        for mime in ("text/csv;charset=utf-8", "application/vnd.ms-excel", "text/plain", "application/csv"):
            self.assertEqual(self.upload(filename="Sales.CSV", mime=mime).status_code, 201)

    def test_storage_failure_is_visible_and_retry_creates_new_version(self):
        with patch("app.services.dataset_service.store_original",
                   side_effect=EndpointConnectionError(endpoint_url="http://test-unavailable")):
            self.assertEqual(self.upload().status_code, 503)
        failed = self.client.get("/api/v1/datasets").json()[0]
        self.assertEqual(failed["versions"][0]["status"], "FAILED")
        self.assertTrue(failed["versions"][0]["error_message"])
        retried = self.upload(dataset_id=failed["id"]).json()
        self.assertEqual([v["version_number"] for v in retried["versions"]], [2, 1])

    def test_concurrent_version_allocation(self):
        dataset_id = self.upload().json()["id"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.upload(dataset_id=dataset_id), range(2)))
        self.assertEqual([r.status_code for r in results], [201, 201])
        versions = self.client.get("/api/v1/datasets").json()[0]["versions"]
        self.assertEqual([v["version_number"] for v in versions], [3, 2, 1])


if __name__ == "__main__":
    unittest.main()
