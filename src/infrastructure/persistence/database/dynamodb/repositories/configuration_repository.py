from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from boto3.dynamodb.conditions import Attr, Key

from src.application.ports.configuration_port import (
    AgentSettings,
    AnalystCapacity,
    ConfigurationRecord,
    ConfigurationRepository,
    DayProfile,
    DistributionValue,
    ExampleCase,
    GeneralSettings,
    InfraSettings,
    ModusOperandi,
    MonitoringSettings,
    OpsSettings,
    RedFlag,
    SamplingCriterion,
    SamplingIntervalUnit,
    ShortageAction,
    ShortageBehavior,
    Taxonomy,
    TestCleanupPolicy,
    TestSettings,
    YellowFlag,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

CONFIGURATIONS_TABLE_NAME = "configurations"


class DynamoConfigurationRepository(ConfigurationRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(CONFIGURATIONS_TABLE_NAME)

    def create(self, config: ConfigurationRecord) -> ConfigurationRecord:
        self._table.put_item(Item=_to_item(config))
        return config

    def get(
        self, configuration_id: str, version: int
    ) -> ConfigurationRecord | None:
        response = self._table.get_item(
            Key={"configuration_id": configuration_id, "version": version}
        )
        item = response.get("Item")
        return _from_item(item) if item else None

    def get_latest_version(
        self, configuration_id: str
    ) -> ConfigurationRecord | None:
        versions = self.list_versions(configuration_id)
        if not versions:
            return None
        return max(versions, key=lambda config: config.version)

    def get_active(self) -> ConfigurationRecord | None:
        # Table stays small (a handful of named configurations x a handful
        # of versions each) - a scan+filter is simpler than a sparse GSI
        # and cheap enough at this size.
        response = self._table.scan(FilterExpression=Attr("active").eq(True))
        items = response.get("Items", [])
        return _from_item(items[0]) if items else None

    def list_latest(self) -> list[ConfigurationRecord]:
        by_lineage: dict[str, ConfigurationRecord] = {}
        for config in self._scan_all():
            current = by_lineage.get(config.configuration_id)
            if current is None or config.version > current.version:
                by_lineage[config.configuration_id] = config
        return list(by_lineage.values())

    def list_versions(self, configuration_id: str) -> list[ConfigurationRecord]:
        response = self._table.query(
            KeyConditionExpression=Key("configuration_id").eq(configuration_id),
        )
        return [_from_item(item) for item in response.get("Items", [])]

    def activate(self, configuration_id: str, version: int) -> ConfigurationRecord:
        # ponytail: two sequential update_item calls, not a
        # transact_write_items - no other repository in this codebase uses
        # DynamoDB transactions, and this is a low-frequency admin action.
        # Leaves a narrow race window under concurrent activations; upgrade
        # to transact_write_items if that ever becomes a real risk.
        current_active = self.get_active()
        if current_active is not None and (
            current_active.configuration_id,
            current_active.version,
        ) != (configuration_id, version):
            self._set_active(
                current_active.configuration_id, current_active.version, False
            )
        self._set_active(configuration_id, version, True)
        activated = self.get(configuration_id, version)
        assert activated is not None
        return activated

    def _set_active(
        self, configuration_id: str, version: int, active: bool
    ) -> None:
        self._table.update_item(
            Key={"configuration_id": configuration_id, "version": version},
            UpdateExpression="SET active = :active, updated_at = :updated_at",
            ExpressionAttributeValues={
                ":active": active,
                ":updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _scan_all(self) -> list[ConfigurationRecord]:
        response = self._table.scan()
        return [_from_item(item) for item in response.get("Items", [])]


def _to_item(config: ConfigurationRecord) -> dict[str, Any]:
    ops_item = asdict(config.ops)
    # DynamoDB map keys must be strings - AnalystCapacity.day_overrides is
    # keyed by int (day of month) on the domain type.
    ops_item["analyst_capacity"]["day_overrides"] = {
        str(day): profile_id
        for day, profile_id in ops_item["analyst_capacity"]["day_overrides"].items()
    }
    return {
        "configuration_id": config.configuration_id,
        "version": config.version,
        "name": config.name,
        "description": config.description,
        "active": config.active,
        "general": asdict(config.general),
        "infra": asdict(config.infra),
        "ops": ops_item,
        "monitoring": asdict(config.monitoring),
        "agent": asdict(config.agent),
        "test": asdict(config.test),
        "created_at": config.created_at.isoformat(),
        "updated_at": config.updated_at.isoformat(),
        "created_by": config.created_by,
    }


def _from_item(item: dict[str, Any]) -> ConfigurationRecord:
    ops_item = item.get("ops") or {}
    monitoring_item = item.get("monitoring") or {}
    agent_item = item.get("agent") or {}
    test_item = item.get("test") or {}

    return ConfigurationRecord(
        configuration_id=item["configuration_id"],
        version=int(item["version"]),
        name=item["name"],
        description=item.get("description") or "",
        active=bool(item.get("active", False)),
        general=GeneralSettings(**(item.get("general") or {})),
        infra=InfraSettings(**(item.get("infra") or {})),
        ops=OpsSettings(
            voicebot_max_concurrent_calls=int(
                ops_item.get("voicebot_max_concurrent_calls", 40)
            ),
            analyst_capacity=_analyst_capacity_from_item(
                ops_item.get("analyst_capacity") or {}
            ),
            queue_max_lifetime_value=int(
                ops_item.get("queue_max_lifetime_value", 60)
            ),
            queue_max_lifetime_unit=SamplingIntervalUnit(
                ops_item.get("queue_max_lifetime_unit", "minutes")
            ),
            voicebot_shortage_behavior=_shortage_behavior_from_item(
                ops_item.get("voicebot_shortage_behavior") or {}
            ),
            analyst_shortage_behavior=_shortage_behavior_from_item(
                ops_item.get("analyst_shortage_behavior") or {}
            ),
        ),
        monitoring=MonitoringSettings(
            sampling_interval_value=int(
                monitoring_item.get("sampling_interval_value", 30)
            ),
            sampling_interval_unit=SamplingIntervalUnit(
                monitoring_item.get("sampling_interval_unit", "minutes")
            ),
            sampling_criteria=[
                _sampling_criterion_from_item(criterion)
                for criterion in monitoring_item.get("sampling_criteria") or []
            ],
            max_samples=int(monitoring_item.get("max_samples", 200)),
            prompt_clasificacion=monitoring_item.get("prompt_clasificacion") or "",
            prompt_analista=monitoring_item.get("prompt_analista") or "",
            prompt_monitoreo=monitoring_item.get("prompt_monitoreo") or "",
            evaluation_variables=list(
                monitoring_item.get("evaluation_variables") or []
            ),
        ),
        agent=AgentSettings(
            perfil_usuario=agent_item.get("perfil_usuario") or "",
            perfil_usuario_vars=list(agent_item.get("perfil_usuario_vars") or []),
            perfil_transaccion=agent_item.get("perfil_transaccion") or "",
            perfil_transaccion_vars=list(
                agent_item.get("perfil_transaccion_vars") or []
            ),
            perfil_transaccional=agent_item.get("perfil_transaccional") or "",
            perfil_transaccional_vars=list(
                agent_item.get("perfil_transaccional_vars") or []
            ),
            taxonomies=[
                Taxonomy(
                    id=t["id"],
                    code=t["code"],
                    name=t["name"],
                    description=t.get("description") or "",
                    variables=list(t.get("variables") or []),
                    examples=list(t.get("examples") or []),
                    active=bool(t.get("active", True)),
                    segmento=t.get("segmento") or "",
                )
                for t in agent_item.get("taxonomies") or []
            ],
            modus_operandi=[
                ModusOperandi(
                    id=m["id"],
                    title=m["title"],
                    narrative=m.get("narrative") or "",
                    taxonomy_id=m["taxonomy_id"],
                    segmento=m.get("segmento") or "",
                )
                for m in agent_item.get("modus_operandi") or []
            ],
            red_flags=[
                RedFlag(
                    id=r["id"],
                    name=r["name"],
                    description=r.get("description") or "",
                    modus_operandi_id=r["modus_operandi_id"],
                    taxonomy_id=r["taxonomy_id"],
                    variables=list(r.get("variables") or []),
                    segmento=r.get("segmento") or "",
                )
                for r in agent_item.get("red_flags") or []
            ],
            yellow_flags=[
                YellowFlag(
                    id=y["id"],
                    name=y["name"],
                    description=y.get("description") or "",
                    modus_operandi_id=y["modus_operandi_id"],
                    taxonomy_id=y["taxonomy_id"],
                    variables=list(y.get("variables") or []),
                    segmento=y.get("segmento") or "",
                )
                for y in agent_item.get("yellow_flags") or []
            ],
            example_cases=[
                ExampleCase(
                    id=e["id"],
                    text=e.get("text") or "",
                    modus_operandi_id=e["modus_operandi_id"],
                    taxonomy_id=e["taxonomy_id"],
                    segmento=e.get("segmento") or "",
                )
                for e in agent_item.get("example_cases") or []
            ],
            active_fields=list(agent_item.get("active_fields") or []),
        ),
        test=TestSettings(
            max_test_instances=int(test_item.get("max_test_instances", 4)),
            max_concurrent_experiments=int(
                test_item.get("max_concurrent_experiments", 3)
            ),
            experiment_timeout_minutes=int(
                test_item.get("experiment_timeout_minutes", 30)
            ),
            max_stored_test_runs=int(test_item.get("max_stored_test_runs", 20)),
            test_cleanup_policy=TestCleanupPolicy(
                test_item.get("test_cleanup_policy", "oldest")
            ),
        ),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
        created_by=item.get("created_by"),
    )


def _sampling_criterion_from_item(item: dict[str, Any]) -> SamplingCriterion:
    return SamplingCriterion(
        id=item["id"],
        name=item["name"],
        values=[
            DistributionValue(id=v["id"], label=v["label"], pct=int(v["pct"]))
            for v in item.get("values") or []
        ],
    )


def _analyst_capacity_from_item(item: dict[str, Any]) -> AnalystCapacity:
    return AnalystCapacity(
        profiles=[
            DayProfile(
                id=p["id"],
                name=p["name"],
                description=p.get("description") or "",
                hourly=[int(h) for h in p.get("hourly") or []],
            )
            for p in item.get("profiles") or []
        ],
        default_profile_id=item.get("default_profile_id") or "",
        day_overrides={
            int(day): profile_id
            for day, profile_id in (item.get("day_overrides") or {}).items()
        },
    )


def _shortage_behavior_from_item(item: dict[str, Any]) -> ShortageBehavior:
    return ShortageBehavior(
        action=ShortageAction(item.get("action", "block-soft")),
        custom_text=item.get("custom_text") or "",
    )
