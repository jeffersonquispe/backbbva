"""GET /metrics/technical: `monitor` permission, step_name/model query
params reach the use case as filters, unknown filters answer 422."""
from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

os.environ.setdefault("GENAI_ENVIRONMENT", "test")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.use_cases.metrics.get_technical_metrics import GetTechnicalMetrics
from src.infrastructure.entrypoint.api.factories.metrics_factory import (
    get_technical_metrics_use_case,
)
from src.infrastructure.entrypoint.api.routers import metrics_router
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user

NOW = datetime(2026, 10, 1, 15, 30, tzinfo=UTC)


class RecordingRollupRepository:
    def __init__(self) -> None:
        self.queries: list[tuple] = []

    def query(self, data_type, level, periods, filters=None):
        self.queries.append((data_type.value, level.value, tuple(periods), filters))
        return []


def _client(role: LocalRole, repository: RecordingRollupRepository) -> TestClient:
    app = FastAPI()
    app.include_router(metrics_router.router)
    user = LocalUser(
        id=uuid4(), email="u@x.co", name="u", password_hash="", role=role,
        is_active=True, created_at=NOW, updated_at=NOW,
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_technical_metrics_use_case] = lambda: GetTechnicalMetrics(
        repository, "America/Bogota", clock=lambda: NOW
    )
    return TestClient(app)


def test_requires_monitor_permission() -> None:
    response = _client(LocalRole.FRAUD_ANALYST, RecordingRollupRepository()).get("/metrics/technical")
    assert response.status_code == 403


def test_returns_the_technical_shape_and_pushes_filters_down() -> None:
    repository = RecordingRollupRepository()
    response = _client(LocalRole.DATA_ANALYST, repository).get(
        "/metrics/technical",
        params=[("channel", "WEB"), ("step_name", "classification"), ("model", "gpt-a")],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["range"]["from"].startswith("2026-09-30T15:30")
    assert len(body["hourly_profile"]) == 24
    assert body["evaluations"] == {"evaluated": 0, "hallucinations": 0, "data_use_correct": 0, "invalid": 0}
    assert body["llm_calls"]["latency"]["histogram"][0]["bucket"] == "dur_lt_1s"

    filters = {q[0]: q[3] for q in repository.queries}
    assert filters["llm_call"] == {"channel": ["WEB"], "step_name": ["classification"], "model": ["gpt-a"]}
    assert filters["workflow_step"] == {"channel": ["WEB"], "step_name": ["classification"]}
    assert filters["evaluation"] == {"channel": ["WEB"]}


def test_inverted_range_is_422() -> None:
    response = _client(LocalRole.MANAGER, RecordingRollupRepository()).get(
        "/metrics/technical",
        params={"from": "2026-10-01T10:00:00-05:00", "to": "2026-09-30T10:00:00-05:00"},
    )
    assert response.status_code == 422
