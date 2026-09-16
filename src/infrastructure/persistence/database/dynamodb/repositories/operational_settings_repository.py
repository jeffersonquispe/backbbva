from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from boto3.dynamodb.conditions import Key

from src.application.ports.configuration_port import AnalystCapacity, TestCleanupPolicy
from src.application.ports.operational_settings_port import (
    OperationalSettings,
    OperationalSettingsChange,
    OperationalSettingsRepository,
    SettingChange,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.repositories.configuration_repository import (
    _day_profile_from_item,
    _shortage_behavior_from_item,
)

SETTINGS_TABLE_NAME = "operational_settings"
HISTORY_TABLE_NAME = "operational_settings_history"
SETTINGS_RECORD_ID = "current"


class DynamoOperationalSettingsRepository(OperationalSettingsRepository):
    def __init__(self) -> None:
        resource = get_dynamodb_resource()
        self._settings = resource.Table(SETTINGS_TABLE_NAME)
        self._history = resource.Table(HISTORY_TABLE_NAME)

    def get(self) -> OperationalSettings:
        item = self._settings.get_item(Key={"record_id": SETTINGS_RECORD_ID}).get(
            "Item"
        )
        return _from_item(item) if item else OperationalSettings()

    def update(
        self, settings: OperationalSettings, change: OperationalSettingsChange
    ) -> OperationalSettings:
        self._settings.put_item(Item=_to_item(settings))
        self._history.put_item(Item=_change_to_item(change))
        return settings

    def list_changes(self, limit: int = 50) -> list[OperationalSettingsChange]:
        response = self._history.query(
            KeyConditionExpression=Key("record_id").eq(SETTINGS_RECORD_ID),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [_change_from_item(item) for item in response.get("Items", [])]


def _to_item(settings: OperationalSettings) -> dict[str, Any]:
    payload = asdict(settings)
    # DynamoDB map keys must be strings - AnalystCapacity.day_overrides is
    # keyed by int (day of month) on the domain type, same handling as
    # configuration_repository.py's _operations_payload.
    payload["analyst_capacity"]["day_overrides"] = {
        str(day): profile_id
        for day, profile_id in payload["analyst_capacity"]["day_overrides"].items()
    }
    return {"record_id": SETTINGS_RECORD_ID, **payload}


def _from_item(item: dict[str, Any]) -> OperationalSettings:
    capacity_item = item.get("analyst_capacity") or {}
    return OperationalSettings(
        agent_enabled=bool(item.get("agent_enabled", True)),
        analyst_escalation_enabled=bool(
            item.get("analyst_escalation_enabled", True)
        ),
        voicebot_escalation_enabled=bool(
            item.get("voicebot_escalation_enabled", True)
        ),
        max_instances=int(item.get("max_instances", 8)),
        auto_scale=bool(item.get("auto_scale", True)),
        voicebot_max_concurrent_calls=int(
            item.get("voicebot_max_concurrent_calls", 40)
        ),
        voicebot_shortage_behavior=_shortage_behavior_from_item(
            item.get("voicebot_shortage_behavior") or {}
        ),
        analyst_capacity=AnalystCapacity(
            profiles=[
                _day_profile_from_item(p) for p in capacity_item.get("profiles") or []
            ],
            default_profile_id=capacity_item.get("default_profile_id") or "regular",
            day_overrides={
                int(day): profile_id
                for day, profile_id in (
                    capacity_item.get("day_overrides") or {}
                ).items()
            },
        ),
        analyst_shortage_behavior=_shortage_behavior_from_item(
            item.get("analyst_shortage_behavior") or {}
        ),
        max_test_instances=int(item.get("max_test_instances", 4)),
        max_concurrent_experiments=int(item.get("max_concurrent_experiments", 3)),
        experiment_timeout_minutes=int(item.get("experiment_timeout_minutes", 30)),
        max_stored_test_runs=int(item.get("max_stored_test_runs", 20)),
        test_cleanup_policy=TestCleanupPolicy(
            item.get("test_cleanup_policy", "oldest")
        ),
    )


def _change_to_item(change: OperationalSettingsChange) -> dict[str, Any]:
    # previous/new are JSON-encoded strings rather than native DynamoDB
    # types - a diff entry's value can be a bool, int, str, or a nested
    # dict/list (e.g. the whole analyst_capacity subtree), and this keeps
    # the item schema-agnostic of which. Same "value as JSON string"
    # convention audit_dtos.CreateAuditLogInput.arguments already uses.
    return {
        "record_id": SETTINGS_RECORD_ID,
        "changed_at": change.changed_at.isoformat(),
        "id": change.id,
        "changed_by": change.changed_by,
        "changes": [
            {
                "path": setting_change.path,
                "previous": json.dumps(setting_change.previous, default=str),
                "new": json.dumps(setting_change.new, default=str),
            }
            for setting_change in change.changes
        ],
    }


def _change_from_item(item: dict[str, Any]) -> OperationalSettingsChange:
    return OperationalSettingsChange(
        id=item["id"],
        changed_by=item.get("changed_by"),
        changed_at=datetime.fromisoformat(item["changed_at"]),
        changes=[
            SettingChange(
                path=row["path"],
                previous=json.loads(row["previous"]),
                new=json.loads(row["new"]),
            )
            for row in item.get("changes") or []
        ],
    )
