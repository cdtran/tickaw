"""API persistence checks; run only via the disposable migration harness."""
from datetime import UTC, datetime
from uuid import uuid4

from app.db.session import get_session_factory
from app.main import app
from app.models import Dataset, DatasetVersion, Notebook
from app.services.llm_service import get_llm_gateway
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from packages.llm_gateway.contracts import ModelUsage, PlanResponse


class FakeGateway:
    def __init__(self):
        self.calls = []

    def generate_plan(self, stable_model_id, request):
        self.calls.append((stable_model_id, request))
        return PlanResponse(
            payload={
                "plan_version": 2,
                "dimensions": [],
                "metrics": [{"op": "count_rows", "alias": "row_count"}],
                "filters": [],
                "order_by": [],
                "limit": 100,
                "presentation": {"type": "table"},
            },
            stable_model_id=stable_model_id,
            provider="openai-compatible",
            provider_model="qwen-test",
            prompt_version=request.prompt_version,
            usage=ModelUsage(input_tokens=10, output_tokens=20),
        )


def main():
    client = TestClient(app)
    with get_session_factory()() as session:
        dataset = Dataset(name="Notebook fixture")
        session.add(dataset)
        session.flush()
        version = DatasetVersion(dataset_id=dataset.id, version_number=1, status="READY",
            original_filename="sales.csv", file_format="csv", storage_bucket="test",
            original_object_key=str(uuid4()), normalized_object_key=str(uuid4()),
            schema_json={
                "version": 1,
                "columns": [
                    {"name": "region", "inferred_type": "string", "pandas_dtype": "string"},
                    {"name": "revenue", "inferred_type": "number", "pandas_dtype": "Float64"},
                ],
            },
            profile_json={}, preview_json=[], row_count=0,
            completed_at=datetime.now(UTC))
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
    models = client.get("/api/v1/models")
    assert models.status_code == 200, models.text
    assert [model["id"] for model in models.json()] == ["qwen-local"]
    payload = {"question": " Revenue by region? ", "dataset_version_id": version_id,
               "stable_model_id": "qwen-local"}
    response = client.post(path + "/cells", json=payload)
    assert response.status_code == 201, response.text
    cell = response.json()
    assert cell['question'] == "Revenue by region?" and cell['status'] == "SAVED"
    assert cell['dataset_version_id'] == version_id
    assert cell['stable_model_id'] == 'qwen-local'
    assert cell['created_at'] and cell['updated_at']
    fake_gateway = FakeGateway()
    app.dependency_overrides[get_llm_gateway] = lambda: fake_gateway
    try:
        draft = client.post(path + f"/cells/{cell['id']}/analysis-runs")
    finally:
        app.dependency_overrides.pop(get_llm_gateway, None)
    assert draft.status_code == 202, draft.text
    assert draft.json()['status'] == 'QUEUED'
    assert draft.json()['stable_model_id'] == 'qwen-local'
    assert draft.json()['prompt_version'] == 'query-plan-v2.3'
    assert fake_gateway.calls[0][0] == 'qwen-local'
    submitted = fake_gateway.calls[0][1]
    assert submitted.question == 'Revenue by region?'
    assert [column['name'] for column in submitted.dataset_schema['columns']] == [
        'region', 'revenue'
    ]
    assert submitted.dataset_profile == {}
    assert submitted.response_schema['properties']['plan_version']['const'] == 2
    fake_gateway.calls.clear()
    original_generate = fake_gateway.generate_plan

    def invalid_column(stable_model_id, request):
        result = original_generate(stable_model_id, request)
        return result.model_copy(update={
            "payload": {
                **result.payload,
                "dimensions": ["invented_column"],
                "presentation": {"type": "bar"},
            }
        })

    fake_gateway.generate_plan = invalid_column
    app.dependency_overrides[get_llm_gateway] = lambda: fake_gateway
    try:
        invalid = client.post(path + f"/cells/{cell['id']}/analysis-runs")
    finally:
        app.dependency_overrides.pop(get_llm_gateway, None)
    assert invalid.status_code == 502, invalid.text
    assert invalid.json()['detail'] == 'The selected model could not generate a valid query plan.'
    assert len(fake_gateway.calls) == 2
    retry_feedback = fake_gateway.calls[1][1].validation_feedback or ''
    assert 'previous query plan was rejected' in retry_feedback
    assert 'invented_column' in retry_feedback
    # A new client/request/session models a reload, without in-memory UI state.
    loaded = TestClient(app).get(path).json()
    assert loaded['cells'][0]['id'] == cell['id']
    assert loaded['cells'][0]['latest_analysis']['id'] == draft.json()['id']
    assert loaded['updated_at'] >= notebook['updated_at']
    assert client.get(f"/api/v1/notebooks/{other['id']}").json()['cells'] == []
    assert notebook['id'] in [item['id'] for item in client.get('/api/v1/notebooks').json()]
    for question in ('', '   ', 'x' * 4001):
        assert client.post(path + '/cells', json={**payload, 'question': question}).status_code == 422
    assert client.post('/api/v1/notebooks', json={'title': ' '}).status_code == 422
    assert client.post(path + '/cells', json={**payload, 'status': 'COMPLETED'}).status_code == 422
    assert client.post(path + '/cells', json={**payload, 'dataset_version_id': str(uuid4())}).status_code == 404
    assert client.post(path + '/cells', json={**payload, 'dataset_version_id': pending_id}).status_code == 409
    assert client.post(path + '/cells', json={**payload, 'stable_model_id': 'missing'}).status_code == 422
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
