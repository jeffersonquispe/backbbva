from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from boto3.dynamodb.conditions import Key

from src.application.ports.simulation_scenario_port import (
    FieldGenerator,
    GeneratorKind,
    OutputMode,
    RateInterval,
    ScenarioStatus,
    SimulationScenarioRecord,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.serialization import (
    from_dynamodb,
    to_dynamodb,
)

TABLE_NAME = "event_simulation_scenarios"
PARTITION = "scenario"


class DynamoSimulationScenarioRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(TABLE_NAME)

    def create(
        self, scenario: SimulationScenarioRecord
    ) -> SimulationScenarioRecord:
        self._table.put_item(Item=_to_item(scenario))
        return scenario

    def get(self, scenario_id: UUID) -> SimulationScenarioRecord | None:
        response = self._table.get_item(
            Key={"partition": PARTITION, "scenario_id": str(scenario_id)}
        )
        item = response.get("Item")
        if item is None:
            return None
        return _from_item(item)

    def list(
        self, status: ScenarioStatus | None = None
    ) -> list[SimulationScenarioRecord]:
        if status is None:
            response = self._table.query(
                KeyConditionExpression=Key("partition").eq(PARTITION),
            )
        else:
            response = self._table.query(
                IndexName="StatusIdx",
                KeyConditionExpression=Key("status").eq(status.value),
            )
        return [_from_item(item) for item in response.get("Items", [])]

    def update(
        self,
        scenario_id: UUID,
        **changes: Any,
    ) -> SimulationScenarioRecord | None:
        current = self.get(scenario_id)
        if current is None:
            return None

        updated_fields = {
            f.name: getattr(current, f.name) for f in dataclasses.fields(current)
        }
        # Default bump first, so an explicit updated_at in `changes` (rare,
        # but the port allows it) still wins over this default.
        updated_fields["updated_at"] = datetime.now(UTC)
        updated_fields.update(changes)

        updated = SimulationScenarioRecord(**updated_fields)
        self._table.put_item(Item=_to_item(updated))
        return updated

    def delete(self, scenario_id: UUID) -> None:
        self._table.delete_item(
            Key={"partition": PARTITION, "scenario_id": str(scenario_id)}
        )


def _field_generator_to_item(generator: FieldGenerator) -> dict[str, Any]:
    return {
        "kind": generator.kind.value,
        "value": to_dynamodb(generator.value),
        "weights": to_dynamodb(generator.weights),
        "params": to_dynamodb(generator.params),
        "system_prompt": generator.system_prompt,
        "user_prompt_template": generator.user_prompt_template,
        "model": generator.model,
        "temperature": to_dynamodb(generator.temperature),
        "seed_dataset_name": generator.seed_dataset_name,
        "seed_field": generator.seed_field,
    }


def _field_generator_from_item(item: dict[str, Any]) -> FieldGenerator:
    return FieldGenerator(
        kind=GeneratorKind(item["kind"]),
        value=from_dynamodb(item.get("value")),
        weights=from_dynamodb(item.get("weights")),
        params=from_dynamodb(item.get("params")),
        system_prompt=item.get("system_prompt"),
        user_prompt_template=item.get("user_prompt_template"),
        model=item.get("model"),
        temperature=from_dynamodb(item.get("temperature", 0.0)),
        seed_dataset_name=item.get("seed_dataset_name"),
        seed_field=item.get("seed_field"),
    )


def _rate_interval_to_item(interval: RateInterval) -> dict[str, Any]:
    return {
        "start_offset_seconds": interval.start_offset_seconds,
        "end_offset_seconds": interval.end_offset_seconds,
        "events_per_minute": to_dynamodb(interval.events_per_minute),
    }


def _rate_interval_from_item(item: dict[str, Any]) -> RateInterval:
    return RateInterval(
        start_offset_seconds=int(item["start_offset_seconds"]),
        end_offset_seconds=int(item["end_offset_seconds"]),
        events_per_minute=from_dynamodb(item["events_per_minute"]),
    )


def _to_item(scenario: SimulationScenarioRecord) -> dict[str, Any]:
    return {
        "partition": PARTITION,
        "scenario_id": str(scenario.id),
        "name": scenario.name,
        "status": scenario.status.value,
        "output_mode": scenario.output_mode.value,
        "rate_schedule": [
            _rate_interval_to_item(interval) for interval in scenario.rate_schedule
        ],
        "field_specs": {
            field_name: _field_generator_to_item(generator)
            for field_name, generator in scenario.field_specs.items()
        },
        "created_at": scenario.created_at.isoformat(),
        "updated_at": scenario.updated_at.isoformat(),
        "target_dataset_name": scenario.target_dataset_name,
        "created_by": scenario.created_by,
        "started_at": (
            scenario.started_at.isoformat() if scenario.started_at else None
        ),
        "events_emitted": scenario.events_emitted,
        "last_tick_offset_seconds": scenario.last_tick_offset_seconds,
        "error": scenario.error,
    }


def _from_item(item: dict[str, Any]) -> SimulationScenarioRecord:
    started_at = item.get("started_at")
    return SimulationScenarioRecord(
        id=UUID(item["scenario_id"]),
        name=item["name"],
        status=ScenarioStatus(item["status"]),
        output_mode=OutputMode(item["output_mode"]),
        rate_schedule=[
            _rate_interval_from_item(interval)
            for interval in item.get("rate_schedule") or []
        ],
        field_specs={
            field_name: _field_generator_from_item(generator_item)
            for field_name, generator_item in (item.get("field_specs") or {}).items()
        },
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
        target_dataset_name=item.get("target_dataset_name"),
        created_by=item.get("created_by"),
        started_at=datetime.fromisoformat(started_at) if started_at else None,
        events_emitted=int(item.get("events_emitted", 0)),
        last_tick_offset_seconds=int(item.get("last_tick_offset_seconds", 0)),
        error=item.get("error"),
    )
