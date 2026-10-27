"""Fast API-contract tests: no Docker, DynamoDB or OpenSearch required."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

os.environ.setdefault("GENAI_ENVIRONMENT", "test")
os.environ.setdefault("API_V0_STR", "/api/v0")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FraudKnowledgeSearchResult,
    SearchPipeline,
    TaxonomiaDocument,
)
from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.ports.vector_store_instance_port import (
    KnowledgeAssetType,
    VectorStoreInstance,
    VectorStoreInstanceAsset,
)
from src.application.use_cases.vector_store_instances.knowledge_graph import (
    KnowledgeGraphImpact,
)
from src.infrastructure.entrypoint.api.routers import (
    flag_library_router,
    modus_operandi_library_router,
    similar_case_library_router,
    vector_store_instances_router,
)
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user


def _user(role: LocalRole = LocalRole.DATA_ANALYST) -> LocalUser:
    now = datetime.now(UTC)
    return LocalUser(
        id=uuid4(),
        email="qa@aria.test",
        name="QA Analyst",
        password_hash="unused",
        role=role,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def _client(router, user: LocalUser) -> tuple[TestClient, FastAPI]:
    app = FastAPI()
    app.include_router(router, prefix="/api/v0")
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), app


class _CreateInstance:
    def execute(self, *, name: str, description: str, created_by: str, assets: list):
        return VectorStoreInstance(
            id="vector-store-v1",
            version=1,
            name=name,
            description=description,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            created_by=created_by,
        )


class _Graph:
    def preview_add(
        self, instance_id: str, asset_type: KnowledgeAssetType, asset_id: str
    ):
        assert instance_id == "vector-store-v1"
        return [
            KnowledgeGraphImpact(asset_type, asset_id, "manual"),
            KnowledgeGraphImpact(
                KnowledgeAssetType.MODUS_OPERANDI, "mo-1", "inherited_from_taxonomy"
            ),
        ]

    def attach(self, instance_id: str, asset_type: KnowledgeAssetType, asset_id: str):
        return [
            VectorStoreInstanceAsset(instance_id, asset_type, asset_id, 1),
            VectorStoreInstanceAsset(
                instance_id,
                KnowledgeAssetType.MODUS_OPERANDI,
                "mo-1",
                1,
                origin="inherited_from_taxonomy",
            ),
        ]


class _UpdateInstance:
    def execute(self, *args, **kwargs):
        return VectorStoreInstance(
            id="vector-store-v1",
            version=1,
            name="QA",
            description="",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            created_by="QA Analyst",
            updated_at=datetime(2026, 1, 2, tzinfo=UTC),
            updated_by="QA Analyst",
        )


class _SearchKnowledge:
    def __init__(self, hits):
        self.hits = hits
        self.call = None

    def execute(self, query, **kwargs):
        self.call = (query, kwargs)
        return self.hits


def test_vector_store_write_requires_an_authorized_role() -> None:
    client, _ = _client(
        vector_store_instances_router.router, _user(LocalRole.FRAUD_ANALYST)
    )

    response = client.post(
        "/api/v0/vector-store-instances", json={"name": "QA", "description": ""}
    )

    assert response.status_code == 403


def test_create_instance_uses_authenticated_user_for_audit() -> None:
    client, app = _client(vector_store_instances_router.router, _user())
    app.dependency_overrides[
        vector_store_instances_router.get_create_vector_store_instance_use_case
    ] = lambda: _CreateInstance()

    response = client.post(
        "/api/v0/vector-store-instances", json={"name": "QA", "description": "Control"}
    )

    assert response.status_code == 201
    assert response.json()["created_by"] == "QA Analyst"
    assert response.json()["id"] == "vector-store-v1"


def test_preflight_reports_the_recursive_impact(monkeypatch) -> None:
    client, _ = _client(vector_store_instances_router.router, _user())
    monkeypatch.setattr(vector_store_instances_router, "_graph", lambda: _Graph())

    response = client.post(
        "/api/v0/vector-store-instances/vector-store-v1/documents/preflight",
        json={"asset_type": "taxonomy", "asset_id": "tax-1"},
    )

    assert response.status_code == 200
    assert response.json()["will_add"] == [
        {"asset_type": "taxonomy", "asset_id": "tax-1", "origin": "manual"},
        {
            "asset_type": "modus_operandi",
            "asset_id": "mo-1",
            "origin": "inherited_from_taxonomy",
        },
    ]


def test_add_document_persists_the_complete_graph_relation(monkeypatch) -> None:
    client, _ = _client(vector_store_instances_router.router, _user())
    monkeypatch.setattr(vector_store_instances_router, "_graph", lambda: _Graph())
    monkeypatch.setattr(
        vector_store_instances_router,
        "get_update_vector_store_instance_use_case",
        lambda: _UpdateInstance(),
    )

    response = client.post(
        "/api/v0/vector-store-instances/vector-store-v1/documents",
        json={"asset_type": "taxonomy", "asset_id": "tax-1"},
    )

    assert response.status_code == 201
    assert {(item["asset_type"], item["asset_id"]) for item in response.json()} == {
        ("taxonomy", "tax-1"),
        ("modus_operandi", "mo-1"),
    }


def test_children_cannot_be_deleted_through_the_public_api() -> None:
    for router_module, path, delete_dependency in (
        (
            modus_operandi_library_router,
            "/api/v0/library/modus-operandi/mo-1",
            modus_operandi_library_router.get_delete_modus_operandi_library_entry_use_case,
        ),
        (
            flag_library_router,
            "/api/v0/library/flags/flag-1",
            flag_library_router.get_delete_flag_library_entry_use_case,
        ),
        (
            similar_case_library_router,
            "/api/v0/library/similar-cases/case-1",
            similar_case_library_router.get_delete_similar_case_library_entry_use_case,
        ),
    ):
        client, app = _client(router_module.router, _user())
        app.dependency_overrides[delete_dependency] = lambda: object()
        response = client.delete(path)
        assert response.status_code == 405


def test_query_instance_uses_requested_pipeline_and_returns_active_generation(monkeypatch) -> None:
    client, _ = _client(vector_store_instances_router.router, _user())
    document = TaxonomiaDocument(
        id=uuid4(),
        text="Fraude por cambio de dispositivo",
        text_embedded=[0.1, 0.2],
        vector_store_id="vector-store-v1",
        vector_store_version=3,
    )
    search = _SearchKnowledge([FraudKnowledgeSearchResult(document, 1.25)])
    monkeypatch.setattr(
        vector_store_instances_router,
        "get_search_fraud_knowledge_use_case",
        lambda: search,
    )

    response = client.get(
        "/api/v0/vector-store-instances/vector-store-v1/query",
        params={
            "query": "acceso desde un móvil nuevo",
            "document_type": "taxonomia",
            "pipeline": "embedding_heavy",
            "top_k": 7,
        },
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(document.id),
            "type": "taxonomia",
            "text": document.text,
            "score": 1.25,
            "vector_store_id": "vector-store-v1",
            "vector_store_version": 3,
        }
    ]
    assert search.call == (
        "acceso desde un móvil nuevo",
        {
            "pipeline": SearchPipeline.EMBEDDING_HEAVY,
            "vector_store_generation": None,
            "vector_store_id": "vector-store-v1",
            "document_type": DocumentType.TAXONOMIA,
            "top_k": 7,
        },
    )


def test_query_instance_rejects_invalid_pipeline_and_limits(monkeypatch) -> None:
    client, _ = _client(vector_store_instances_router.router, _user())
    monkeypatch.setattr(
        vector_store_instances_router,
        "get_search_fraud_knowledge_use_case",
        lambda: _SearchKnowledge([]),
    )

    invalid_pipeline = client.get(
        "/api/v0/vector-store-instances/vector-store-v1/query",
        params={"query": "fraude", "pipeline": "unknown"},
    )
    excessive_top_k = client.get(
        "/api/v0/vector-store-instances/vector-store-v1/query",
        params={"query": "fraude", "top_k": 51},
    )

    assert invalid_pipeline.status_code == 422
    assert excessive_top_k.status_code == 422


# --- generations: build never publishes, list reports production usage -----


def _generation(number: int, status: str = "ready", fingerprint: str = "fp"):
    from src.domain.fraud_knowledge.vector_store_generations import (
        VectorStoreGeneration,
        VectorStoreGenerationStatus,
    )

    return VectorStoreGeneration(
        instance_id="vector-store-v1",
        generation=number,
        status=VectorStoreGenerationStatus(status),
        built_by="QA Analyst",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        fingerprint=fingerprint,
        document_count=4,
    )


class _ListUseCase:
    def __init__(self, views) -> None:
        self.views = views

    def generations(self, instance_id: str):
        assert instance_id == "vector-store-v1"
        return self.views


class _InstanceRepository:
    def get(self, instance_id: str):
        if instance_id != "vector-store-v1":
            return None
        return _UpdateInstance().execute()


class _BuildUseCase:
    def __init__(self, result=None, error: Exception | None = None, fingerprint="fp"):
        self.result = result
        self.error = error
        self._fingerprint = fingerprint
        self.calls: list[tuple[str, str]] = []

    def execute(self, instance_id: str, *, actor: str):
        self.calls.append((instance_id, actor))
        if self.error is not None:
            raise self.error
        return self.result

    def fingerprint(self, instance_id: str) -> str:
        return self._fingerprint


def _generations_client(monkeypatch, role, views, build):
    from src.infrastructure.entrypoint.api.factories.vector_store_instance_factory import (
        get_build_vector_store_generation_use_case,
    )

    client, app = _client(vector_store_instances_router.router, _user(role))
    app.dependency_overrides[get_build_vector_store_generation_use_case] = lambda: build
    monkeypatch.setattr(
        vector_store_instances_router,
        "get_list_vector_store_instances_use_case",
        lambda: _ListUseCase(views),
    )
    monkeypatch.setattr(
        vector_store_instances_router,
        "get_vector_store_instance_repository",
        lambda: _InstanceRepository(),
    )
    monkeypatch.setattr(
        vector_store_instances_router,
        "get_build_vector_store_generation_use_case",
        lambda: build,
    )
    return client


def test_build_generation_returns_it_without_publishing(monkeypatch) -> None:
    from src.application.use_cases.vector_store_instances.build_vector_store_generation import (
        BuildVectorStoreGenerationOutput,
    )
    from src.application.use_cases.vector_store_instances.list_vector_store_instances import (
        VectorStoreGenerationView,
    )

    built = _generation(2)
    build = _BuildUseCase(BuildVectorStoreGenerationOutput(built, built=True))
    views = [
        VectorStoreGenerationView(built, in_production=False),
        VectorStoreGenerationView(_generation(1), in_production=True, pinned_by=("cfg@v3",)),
    ]
    client = _generations_client(monkeypatch, LocalRole.DATA_ANALYST, views, build)

    response = client.post("/api/v0/vector-store-instances/vector-store-v1/generations")

    assert response.status_code == 200
    body = response.json()
    assert (body["generation"], body["status"], body["built"]) == (2, "ready", True)
    # Building is not publishing: the new generation is not what production uses.
    assert body["in_production"] is False
    assert build.calls == [("vector-store-v1", "QA Analyst")]


def test_list_generations_reports_production_pins_and_manifest_drift(monkeypatch) -> None:
    from src.application.use_cases.vector_store_instances.list_vector_store_instances import (
        VectorStoreGenerationView,
    )

    views = [
        VectorStoreGenerationView(_generation(2, fingerprint="old"), in_production=False),
        VectorStoreGenerationView(
            _generation(1, "retired", fingerprint="older"), in_production=False
        ),
    ]
    client = _generations_client(
        monkeypatch, LocalRole.MANAGER, views, _BuildUseCase(fingerprint="current")
    )

    response = client.get("/api/v0/vector-store-instances/vector-store-v1/generations")

    assert response.status_code == 200
    assert [(item["generation"], item["status"], item["matches_manifest"]) for item in response.json()] == [
        (2, "ready", False),
        (1, "retired", False),
    ]
    assert client.get("/api/v0/vector-store-instances/missing/generations").status_code == 404


def test_build_generation_maps_errors_and_requires_writer(monkeypatch) -> None:
    from src.application.errors import ConflictError
    from src.application.use_cases.vector_store_instances.build_vector_store_generation import (
        EmptyVectorStoreInstanceError,
    )
    from src.application.use_cases.vector_store_instances.manage_vector_store_instance import (
        VectorStoreInstanceNotFoundError,
    )

    path = "/api/v0/vector-store-instances/vector-store-v1/generations"
    build = _BuildUseCase()
    client = _generations_client(monkeypatch, LocalRole.CHANNEL_MANAGER, [], build)
    for error, expected in (
        (EmptyVectorStoreInstanceError("empty"), 422),
        (ConflictError("already building"), 409),
        (VectorStoreInstanceNotFoundError("missing"), 404),
    ):
        build.error = error
        assert client.post(path).status_code == expected

    build = _BuildUseCase(error=AssertionError("must not build"))
    forbidden = _generations_client(monkeypatch, LocalRole.FRAUD_ANALYST, [], build)
    assert forbidden.post(path).status_code == 403
    assert forbidden.get(path).status_code == 403
    assert build.calls == []


def test_promote_endpoint_no_longer_exists() -> None:
    client, _ = _client(vector_store_instances_router.router, _user(LocalRole.MANAGER))
    response = client.post("/api/v0/vector-store-instances/vector-store-v1/promote")
    assert response.status_code in {404, 405}


def test_query_unavailable_generation_is_a_conflict(monkeypatch) -> None:
    from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
        VectorStoreGenerationUnavailableError,
    )

    class _Retired:
        def execute(self, query, **kwargs):
            assert kwargs["vector_store_generation"] == 1
            raise VectorStoreGenerationUnavailableError("generation 1 is retired")

    client, _ = _client(vector_store_instances_router.router, _user())
    monkeypatch.setattr(
        vector_store_instances_router, "get_search_fraud_knowledge_use_case", _Retired
    )
    response = client.get(
        "/api/v0/vector-store-instances/vector-store-v1/query",
        params={"query": "phishing", "generation": 1},
    )
    assert response.status_code == 409
