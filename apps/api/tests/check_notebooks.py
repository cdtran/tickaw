"""API persistence checks; run only via the disposable migration harness."""
from datetime import datetime, timezone
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from app.main import app
from app.models import Dataset, DatasetVersion, Notebook, NotebookCell
from app.db.session import get_session_factory


def main():
    client = TestClient(app)
    with get_session_factory()() as session:
        dataset = Dataset(name="Notebook fixture")
        session.add(dataset)
        session.flush()
        version = DatasetVersion(dataset_id=dataset.id, version_number=1, status="READY",
            original_filename="sales.csv", file_format="csv", storage_bucket="test",
            original_object_key=str(uuid4()), normalized_object_key=str(uuid4()),
            schema_json={}, profile_json={}, preview_json=[], row_count=0,
            completed_at=datetime.now(timezone.utc))
        pending = DatasetVersion(dataset_id=dataset.id, version_number=2,
            original_filename="sales.csv", file_format="csv", storage_bucket="test",
            original_object_key=str(uuid4()))
        session.add_all([version, pending]); session.commit()
        version_id, pending_id = str(version.id), str(pending.id)
    created = client.post("/api/v1/notebooks", json={"title": " Sales notebook "})
    assert created.status_code == 201, created.text
    notebook = created.json()
    other = client.post("/api/v1/notebooks", json={"title": "Other"}).json()
    path = f"/api/v1/notebooks/{notebook['id']}"
    payload = {"question": " Revenue by region? ", "dataset_version_id": version_id}
    response = client.post(path + "/cells", json=payload)
    assert response.status_code == 201, response.text
    cell = response.json()
    assert cell['question'] == "Revenue by region?" and cell['status'] == "SAVED"
    assert cell['dataset_version_id'] == version_id
    assert cell['created_at'] and cell['updated_at']
    # A new client/request/session models a reload, without in-memory UI state.
    loaded = TestClient(app).get(path).json()
    assert loaded['cells'] == [cell]
    assert loaded['updated_at'] >= notebook['updated_at']
    assert client.get(f"/api/v1/notebooks/{other['id']}").json()['cells'] == []
    assert notebook['id'] in [item['id'] for item in client.get('/api/v1/notebooks').json()]
    for question in ('', '   ', 'x' * 4001):
        assert client.post(path + '/cells', json={**payload, 'question': question}).status_code == 422
    assert client.post('/api/v1/notebooks', json={'title': ' '}).status_code == 422
    assert client.post(path + '/cells', json={**payload, 'status': 'COMPLETED'}).status_code == 422
    assert client.post(path + '/cells', json={**payload, 'dataset_version_id': str(uuid4())}).status_code == 404
    assert client.post(path + '/cells', json={**payload, 'dataset_version_id': pending_id}).status_code == 409
    assert client.post(f'/api/v1/notebooks/{uuid4()}/cells', json=payload).status_code == 404
    assert len(client.get(path).json()['cells']) == 1
    with get_session_factory()() as session:
        for model, identity in ((DatasetVersion, version_id), (Notebook, notebook['id'])):
            try:
                with session.begin_nested():
                    session.execute(delete(model).where(model.id == identity))
            except IntegrityError:
                pass
            else:
                raise AssertionError('Referenced record deletion must fail')
    print('PASS: notebook persistence, exact version, isolation, validation, timestamps, restrictive references')


if __name__ == '__main__':
    main()
