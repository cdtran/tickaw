"""Real PostgreSQL auth/session/ownership checks with a stubbed OIDC exchange."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.main import app
from app.models import (
    AnalysisRun,
    BrowserSession,
    Dataset,
    DatasetVersion,
    Notebook,
    NotebookCell,
    User,
)
from app.services.auth_service import LOGIN_COOKIE, SESSION_COOKIE, digest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.auth_helpers import authenticated_client


def main():
    alice, alice_id = authenticated_client()
    bob, bob_id = authenticated_client()
    with get_session_factory()() as session:
        dataset = Dataset(name="Private dataset", owner_id=alice_id)
        legacy = Dataset(name="Quarantined")
        notebook = Notebook(title="Alice notebook", owner_id=alice_id)
        bob_notebook = Notebook(title="Bob notebook", owner_id=bob_id)
        legacy_notebook = Notebook(title="Quarantined notebook")
        session.add_all([dataset, legacy, notebook, bob_notebook, legacy_notebook])
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
            question="Count rows",
            stable_model_id="qwen-local",
        )
        session.add(cell)
        session.flush()
        run = AnalysisRun(notebook_cell_id=cell.id, dataset_version_id=version.id)
        session.add(run)
        session.commit()
        dataset_id, version_id, notebook_id, cell_id, run_id = (
            dataset.id,
            version.id,
            notebook.id,
            cell.id,
            run.id,
        )
        legacy_id, legacy_notebook_id, bob_notebook_id = (
            legacy.id,
            legacy_notebook.id,
            bob_notebook.id,
        )
    assert str(dataset_id) in [r["id"] for r in alice.get("/api/v1/datasets").json()]
    assert str(dataset_id) not in [r["id"] for r in bob.get("/api/v1/datasets").json()]
    assert str(notebook_id) not in [r["id"] for r in bob.get("/api/v1/notebooks").json()]
    assert str(legacy_id) not in [r["id"] for r in alice.get("/api/v1/datasets").json()]
    assert alice.get(f"/api/v1/notebooks/{legacy_notebook_id}").status_code == 404
    assert alice.get(f"/api/v1/datasets/versions/{version_id}").status_code == 200
    assert alice.get(f"/api/v1/analysis-runs/{run_id}").status_code == 200
    assert alice.get(f"/api/v1/notebooks/{notebook_id}").status_code == 200
    payload = {
        "question": "Count rows",
        "dataset_version_id": str(version_id),
        "stable_model_id": "qwen-local",
    }
    for path in [
        f"/api/v1/notebooks/{notebook_id}",
        f"/api/v1/datasets/versions/{version_id}",
        f"/api/v1/analysis-runs/{run_id}",
        f"/api/v1/analysis-runs/{run_id}/result",
    ]:
        assert bob.get(path).status_code == 404, path
    with (
        patch("app.services.dataset_service.store_original") as storage,
        patch("app.services.analysis_service.enqueue_run") as enqueue,
    ):
        assert bob.post(f"/api/v1/datasets/versions/{version_id}/profile").status_code == 404
        assert bob.post(f"/api/v1/notebooks/{notebook_id}/cells", json=payload).status_code == 404
        assert (
            bob.post(f"/api/v1/notebooks/{bob_notebook_id}/cells", json=payload).status_code == 404
        )
        assert (
            bob.post(f"/api/v1/notebooks/{notebook_id}/cells/{cell_id}/analysis-runs").status_code
            == 404
        )
        assert (
            bob.post(
                f"/api/v1/analysis-runs/{run_id}/clarification", json={"answer": "Count rows"}
            ).status_code
            == 404
        )
        for target in [dataset_id, legacy_id]:
            response = bob.post(
                f"/api/v1/datasets/uploads?filename=data.csv&dataset_id={target}",
                content=b"column\nvalue\n",
                headers={"Content-Type": "text/csv"},
            )
            assert response.status_code == 404, response.text
        storage.assert_not_called()
        enqueue.assert_not_called()
    created = bob.post("/api/v1/notebooks", json={"title": "New private notebook"})
    assert created.status_code == 201
    assert alice.get("/api/v1/notebooks/" + created.json()["id"]).status_code == 404
    assert (
        bob.post(
            "/api/v1/notebooks",
            json={"title": "Blocked"},
            headers={"Origin": "https://attacker.test"},
        ).status_code
        == 403
    )
    token = alice.cookies.get(SESSION_COOKIE)
    assert alice.post("/api/v1/auth/logout").status_code == 204
    alice.cookies.set(SESSION_COOKIE, token)
    assert alice.get("/api/v1/auth/me").status_code == 401
    with get_session_factory()() as session:
        record = session.get(BrowserSession, digest(bob.cookies.get(SESSION_COOKIE)))
        record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    assert bob.get("/api/v1/auth/me").status_code == 401
    settings = get_settings()
    overrides = {
        "auth_issuer": "https://cognito-idp.us-east-1.amazonaws.com/test-pool",
        "auth_domain": "https://test.auth.us-east-1.amazoncognito.com",
        "auth_client_id": "test-client",
        "auth_app_origin": "http://localhost:5173",
        "auth_cookie_secure": False,
    }
    with patch.multiple(settings, **overrides):
        oidc = TestClient(app, follow_redirects=False)

        def begin():
            response = oidc.get("/api/v1/auth/login")
            assert response.status_code == 302
            assert (
                "HttpOnly" in response.headers["set-cookie"]
                and "SameSite=lax" in response.headers["set-cookie"]
            )
            query = parse_qs(urlsplit(response.headers["location"]).query)
            assert query["identity_provider"] == ["Google"] and query["code_challenge_method"] == [
                "S256"
            ]
            return query

        query = begin()
        callback = "/api/v1/auth/callback?" + "state=" + query["state"][0] + "&code=private-code"
        # A different browser cannot consume this browser's transaction.
        attacker = TestClient(app, follow_redirects=False)
        assert attacker.get(callback).status_code == 400
        assert oidc.get(callback.replace(query["state"][0], "wrong-state")).status_code == 400
        claims = {
            "iss": settings.auth_issuer,
            "sub": "google-cognito-sub",
            "email": "google@example.test",
            "exp": int((datetime.now(UTC) + timedelta(minutes=30)).timestamp()),
        }
        with patch("app.api.v1.endpoints.auth.exchange_code", return_value=claims) as exchange:
            response = oidc.get(callback)
            assert response.status_code == 303, response.text
            exchange.assert_called_once()
            assert exchange.call_args.args[2] == query["nonce"][0]
            assert "private-code" not in response.headers["location"]
            assert oidc.get(callback).status_code == 400  # replay cannot create another session
        assert oidc.cookies.get(LOGIN_COOKIE) is None
        me = oidc.get("/api/v1/auth/me")
        assert me.status_code == 200 and me.json()["email"] == claims["email"]
        first_id, first_token = me.json()["id"], oidc.cookies.get(SESSION_COOKIE)
        query = begin()
        with patch("app.api.v1.endpoints.auth.exchange_code", return_value=claims):
            assert (
                oidc.get(
                    "/api/v1/auth/callback", params={"state": query["state"][0], "code": "second"}
                ).status_code
                == 303
            )
        assert oidc.get("/api/v1/auth/me").json()["id"] == first_id
        with get_session_factory()() as session:
            assert session.get(BrowserSession, digest(first_token)) is None  # rotation
            record = session.get(BrowserSession, digest(oidc.cookies.get(SESSION_COOKIE)))
            assert record.expires_at.timestamp() <= claims["exp"]
            assert session.scalar(select(User).where(User.id == first_id)).subject == claims["sub"]
        query = begin()
        with patch(
            "app.api.v1.endpoints.auth.exchange_code", side_effect=HTTPException(401, "safe error")
        ):
            response = oidc.get(
                "/api/v1/auth/callback", params={"state": query["state"][0], "code": "bad"}
            )
            assert (
                response.status_code == 303 and "auth_error=failed" in response.headers["location"]
            )
        query = begin()
        response = oidc.get(
            "/api/v1/auth/callback", params={"state": query["state"][0], "error": "access_denied"}
        )
        assert (
            response.status_code == 303 and "auth_error=cancelled" in response.headers["location"]
        )
    print(
        "PASS: ownership across API routes, legacy quarantine, CSRF, expiry/logout, browser-bound one-use callbacks, stable identity, session rotation"
    )


if __name__ == "__main__":
    main()
