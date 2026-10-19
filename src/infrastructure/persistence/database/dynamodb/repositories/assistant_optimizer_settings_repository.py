from __future__ import annotations

import json
from dataclasses import asdict, fields
from datetime import datetime
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Key

from src.application.ports.assistant_optimizer_settings_changes_port import (
    AssistantOptimizerSettingChange,
    AssistantOptimizerSettingsChange,
    AssistantOptimizerSettingsChangesPort,
)
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettings,
    AssistantOptimizerSettingsPort,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

SETTINGS_TABLE_NAME = "assistant_optimizer_settings"
CHANGES_TABLE_NAME = "assistant_optimizer_settings_changes"
SETTINGS_RECORD_ID = "current"
_NON_PERSISTED_FIELDS = {"maturing_days", "expected_coverage_pct", "stable_months"}


class DynamoAssistantOptimizerSettingsRepository(
    AssistantOptimizerSettingsPort, AssistantOptimizerSettingsChangesPort
):
    def __init__(self) -> None:
        resource = get_dynamodb_resource()
        self._settings = resource.Table(SETTINGS_TABLE_NAME)
        self._changes = resource.Table(CHANGES_TABLE_NAME)

    def get(self) -> AssistantOptimizerSettings:
        item = self._settings.get_item(Key={"record_id": SETTINGS_RECORD_ID}).get("Item")
        return _from_item(item) if item else AssistantOptimizerSettings()

    def update(
        self, settings: AssistantOptimizerSettings
    ) -> AssistantOptimizerSettings:
        self._settings.put_item(Item=_to_item(settings))
        return settings

    def append(self, change: AssistantOptimizerSettingsChange) -> None:
        self._changes.put_item(Item=_change_to_item(change))

    def list(self, limit: int = 50) -> list[AssistantOptimizerSettingsChange]:
        response = self._changes.query(
            KeyConditionExpression=Key("record_id").eq(SETTINGS_RECORD_ID),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [_change_from_item(item) for item in response.get("Items", [])]


def _to_item(settings: AssistantOptimizerSettings) -> dict[str, Any]:
    payload = {
        field.name: getattr(settings, field.name)
        for field in fields(settings)
        if field.name not in _NON_PERSISTED_FIELDS
    }
    return {"record_id": SETTINGS_RECORD_ID, **_to_dynamo(payload)}


def _to_dynamo(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, tuple):
        return [_to_dynamo(item) for item in value]
    if isinstance(value, list):
        return [_to_dynamo(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_dynamo(item) for key, item in value.items()}
    return value


def _from_item(item: dict[str, Any]) -> AssistantOptimizerSettings:
    defaults = AssistantOptimizerSettings()
    values: dict[str, Any] = {}
    for field in fields(defaults):
        if field.name in _NON_PERSISTED_FIELDS:
            continue
        value = item.get(field.name, getattr(defaults, field.name))
        default = getattr(defaults, field.name)
        if isinstance(default, bool):
            value = bool(value)
        elif isinstance(default, float):
            value = float(value)
        elif isinstance(default, int):
            value = int(value)
        elif isinstance(default, tuple):
            value = tuple(value or ())
        values[field.name] = value
    return AssistantOptimizerSettings(**values)


def _change_to_item(change: AssistantOptimizerSettingsChange) -> dict[str, Any]:
    return {
        "record_id": SETTINGS_RECORD_ID,
        "changed_at": change.changed_at.isoformat(),
        "id": change.id,
        "changed_by": change.changed_by,
        "changes_json": json.dumps(
            [asdict(entry) for entry in change.changes],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }


def _change_from_item(item: dict[str, Any]) -> AssistantOptimizerSettingsChange:
    return AssistantOptimizerSettingsChange(
        id=str(item["id"]),
        changed_by=str(item["changed_by"]),
        changed_at=datetime.fromisoformat(str(item["changed_at"])),
        changes=[
            AssistantOptimizerSettingChange(**entry)
            for entry in json.loads(item.get("changes_json", "[]"))
        ],
    )
