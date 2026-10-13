from copy import deepcopy
from dataclasses import asdict
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.application.ports.model_port import ModelRecord, ModelStatus
from src.application.use_cases.models.feature_engineering import (
    FeatureTemplatesUseCase,
    PreviewFeaturesUseCase,
)
from src.domain.models.feature_recipe import describe_capabilities
from src.infrastructure.entrypoint.api.factories.model_factory import (
    get_feature_templates_use_case,
    get_preview_features_use_case,
)
from src.infrastructure.entrypoint.api.routers.models_router import router
from src.infrastructure.entrypoint.api.schemas import CreateModelRequest
from src.infrastructure.persistence.database.dynamodb.repositories.model_repository import (
    _from_item,
    _to_item,
)


def configuration():
    return {"schema_version": 1, "mappings": {}, "recipes": [{"id": "amount", "name": "amount_numeric", "source": "current", "path": "transaction.amount", "output_type": "number", "steps": []}]}


class InMemoryTemplates:
    def __init__(self):
        self.items = {}

    def create(self, item):
        self.items[item.id] = deepcopy(item)
        return item

    def list(self):
        return list(self.items.values())

    def delete(self, identifier):
        self.items.pop(identifier, None)


def client():
    app = FastAPI()
    app.include_router(router)
    templates = FeatureTemplatesUseCase(InMemoryTemplates())
    app.dependency_overrides[get_feature_templates_use_case] = lambda: templates
    app.dependency_overrides[get_preview_features_use_case] = lambda: PreviewFeaturesUseCase()
    return TestClient(app)


def test_static_feature_routes_precede_dynamic_model_lookup_and_work(monkeypatch):
    from src.infrastructure.entrypoint.api.routers import models_router

    class QueuedTask:
        id = "preview-task"

    monkeypatch.setattr(models_router.celery_app, "send_task", lambda *args, **kwargs: QueuedTask())
    paths = [route.path for route in router.routes]
    assert paths.index("/models/features/operations") < paths.index("/models/{model_id}")
    assert paths.index("/models/features/preview") < paths.index("/models/{model_id}")
    assert paths.index("/models/feature-templates") < paths.index("/models/{model_id}")
    with client() as api:
        assert api.get("/models/feature-templates").json() == []
        created = api.post("/models/feature-templates", json={"name": "Amount", "configuration": configuration()})
        assert created.status_code == 201
        saved = created.json()
        assert api.get("/models/feature-templates").json()[0]["id"] == saved["id"]
        result = api.post("/models/features/preview", json={"configuration": saved["configuration"], "rows": [{"transaction": {"amount": 30}}]})
        assert result.status_code == 202
        assert result.json() == {"task_id": "preview-task", "status": "PENDING"}
        assert api.delete(f"/models/feature-templates/{saved['id']}").status_code == 204
        assert api.get("/models/feature-templates").json() == []
        assert api.post("/models/features/preview", json={"configuration": configuration(), "rows": []}).status_code == 422
        invalid = configuration()
        invalid["schema_version"] = 999
        assert api.post("/models/feature-templates", json={"name": "Invalid", "configuration": invalid}).status_code == 422


def test_feature_operations_endpoint_publishes_domain_capabilities():
    with client() as api:
        response = api.get("/models/features/operations")
        assert response.status_code == 200
        assert response.json() == describe_capabilities()


def request_args():
    return dict(tag="v1", dataset_name="sample", target_field="label", positive_labels=["risk"], feature_configuration=configuration())


def test_recipe_only_schema_and_persistence_roundtrip():
    request = CreateModelRequest(**request_args())
    assert request.feature_transforms == []
    record = ModelRecord(id=uuid4(), tag="v1", description="", status=ModelStatus.DRAFT, dataset_name="sample", target_field="label", feature_configuration=request.feature_configuration)
    assert asdict(_from_item(_to_item(record))) == asdict(record)
    legacy = _to_item(record)
    legacy.pop("feature_configuration")
    assert _from_item(legacy).feature_configuration is None


@pytest.mark.parametrize("path", ["label", "label.nested"])
def test_schema_rejects_target_leakage(path):
    args = request_args()
    args["feature_configuration"]["recipes"][0]["path"] = path
    with pytest.raises(ValidationError):
        CreateModelRequest(**args)


def test_schema_rejects_collision_with_legacy_feature():
    args = request_args()
    args["feature_transforms"] = [{"field": "amount_numeric", "kind": "numeric"}]
    with pytest.raises(ValidationError):
        CreateModelRequest(**args)


def test_preview_rejects_target_leakage_when_target_is_provided():
    config = configuration()
    config["recipes"][0]["path"] = "label"
    with client() as api:
        result = api.post("/models/features/preview", json={"configuration": config, "target_field": "label", "rows": [{"label": 1}]})
        assert result.status_code == 422


def test_preview_validation_identifies_the_invalid_mapping():
    config = configuration()
    config["recipes"].append(
        {
            "id": "employee_flag",
            "name": "Empleado banco",
            "source": "current",
            "path": "employee",
            "output_type": "boolean",
            "missing": {"policy": "constant", "value": 0},
            "steps": [],
        }
    )
    with client() as api:
        result = api.post("/models/features/preview", json={"configuration": config, "rows": [{"employee": "yes"}]})
    assert result.status_code == 422
    assert result.json()["detail"] == {
        "code": "invalid_feature_recipe",
        "recipe_id": "employee_flag",
        "recipe_name": "Empleado banco",
        "field": "missing.value",
        "message": "Missing constant must match boolean output_type",
    }


def test_preview_poll_returns_pending_ready_and_failed(monkeypatch):
    from celery import states

    from src.infrastructure.entrypoint.api.routers import models_router

    class Result:
        def __init__(self, state, result=None):
            self.state = state
            self.result = result

    with client() as api:
        monkeypatch.setattr(models_router, "AsyncResult", lambda *_, **__: Result(states.STARTED))
        assert api.get("/models/features/preview/task").json() == {"task_id": "task", "status": "PENDING", "result": None, "error": None}
        monkeypatch.setattr(models_router, "AsyncResult", lambda *_, **__: Result(states.SUCCESS, {"rows": []}))
        assert api.get("/models/features/preview/task").json() == {"task_id": "task", "status": "READY", "result": {"rows": []}, "error": None}
        monkeypatch.setattr(models_router, "AsyncResult", lambda *_, **__: Result(states.FAILURE, "bad recipe"))
        assert api.get("/models/features/preview/task").json() == {"task_id": "task", "status": "FAILED", "result": None, "error": "bad recipe"}
