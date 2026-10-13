"""D6: reasoning_evaluation_sample_rate in OperationalSettings - validated
0..1 at the API, persisted through the DynamoDB item mapping."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.ports.operational_settings_port import OperationalSettings
from src.application.use_cases.operational_settings.update_operational_settings import (
    UpdateOperationalSettingsUseCase,
)
from src.infrastructure.entrypoint.api.factories.operational_settings_factory import (
    get_update_operational_settings_use_case,
)
from src.infrastructure.entrypoint.api.routers.operational_settings_router import router
from src.infrastructure.persistence.database.dynamodb.repositories.operational_settings_repository import (
    _from_item,
    _to_item,
)


class InMemoryOperationalSettingsRepository:
    def __init__(self) -> None:
        self.settings = OperationalSettings()
        self.history: list = []

    def get(self) -> OperationalSettings:
        return self.settings

    def update(self, settings, change):
        self.settings = settings
        self.history.append(change)
        return settings

    def list_changes(self, limit: int = 50):
        return list(reversed(self.history))[:limit]


def _client(repository) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_update_operational_settings_use_case] = (
        lambda: UpdateOperationalSettingsUseCase(repository)
    )
    return TestClient(app)


def test_default_is_small_and_round_trips() -> None:
    assert OperationalSettings().reasoning_evaluation_sample_rate == 0.05
    item = _to_item(OperationalSettings(reasoning_evaluation_sample_rate=0.25))
    assert _from_item(item).reasoning_evaluation_sample_rate == 0.25
    # Items written before the field existed read the default.
    item.pop("reasoning_evaluation_sample_rate")
    assert _from_item(item).reasoning_evaluation_sample_rate == 0.05


def test_rate_out_of_range_is_422_and_zero_is_accepted() -> None:
    repository = InMemoryOperationalSettingsRepository()
    client = _client(repository)
    assert (
        client.put(
            "/operational-settings",
            json={"settings": {"reasoning_evaluation_sample_rate": 1.5}},
        ).status_code
        == 422
    )
    response = client.put(
        "/operational-settings",
        json={"settings": {"reasoning_evaluation_sample_rate": 0}},
    )
    assert response.status_code == 200
    assert response.json()["reasoning_evaluation_sample_rate"] == 0
    assert repository.settings.reasoning_evaluation_sample_rate == 0
