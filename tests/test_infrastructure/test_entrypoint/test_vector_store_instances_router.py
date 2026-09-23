"""Fast API-contract tests: no Docker, DynamoDB or OpenSearch required."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

os.environ.setdefault("GENAI_ENVIRONMENT", "test")
os.environ.setdefault("API_V0_STR", "/api/v0")

from fastapi import FastAPI
from fastapi.testclient import TestClient

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
    now = datetime.now(timezone.utc)
    return LocalUser(
        id=uuid4(), email="qa@aria.test", name="QA Analyst", password_hash="unused",
        role=role, is_active=True, created_at=now, updated_at=now,
    )


def _client(router, user: LocalUser) -> tuple[TestClient, FastAPI]:
    app = FastAPI()
    app.include_router(router, prefix="/api/v0")
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), app


class _CreateInstance:
    def execute(self, *, name: str, description: str, created_by: str, assets: list):
        return VectorStoreInstance(
            id="vector-store-v1", version=1, name=name, description=description,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), created_by=created_by,
        )


class _Graph:
    def preview_add(self, instance_id: str, asset_type: KnowledgeAssetType, asset_id: str):
        assert instance_id == "vector-store-v1"
        return [
            KnowledgeGraphImpact(asset_type, asset_id, "manual"),
            KnowledgeGraphImpact(KnowledgeAssetType.MODUS_OPERANDI, "mo-1", "inherited_from_taxonomy"),
        ]

    def attach(self, instance_id: str, asset_type: KnowledgeAssetType, asset_id: str):
        return [
            VectorStoreInstanceAsset(instance_id, asset_type, asset_id, 1),
            VectorStoreInstanceAsset(instance_id, KnowledgeAssetType.MODUS_OPERANDI, "mo-1", 1, origin="inherited_from_taxonomy"),
        ]


class _UpdateInstance:
    def execute(self, *args, **kwargs):
        return VectorStoreInstance(
            id="vector-store-v1", version=1, name="QA", description="",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), created_by="QA Analyst",
            updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc), updated_by="QA Analyst",
        )


def test_vector_store_write_requires_an_authorized_role() -> None:
    client, _ = _client(vector_store_instances_router.router, _user(LocalRole.FRAUD_ANALYST))

    response = client.post("/api/v0/vector-store-instances", json={"name": "QA", "description": ""})

    assert response.status_code == 403


def test_create_instance_uses_authenticated_user_for_audit() -> None:
    client, app = _client(vector_store_instances_router.router, _user())
    app.dependency_overrides[vector_store_instances_router.get_create_vector_store_instance_use_case] = lambda: _CreateInstance()

    response = client.post("/api/v0/vector-store-instances", json={"name": "QA", "description": "Control"})

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
        {"asset_type": "modus_operandi", "asset_id": "mo-1", "origin": "inherited_from_taxonomy"},
    ]


def test_add_document_persists_the_complete_graph_relation(monkeypatch) -> None:
    client, _ = _client(vector_store_instances_router.router, _user())
    monkeypatch.setattr(vector_store_instances_router, "_graph", lambda: _Graph())
    monkeypatch.setattr(vector_store_instances_router, "get_update_vector_store_instance_use_case", lambda: _UpdateInstance())

    response = client.post(
        "/api/v0/vector-store-instances/vector-store-v1/documents",
        json={"asset_type": "taxonomy", "asset_id": "tax-1"},
    )

    assert response.status_code == 201
    assert {(item["asset_type"], item["asset_id"]) for item in response.json()} == {
        ("taxonomy", "tax-1"), ("modus_operandi", "mo-1"),
    }


def test_children_cannot_be_deleted_through_the_public_api() -> None:
    for router_module, path, delete_dependency in (
        (modus_operandi_library_router, "/api/v0/library/modus-operandi/mo-1", modus_operandi_library_router.get_delete_modus_operandi_library_entry_use_case),
        (flag_library_router, "/api/v0/library/flags/flag-1", flag_library_router.get_delete_flag_library_entry_use_case),
        (similar_case_library_router, "/api/v0/library/similar-cases/case-1", similar_case_library_router.get_delete_similar_case_library_entry_use_case),
    ):
        client, app = _client(router_module.router, _user())
        app.dependency_overrides[delete_dependency] = lambda: object()
        response = client.delete(path)
        assert response.status_code == 405
