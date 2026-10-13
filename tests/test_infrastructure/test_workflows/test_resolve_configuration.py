from __future__ import annotations

from datetime import UTC, datetime

import pytest

import src.infrastructure.workflows.celery.review_intake_steps as workflow_module
from src.domain.configurations.entities import (
    ConfigurationRecord,
    GeneralSettings,
    InfraSettings,
    TestSettings,
)
from src.domain.configurations.exceptions import ConfigurationNotFoundError


class InMemoryConfigurationRepository:
    def __init__(self, items: list[ConfigurationRecord]) -> None:
        self._items = {(c.configuration_id, c.version): c for c in items}

    def get(self, configuration_id: str, version: int) -> ConfigurationRecord | None:
        return self._items.get((configuration_id, version))

    def get_latest_version(self, configuration_id: str) -> ConfigurationRecord | None:
        versions = [c for (cid, _), c in self._items.items() if cid == configuration_id]
        return max(versions, key=lambda c: c.version) if versions else None

    def get_active(self) -> ConfigurationRecord | None:
        for c in self._items.values():
            if c.active:
                return c
        return None


def _config(configuration_id: str, version: int, active: bool) -> ConfigurationRecord:
    now = datetime.now(UTC)
    return ConfigurationRecord(
        configuration_id=configuration_id,
        version=version,
        name=f"{configuration_id}-v{version}",
        description="",
        active=active,
        general=GeneralSettings(),
        infra=InfraSettings(),
        test=TestSettings(),
        created_at=now,
        updated_at=now,
    )


def test_resolve_configuration_uses_active_when_no_ref_given(monkeypatch) -> None:
    active = _config("cfg-active", 1, active=True)
    repo = InMemoryConfigurationRepository([active])
    monkeypatch.setattr(workflow_module, "get_configuration_repository", lambda: repo)

    resolved = workflow_module._resolve_configuration({"input": {}})

    assert resolved is active


def test_resolve_configuration_pins_specific_inactive_version_when_ref_given(
    monkeypatch,
) -> None:
    active = _config("cfg-active", 1, active=True)
    pinned = _config("cfg-under-test", 3, active=False)
    repo = InMemoryConfigurationRepository([active, pinned])
    monkeypatch.setattr(workflow_module, "get_configuration_repository", lambda: repo)

    context = {
        "input": {
            "configuration_ref": {"configuration_id": "cfg-under-test", "version": 3}
        }
    }
    resolved = workflow_module._resolve_configuration(context)

    assert resolved is pinned


def test_resolve_configuration_raises_when_ref_does_not_resolve(monkeypatch) -> None:
    repo = InMemoryConfigurationRepository([])
    monkeypatch.setattr(workflow_module, "get_configuration_repository", lambda: repo)

    context = {
        "input": {"configuration_ref": {"configuration_id": "missing", "version": 1}}
    }

    with pytest.raises(ConfigurationNotFoundError):
        workflow_module._resolve_configuration(context)
