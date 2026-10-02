from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Key

from src.application.ports.configuration_port import (
    AnalystCapacity,
    ListMembershipMode,
    SamplingIntervalUnit,
    TestCleanupPolicy,
)
from src.application.ports.operational_settings_port import (
    AmountTier,
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
    # boto3's resource layer rejects native float.
    payload["queue_discard_amount_threshold"] = Decimal(
        str(payload["queue_discard_amount_threshold"])
    )
    payload["amount_tiers"] = [
        {
            "code": tier["code"],
            "label": tier["label"],
            "min_inclusive": Decimal(str(tier["min_inclusive"])),
            "max_exclusive": (
                Decimal(str(tier["max_exclusive"]))
                if tier["max_exclusive"] is not None
                else None
            ),
        }
        for tier in payload["amount_tiers"]
    ]
    payload["reasoning_evaluation_sample_rate"] = Decimal(
        str(payload["reasoning_evaluation_sample_rate"])
    )
    return {"record_id": SETTINGS_RECORD_ID, **payload}


def _from_item(item: dict[str, Any]) -> OperationalSettings:
    capacity_item = item.get("analyst_capacity") or {}
    defaults = AnalystCapacity()
    profiles = [
        _day_profile_from_item(p) for p in capacity_item.get("profiles") or []
    ]
    return OperationalSettings(
        agent_enabled=bool(item.get("agent_enabled", True)),
        # Pre-rename items stored these as *_escalation_enabled.
        analyst_enabled=bool(
            item.get("analyst_enabled", item.get("analyst_escalation_enabled", True))
        ),
        voicebot_enabled=bool(
            item.get("voicebot_enabled", item.get("voicebot_escalation_enabled", True))
        ),
        max_instances=int(item.get("max_instances", 8)),
        auto_scale=bool(item.get("auto_scale", True)),
        voicebot_max_concurrent_calls=int(
            item.get("voicebot_max_concurrent_calls", 40)
        ),
        analyst_capacity=AnalystCapacity(
            profiles=profiles or defaults.profiles,
            default_profile_id=capacity_item.get("default_profile_id")
            or defaults.default_profile_id,
            day_overrides=(
                {
                    int(day): profile_id
                    for day, profile_id in capacity_item["day_overrides"].items()
                }
                if "day_overrides" in capacity_item
                else defaults.day_overrides
            ),
        ),
        queue_max_lifetime_value=int(item.get("queue_max_lifetime_value", 60)),
        queue_max_lifetime_unit=SamplingIntervalUnit(
            item.get("queue_max_lifetime_unit", "minutes")
        ),
        queue_discard_amount_threshold=float(
            item.get("queue_discard_amount_threshold", 0)
        ),
        queue_rule_filter_enabled=bool(item.get("queue_rule_filter_enabled", False)),
        queue_rule_filter_mode=ListMembershipMode(
            item.get("queue_rule_filter_mode", "belongs")
        ),
        queue_allowed_triggered_rules=list(
            item.get("queue_allowed_triggered_rules") or []
        ),
        queue_discard_behavior=_shortage_behavior_from_item(
            item.get("queue_discard_behavior") or {}
        ),
        max_test_instances=int(item.get("max_test_instances", 4)),
        max_concurrent_experiments=int(item.get("max_concurrent_experiments", 3)),
        experiment_timeout_minutes=int(item.get("experiment_timeout_minutes", 30)),
        max_stored_test_runs=int(item.get("max_stored_test_runs", 20)),
        test_cleanup_policy=TestCleanupPolicy(
            item.get("test_cleanup_policy", "oldest")
        ),
        amount_tiers=[
            AmountTier(
                code=str(tier["code"]),
                label=str(tier.get("label") or tier["code"]),
                min_inclusive=float(tier.get("min_inclusive") or 0),
                max_exclusive=(
                    float(tier["max_exclusive"])
                    if tier.get("max_exclusive") is not None
                    else None
                ),
            )
            for tier in item.get("amount_tiers") or []
        ],
        amount_tier_set_version=int(item.get("amount_tier_set_version", 0)),
        reasoning_evaluation_sample_rate=float(
            item.get("reasoning_evaluation_sample_rate", 0.05)
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
