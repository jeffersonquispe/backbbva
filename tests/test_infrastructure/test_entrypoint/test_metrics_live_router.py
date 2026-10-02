"""GET /metrics/live: `dashboard` permission, current counts per live
state from the status index plus active voicebot calls."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

os.environ.setdefault("GENAI_ENVIRONMENT", "test")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.ports.alert_port import AlertStatus
from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.use_cases.metrics.get_live_alert_funnel import GetLiveAlertFunnel
from src.infrastructure.entrypoint.api.factories.metrics_factory import (
    get_live_alert_funnel_use_case,
)
from src.infrastructure.entrypoint.api.routers import metrics_router
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user

NOW = datetime(2026, 10, 1, 15, 30, tzinfo=timezone.utc)


class InMemoryAlertCounts:
    def __init__(self, counts: dict[AlertStatus, int]) -> None:
        self._counts = counts

    def count_by_status(self, status: AlertStatus) -> int:
        return self._counts.get(status, 0)


class InMemoryReservations:
    def __init__(self, active_voicebot: int) -> None:
        self._active = active_voicebot

    def list_active(self, resource, now):
        return [object()] * self._active


def _client(role: LocalRole) -> TestClient:
    app = FastAPI()
    app.include_router(metrics_router.router)
    user = LocalUser(
        id=uuid4(), email="u@x.co", name="u", password_hash="", role=role,
        is_active=True, created_at=NOW, updated_at=NOW,
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_live_alert_funnel_use_case] = lambda: GetLiveAlertFunnel(
        InMemoryAlertCounts(
            {AlertStatus.RECEIVED: 3, AlertStatus.PROCESSING: 2, AlertStatus.ESCALATED: 5}
        ),
        InMemoryReservations(active_voicebot=1),
        clock=lambda: NOW,
    )
    return TestClient(app)


def test_requires_dashboard_permission() -> None:
    assert _client(LocalRole.FRAUD_ANALYST).get("/metrics/live").status_code == 403


def test_returns_current_counts() -> None:
    response = _client(LocalRole.MANAGER).get("/metrics/live")
    assert response.status_code == 200
    body = response.json()
    assert body["received"] == 3
    assert body["processing"] == 2
    assert body["escalated"] == 5
    assert body["voicebot_in_call"] == 1
    assert body["measured_at"].startswith("2026-10-01T15:30")
