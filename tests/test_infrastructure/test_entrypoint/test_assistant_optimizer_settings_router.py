from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettings,
)
from src.application.ports.audit_port import AuditEntry
from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.use_cases.assistant_optimizer_settings import (
    GetAssistantOptimizerSettingsUseCase,
    ListAssistantOptimizerSettingsChangesUseCase,
    UpdateAssistantOptimizerSettingsUseCase,
)
from src.infrastructure.entrypoint.api.factories.assistant_optimizer_settings_factory import (
    get_get_assistant_optimizer_settings_use_case,
    get_list_assistant_optimizer_settings_changes_use_case,
    get_mature_sampler_schema_configuration_use_case,
    get_preview_mature_sample_use_case,
    get_update_assistant_optimizer_settings_use_case,
    get_update_mature_sampler_schema_configuration_use_case,
)
from src.infrastructure.entrypoint.api.routers.assistant_optimizer_settings_router import (
    router,
)
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user


class InMemorySettings:
    def __init__(self) -> None:
        self.value = AssistantOptimizerSettings()

    def get(self):
        return self.value

    def update(self, value):
        self.value = value
        return value


class InMemoryChanges:
    def __init__(self) -> None:
        self.values = []

    def append(self, change):
        self.values.append(change)

    def list(self, limit=50):
        return list(reversed(self.values))[:limit]


class InMemoryAudit:
    def __init__(self) -> None:
        self.values: list[AuditEntry] = []

    def write(self, entry):
        self.values.append(entry)


class InMemorySamplerFieldPool:
    def validate_selected_fields(self, selected_fields, compatible_versions):
        if set(selected_fields) - {"schema_feature"}:
            raise ValueError("Los campos deben seleccionarse del esquema compatible")

    def available_fields(self):
        return ["schema_feature"]


class InMemorySamplerSchemaConfiguration:
    def __init__(self):
        self.configuration = {
            "target_fields": [{"field": "schema_label", "type": "string", "description": ""}],
            "marking_date_fields": [{"field": "schema_marked_at", "type": "datetime", "description": ""}],
            "mapping": {
                "target_field": "",
                "marking_date_field": "",
                "label_value_mapping": {},
            },
        }

    def execute(self):
        return self.configuration


class InMemorySamplerSchemaConfigurationUpdater:
    def __init__(self, configuration):
        self.configuration = configuration

    def execute(self, proposed, *, changed_by):
        self.configuration.configuration["mapping"] = {
            "target_field": proposed.target_field,
            "marking_date_field": proposed.marking_date_field,
            "label_value_mapping": proposed.label_value_mapping,
        }
        return proposed


def _client(role: LocalRole = LocalRole.MANAGER):
    app = FastAPI()
    app.include_router(router)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    user = LocalUser(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        email="manager@example.com",
        name="Manager",
        password_hash="",
        role=role,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    settings = InMemorySettings()
    changes = InMemoryChanges()
    audit = InMemoryAudit()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_get_assistant_optimizer_settings_use_case] = (
        lambda: GetAssistantOptimizerSettingsUseCase(settings)
    )
    app.dependency_overrides[get_update_assistant_optimizer_settings_use_case] = (
        lambda: UpdateAssistantOptimizerSettingsUseCase(settings, changes, audit)
    )
    app.dependency_overrides[
        get_list_assistant_optimizer_settings_changes_use_case
    ] = lambda: ListAssistantOptimizerSettingsChangesUseCase(changes)
    app.dependency_overrides[get_preview_mature_sample_use_case] = (
        lambda: InMemorySamplerFieldPool()
    )
    schema_configuration = InMemorySamplerSchemaConfiguration()
    app.dependency_overrides[get_mature_sampler_schema_configuration_use_case] = (
        lambda: schema_configuration
    )
    app.dependency_overrides[get_update_mature_sampler_schema_configuration_use_case] = (
        lambda: InMemorySamplerSchemaConfigurationUpdater(schema_configuration)
    )
    return TestClient(app), settings, changes, audit


def test_manager_can_read_update_and_list_changes() -> None:
    client, _, changes, audit = _client()
    settings = client.get("/assistant-optimizer-settings")
    assert settings.status_code == 200
    payload = settings.json()
    payload["assistant_max_message_chars"] = 4_000

    updated = client.put("/assistant-optimizer-settings", json={"settings": payload})

    assert updated.status_code == 200
    assert updated.json()["assistant_max_message_chars"] == 4_000
    assert changes.values[0].changed_by == "manager@example.com"
    assert audit.values[0].action == "assistant_optimizer_settings.update"
    history = client.get("/assistant-optimizer-settings/changes")
    assert history.status_code == 200
    assert history.json()[0]["changes"][0]["path"] == "assistant_max_message_chars"


def test_release_manager_can_read_settings() -> None:
    client, _, _, _ = _client(LocalRole.RELEASE_MANAGER)
    assert client.get("/assistant-optimizer-settings").status_code == 200


def test_channel_manager_cannot_read_or_update_settings() -> None:
    client, _, _, _ = _client(LocalRole.CHANNEL_MANAGER)
    assert client.get("/assistant-optimizer-settings").status_code == 403
    values = {
        field.name: getattr(AssistantOptimizerSettings(), field.name)
        for field in fields(AssistantOptimizerSettings)
        if field.name not in {"maturing_days", "expected_coverage_pct", "stable_months"}
    }
    assert (
        client.put(
            "/assistant-optimizer-settings", json={"settings": values}
        ).status_code
        == 403
    )


def test_invalid_settings_return_422() -> None:
    client, _, changes, audit = _client()
    current = client.get("/assistant-optimizer-settings").json()
    current["assistant_max_message_chars"] = 8_001
    response = client.put("/assistant-optimizer-settings", json={"settings": current})
    assert response.status_code == 422
    assert changes.values == []
    assert audit.values == []


def test_partition_proportions_must_sum_to_one() -> None:
    client, _, _, _ = _client()
    current = client.get("/assistant-optimizer-settings").json()
    current["sampler_train_proportion"] = 0.7
    response = client.put("/assistant-optimizer-settings", json={"settings": current})
    assert response.status_code == 422


def test_sampler_fields_are_served_from_schema_pool_and_invalid_selection_is_rejected() -> None:
    client, _, _, _ = _client()
    assert client.get("/assistant-optimizer-settings/sampler/fields").json() == [
        "schema_feature"
    ]
    values = client.get("/assistant-optimizer-settings").json()
    values["sampler_strata"] = ["invented_column"]

    response = client.put(
        "/assistant-optimizer-settings", json={"settings": values}
    )

    assert response.status_code == 422


def test_manager_can_configure_target_label_date_and_value_mapping():
    client, _, _, _ = _client()
    config = client.get("/assistant-optimizer-settings/sampler/schema-configuration")
    assert config.status_code == 200
    assert config.json()["target_fields"][0]["field"] == "schema_label"
    response = client.put(
        "/assistant-optimizer-settings/sampler/schema-configuration",
        json={
            "target_field": "schema_label",
            "marking_date_field": "schema_marked_at",
            "label_value_mapping": {"f": "fraud", "n": "no_fraud"},
        },
    )
    assert response.status_code == 200
    assert response.json()["mapping"]["target_field"] == "schema_label"
    assert response.json()["mapping"]["label_value_mapping"] == {
        "f": "fraud",
        "n": "no_fraud",
    }
