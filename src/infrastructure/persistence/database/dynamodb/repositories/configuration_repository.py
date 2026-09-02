from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Attr, Key

from src.application.ports.configuration_port import (
    AdversarialConfig,
    AgentSettings,
    AnalystCapacity,
    AnalystConfig,
    AnalystPlaybook,
    BuiltInTool,
    ClassificationConfig,
    ComparisonOperator,
    ConfigurationRecord,
    ConfigurationRepository,
    CriteriaMode,
    DayProfile,
    DistributionValue,
    DocumentationConfig,
    DocumentationStrategy,
    ExampleCase,
    FieldCategorization,
    FieldCriterion,
    FieldKind,
    FilterCondition,
    FilterConditionOperator,
    FilterGroup,
    Flag,
    FlagType,
    GeneralSettings,
    InfraSettings,
    LogicalOperator,
    ModusOperandi,
    MonitoringSettings,
    OpsSettings,
    ProfilingConfig,
    ProfilingPromptMode,
    ProfilingStrategy,
    ProfilingStrategyKey,
    ResolutionTag,
    SamplingCriterion,
    SamplingIntervalUnit,
    SegmentSettings,
    ShortageBehavior,
    Taxonomy,
    TestCleanupPolicy,
    TestSettings,
    VectorStoreTool,
    VoicebotCategoryPrompt,
    VoicebotConfig,
    default_segments,
)
from src.application.ports.tag_catalog_port import TagCategory
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

CONFIGURATIONS_TABLE_NAME = "configurations"
GENERAL_TABLE_NAME = "configuration_general"
INFRASTRUCTURE_TABLE_NAME = "configuration_infrastructure"
OPERATIONS_TABLE_NAME = "configuration_operations"
EVALUATION_TABLE_NAME = "configuration_evaluation"
ANALYST_PROFILES_TABLE_NAME = "configuration_analyst_profiles"
SEGMENTS_TABLE_NAME = "configuration_segments"
PROFILING_STRATEGIES_TABLE_NAME = "configuration_profiling_strategies"
FIELD_CATEGORIZATIONS_TABLE_NAME = "configuration_field_categorizations"
TAXONOMIES_TABLE_NAME = "configuration_taxonomies"
MODUS_OPERANDI_TABLE_NAME = "configuration_modus_operandi"
FLAGS_TABLE_NAME = "configuration_red_yellow_flags"
EXAMPLES_TABLE_NAME = "configuration_examples"
PLAYBOOKS_TABLE_NAME = "configuration_playbooks"
VOICEBOT_PROMPTS_TABLE_NAME = "configuration_voicebot_prompts"
SAMPLING_CRITERIA_TABLE_NAME = "configuration_sampling_criteria"
SAMPLING_CRITERIA_VALUES_TABLE_NAME = "configuration_sampling_criteria_values"
FILTER_GROUPS_TABLE_NAME = "configuration_filter_groups"
FILTER_CONDITIONS_TABLE_NAME = "configuration_filter_conditions"


def _config_key(configuration_id: str, version: int) -> str:
    """FK used by tables scoped to a whole configuration version (not a
    single segment) - e.g. configuration_analyst_profiles and
    configuration_segments itself."""
    return f"{configuration_id}#{version:06d}"


def _group_key(segment_id: str, group_id: str) -> str:
    """FK a FilterCondition uses to point at the exact FilterGroup it
    belongs to (a segment's filter tree can have several groups)."""
    return f"{segment_id}#{group_id}"


def _criterion_key(segment_id: str, criterion_id: str) -> str:
    """FK a DistributionValue uses to point at the exact SamplingCriterion
    it belongs to (a segment's monitoring can have several criteria)."""
    return f"{segment_id}#{criterion_id}"


class DynamoConfigurationRepository(ConfigurationRepository):
    def __init__(self) -> None:
        resource = get_dynamodb_resource()
        self._table = resource.Table(CONFIGURATIONS_TABLE_NAME)
        self._general = resource.Table(GENERAL_TABLE_NAME)
        self._infrastructure = resource.Table(INFRASTRUCTURE_TABLE_NAME)
        self._operations = resource.Table(OPERATIONS_TABLE_NAME)
        self._evaluation = resource.Table(EVALUATION_TABLE_NAME)
        self._analyst_profiles = resource.Table(ANALYST_PROFILES_TABLE_NAME)
        self._segments = resource.Table(SEGMENTS_TABLE_NAME)
        self._profiling_strategies = resource.Table(PROFILING_STRATEGIES_TABLE_NAME)
        self._field_categorizations = resource.Table(
            FIELD_CATEGORIZATIONS_TABLE_NAME
        )
        self._taxonomies = resource.Table(TAXONOMIES_TABLE_NAME)
        self._modus_operandi = resource.Table(MODUS_OPERANDI_TABLE_NAME)
        self._flags = resource.Table(FLAGS_TABLE_NAME)
        self._examples = resource.Table(EXAMPLES_TABLE_NAME)
        self._playbooks = resource.Table(PLAYBOOKS_TABLE_NAME)
        self._voicebot_prompts = resource.Table(VOICEBOT_PROMPTS_TABLE_NAME)
        self._sampling_criteria = resource.Table(SAMPLING_CRITERIA_TABLE_NAME)
        self._sampling_criteria_values = resource.Table(
            SAMPLING_CRITERIA_VALUES_TABLE_NAME
        )
        self._filter_groups = resource.Table(FILTER_GROUPS_TABLE_NAME)
        self._filter_conditions = resource.Table(FILTER_CONDITIONS_TABLE_NAME)

    def create(self, config: ConfigurationRecord) -> ConfigurationRecord:
        return self._write_version(config)

    def update(self, config: ConfigurationRecord) -> ConfigurationRecord:
        # Every per-segment child row is keyed off a fresh uuid segment_id
        # minted on each write (see the loop below) - overwriting in place
        # means the old rows for this (configuration_id, version) are
        # orphaned unless deleted first, so cascade-delete before rewriting
        # exactly like create() would.
        self._delete_version_children(config.configuration_id, config.version)
        return self._write_version(config)

    def _write_version(self, config: ConfigurationRecord) -> ConfigurationRecord:
        self._table.put_item(Item=_to_item(config))

        configuration_id, version = config.configuration_id, config.version
        config_key = _config_key(configuration_id, version)
        self._general.put_item(
            Item=_owned_item(configuration_id, version, asdict(config.general))
        )
        self._infrastructure.put_item(
            Item=_owned_item(configuration_id, version, asdict(config.infra))
        )
        self._operations.put_item(
            Item=_owned_item(configuration_id, version, _operations_payload(config.ops))
        )
        self._evaluation.put_item(
            Item=_owned_item(configuration_id, version, asdict(config.test))
        )
        self._put_entities(
            self._analyst_profiles,
            "config_key",
            config_key,
            config.ops.analyst_capacity.profiles,
        )

        # The two segment objects (digital channels / cards) are born here,
        # together with their configuration - each gets a fresh uuid `id`
        # that every other per-segment table below references as its FK.
        for code, segment in config.segments.items():
            segment_id = str(uuid.uuid4())
            agent = segment.agent
            self._segments.put_item(
                Item={
                    "config_key": config_key,
                    "id": segment_id,
                    "segment_code": code,
                    **_segment_to_item(segment),
                }
            )
            self._put_filter_group(segment_id, segment.filter, parent_group_id=None)
            self._put_entities(
                self._profiling_strategies,
                "segment_id",
                segment_id,
                agent.profiling.strategies,
            )
            self._put_field_categorizations(
                segment_id, agent.profiling.field_categorizations
            )
            self._put_entities(
                self._taxonomies, "segment_id", segment_id, agent.taxonomies
            )
            self._put_entities(
                self._modus_operandi, "segment_id", segment_id, agent.modus_operandi
            )
            self._put_entities(self._flags, "segment_id", segment_id, agent.flags)
            self._put_entities(
                self._examples, "segment_id", segment_id, agent.example_cases
            )
            self._put_entities(
                self._playbooks, "segment_id", segment_id, agent.analyst.playbooks
            )
            self._put_entities(
                self._voicebot_prompts,
                "segment_id",
                segment_id,
                agent.analyst.voicebot.category_prompts,
            )
            self._put_sampling_criteria(
                segment_id, segment.monitoring.sampling_criteria
            )
        return config

    def get(
        self, configuration_id: str, version: int
    ) -> ConfigurationRecord | None:
        response = self._table.get_item(
            Key={"configuration_id": configuration_id, "version": version}
        )
        item = response.get("Item")
        return self._hydrate(item) if item else None

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
        return self._hydrate(items[0]) if items else None

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
        return [self._hydrate(item) for item in response.get("Items", [])]

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
        self._set_active(configuration_id, version, True, ever_activated=True)
        activated = self.get(configuration_id, version)
        assert activated is not None
        return activated

    def _set_active(
        self,
        configuration_id: str,
        version: int,
        active: bool,
        *,
        ever_activated: bool = False,
    ) -> None:
        expression = "SET active = :active, updated_at = :updated_at"
        values: dict[str, Any] = {
            ":active": active,
            ":updated_at": datetime.now(timezone.utc).isoformat(),
        }
        # ever_activated is sticky - only ever set to True (going live),
        # never reset back to False when a version is later superseded.
        if ever_activated:
            expression += ", ever_activated = :ever_activated"
            values[":ever_activated"] = True
        self._table.update_item(
            Key={"configuration_id": configuration_id, "version": version},
            UpdateExpression=expression,
            ExpressionAttributeValues=values,
        )

    def _scan_all(self) -> list[ConfigurationRecord]:
        response = self._table.scan()
        return [self._hydrate(item) for item in response.get("Items", [])]

    def _hydrate(self, item: dict[str, Any]) -> ConfigurationRecord:
        """`_from_item` alone rebuilds only what's still stored on the owner
        item (name/description/active/timestamps). Everything normalized
        into its own table - general/infra/ops/test, analyst capacity
        profiles, the two segment objects, and every per-segment sub-entity
        (taxonomies, flags, filter tree, sampling criteria, ...) - gets
        fetched and attached here."""
        config = _from_item(item)
        configuration_id, version = config.configuration_id, config.version
        config_key = _config_key(configuration_id, version)

        general_item = self._general.get_item(
            Key={"configuration_id": configuration_id, "version": version}
        ).get("Item")
        infra_item = self._infrastructure.get_item(
            Key={"configuration_id": configuration_id, "version": version}
        ).get("Item")
        operations_item = self._operations.get_item(
            Key={"configuration_id": configuration_id, "version": version}
        ).get("Item")
        evaluation_item = self._evaluation.get_item(
            Key={"configuration_id": configuration_id, "version": version}
        ).get("Item")

        config.general = _general_from_item(general_item or {})
        config.infra = _infra_from_item(infra_item or {})
        config.ops = _ops_from_item(operations_item or {})
        config.ops.analyst_capacity.profiles = self._query_entities(
            self._analyst_profiles, "config_key", config_key, _day_profile_from_item
        )
        config.test = _evaluation_from_item(evaluation_item or {})

        segment_rows = self._segments.query(
            KeyConditionExpression=Key("config_key").eq(config_key)
        ).get("Items", [])
        segments: dict[str, SegmentSettings] = {}
        for row in segment_rows:
            segment_id = row["id"]
            segment = _segment_settings_from_item(row)
            agent = segment.agent
            segment.filter = self._load_filter_tree(segment_id)
            agent.profiling.strategies = self._load_profiling_strategies(segment_id)
            agent.profiling.field_categorizations = self._query_entities(
                self._field_categorizations,
                "segment_id",
                segment_id,
                _field_categorization_from_item,
            )
            agent.taxonomies = self._query_entities(
                self._taxonomies, "segment_id", segment_id, _taxonomy_from_item
            )
            agent.modus_operandi = self._query_entities(
                self._modus_operandi,
                "segment_id",
                segment_id,
                _modus_operandi_from_item,
            )
            agent.flags = self._query_entities(
                self._flags, "segment_id", segment_id, _flag_from_item
            )
            agent.example_cases = self._query_entities(
                self._examples, "segment_id", segment_id, _example_case_from_item
            )
            agent.analyst.playbooks = self._query_entities(
                self._playbooks, "segment_id", segment_id, _playbook_from_item
            )
            agent.analyst.voicebot.category_prompts = self._query_entities(
                self._voicebot_prompts,
                "segment_id",
                segment_id,
                _voicebot_category_prompt_from_item,
            )
            segment.monitoring.sampling_criteria = self._load_sampling_criteria(
                segment_id
            )
            segments[row["segment_code"]] = segment
        # Pre-migration records (created before configuration_segments
        # existed) have no rows here - fall back to the same default the
        # dataclass field itself uses, so old configs load with both fixed
        # segments present (disabled, empty filter).
        config.segments = segments if segments else default_segments()
        return config

    def _put_entities(
        self, table: Any, hash_attr: str, key: str, entities: list[Any]
    ) -> None:
        if not entities:
            return
        with table.batch_writer() as batch:
            for entity in entities:
                batch.put_item(Item={hash_attr: key, **asdict(entity)})

    def _query_entities(
        self, table: Any, hash_attr: str, key: str, from_item: Any
    ) -> list[Any]:
        response = table.query(KeyConditionExpression=Key(hash_attr).eq(key))
        return [from_item(entity_item) for entity_item in response.get("Items", [])]

    def _put_field_categorizations(
        self, segment_id: str, categorizations: list[FieldCategorization]
    ) -> None:
        # Not routed through the generic _put_entities: criteria carry
        # min/max/numeric_value floats, which DynamoDB rejects unless
        # converted to Decimal first.
        if not categorizations:
            return
        with self._field_categorizations.batch_writer() as batch:
            for fc in categorizations:
                item = asdict(fc)
                item["criteria"] = [_criterion_to_item(c) for c in fc.criteria]
                batch.put_item(Item={"segment_id": segment_id, **item})

    def _put_sampling_criteria(
        self, segment_id: str, criteria: list[SamplingCriterion]
    ) -> None:
        if not criteria:
            return
        with self._sampling_criteria.batch_writer() as batch:
            for criterion in criteria:
                item = asdict(criterion)
                del item["values"]  # own table now
                batch.put_item(Item={"segment_id": segment_id, **item})
        for criterion in criteria:
            self._put_entities(
                self._sampling_criteria_values,
                "criterion_key",
                _criterion_key(segment_id, criterion.id),
                criterion.values,
            )

    def _load_sampling_criteria(self, segment_id: str) -> list[SamplingCriterion]:
        response = self._sampling_criteria.query(
            KeyConditionExpression=Key("segment_id").eq(segment_id)
        )
        criteria = []
        for item in response.get("Items", []):
            values = self._query_entities(
                self._sampling_criteria_values,
                "criterion_key",
                _criterion_key(segment_id, item["id"]),
                _distribution_value_from_item,
            )
            criteria.append(SamplingCriterion(id=item["id"], name=item["name"], values=values))
        return criteria

    def _load_profiling_strategies(self, segment_id: str) -> list[ProfilingStrategy]:
        rows = self._query_entities(
            self._profiling_strategies,
            "segment_id",
            segment_id,
            _profiling_strategy_from_item,
        )
        # Querying returns rows sorted by the RANGE key ("key") as a plain
        # string - alphabetically that's transaccion, transaccional, usuario,
        # not the usuario -> transaccion -> transaccional pipeline order the
        # profiling chain depends on. Re-sort into canonical enum order;
        # fall back to full defaults if nothing was ever written (e.g. a
        # pre-migration record).
        by_key = {strategy.key: strategy for strategy in rows}
        return [
            by_key[key] for key in ProfilingStrategyKey if key in by_key
        ] or [ProfilingStrategy(key=key) for key in ProfilingStrategyKey]

    def _put_filter_group(
        self, segment_id: str, group: FilterGroup, parent_group_id: str | None
    ) -> None:
        self._filter_groups.put_item(
            Item={
                "segment_id": segment_id,
                "id": group.id,
                "operator": group.operator.value,
                "parent_group_id": parent_group_id,
            }
        )
        self._put_entities(
            self._filter_conditions,
            "group_key",
            _group_key(segment_id, group.id),
            group.conditions,
        )
        for nested in group.groups:
            self._put_filter_group(segment_id, nested, parent_group_id=group.id)

    def _load_filter_tree(self, segment_id: str) -> FilterGroup:
        response = self._filter_groups.query(
            KeyConditionExpression=Key("segment_id").eq(segment_id)
        )
        rows = response.get("Items", [])
        if not rows:
            return FilterGroup(id="root")

        groups_by_id: dict[str, FilterGroup] = {}
        children_of: dict[str | None, list[str]] = defaultdict(list)
        for row in rows:
            conditions = self._query_entities(
                self._filter_conditions,
                "group_key",
                _group_key(segment_id, row["id"]),
                _filter_condition_from_item,
            )
            groups_by_id[row["id"]] = FilterGroup(
                id=row["id"],
                operator=LogicalOperator(row.get("operator", "and")),
                conditions=conditions,
            )
            children_of[row.get("parent_group_id")].append(row["id"])

        for parent_id, child_ids in children_of.items():
            if parent_id is None:
                continue
            groups_by_id[parent_id].groups = [
                groups_by_id[child_id] for child_id in child_ids
            ]

        root_id = children_of[None][0]
        return groups_by_id[root_id]

    # --- overwrite-in-place support (update()) ----------------------------

    def _delete_version_children(self, configuration_id: str, version: int) -> None:
        config_key = _config_key(configuration_id, version)
        self._delete_query(self._analyst_profiles, "config_key", config_key)
        segment_rows = self._delete_query(self._segments, "config_key", config_key)
        for row in segment_rows:
            self._delete_segment_children(row["id"])

    def _delete_segment_children(self, segment_id: str) -> None:
        self._delete_query(self._profiling_strategies, "segment_id", segment_id, range_attr="key")
        self._delete_query(self._field_categorizations, "segment_id", segment_id, range_attr="field")
        self._delete_query(self._taxonomies, "segment_id", segment_id)
        self._delete_query(self._modus_operandi, "segment_id", segment_id)
        self._delete_query(self._flags, "segment_id", segment_id)
        self._delete_query(self._examples, "segment_id", segment_id)
        self._delete_query(self._playbooks, "segment_id", segment_id)
        self._delete_query(self._voicebot_prompts, "segment_id", segment_id)

        criteria_rows = self._delete_query(self._sampling_criteria, "segment_id", segment_id)
        for criterion in criteria_rows:
            self._delete_query(
                self._sampling_criteria_values,
                "criterion_key",
                _criterion_key(segment_id, criterion["id"]),
            )

        group_rows = self._delete_query(self._filter_groups, "segment_id", segment_id)
        for group in group_rows:
            self._delete_query(
                self._filter_conditions, "group_key", _group_key(segment_id, group["id"])
            )

    def _delete_query(
        self, table: Any, hash_attr: str, key: str, range_attr: str = "id"
    ) -> list[dict[str, Any]]:
        """Query every row under `key` and delete it, returning the rows
        (pre-delete) so callers can cascade into child tables keyed off
        each row's own id."""
        response = table.query(KeyConditionExpression=Key(hash_attr).eq(key))
        items = response.get("Items", [])
        if not items:
            return items
        with table.batch_writer() as batch:
            for item in items:
                batch.delete_item(Key={hash_attr: key, range_attr: item[range_attr]})
        return items


def _owned_item(
    configuration_id: str, version: int, payload: dict[str, Any]
) -> dict[str, Any]:
    return {"configuration_id": configuration_id, "version": version, **payload}


def _operations_payload(ops: OpsSettings) -> dict[str, Any]:
    payload = asdict(ops)
    del payload["analyst_capacity"]["profiles"]  # own table now
    # DynamoDB map keys must be strings - AnalystCapacity.day_overrides is
    # keyed by int (day of month) on the domain type.
    payload["analyst_capacity"]["day_overrides"] = {
        str(day): profile_id
        for day, profile_id in payload["analyst_capacity"]["day_overrides"].items()
    }
    # DynamoDB's boto3 resource rejects native float - queue_discard_amount_threshold
    # is the only float field on OpsSettings.
    payload["queue_discard_amount_threshold"] = Decimal(
        str(payload["queue_discard_amount_threshold"])
    )
    return payload


def _to_item(config: ConfigurationRecord) -> dict[str, Any]:
    # No "segments" here - the two segment objects are their own table
    # (configuration_segments), born alongside this item in create().
    return {
        "configuration_id": config.configuration_id,
        "version": config.version,
        "name": config.name,
        "description": config.description,
        "active": config.active,
        "ever_activated": config.ever_activated,
        "created_at": config.created_at.isoformat(),
        "updated_at": config.updated_at.isoformat(),
        "created_by": config.created_by,
    }


def _segment_to_item(segment: SegmentSettings) -> dict[str, Any]:
    # asdict() the whole segment, then strip whatever now lives in its own
    # table(s) - asdict picks up any future scalar field automatically, so
    # only the extracted collections need naming here.
    item = asdict(segment)
    del item["filter"]  # own tables now (configuration_filter_groups/_conditions)
    del item["monitoring"]["sampling_criteria"]
    del item["agent"]["profiling"]["strategies"]
    del item["agent"]["profiling"]["field_categorizations"]
    for key in ("taxonomies", "modus_operandi", "flags", "example_cases"):
        del item["agent"][key]
    del item["agent"]["analyst"]["playbooks"]
    del item["agent"]["analyst"]["voicebot"]["category_prompts"]
    return item


def _from_item(item: dict[str, Any]) -> ConfigurationRecord:
    # general/infra/ops/test/segments are placeholders here (segments
    # default via ConfigurationRecord's own default_factory) -
    # DynamoConfigurationRepository._hydrate overwrites all of them from
    # their own tables right after this call.
    return ConfigurationRecord(
        configuration_id=item["configuration_id"],
        version=int(item["version"]),
        name=item["name"],
        description=item.get("description") or "",
        active=bool(item.get("active", False)),
        ever_activated=bool(item.get("ever_activated", False)),
        general=GeneralSettings(),
        infra=InfraSettings(),
        ops=OpsSettings(),
        test=TestSettings(),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
        created_by=item.get("created_by"),
    )


# --- 1:1 section item <-> dataclass -------------------------------------


def _general_from_item(item: dict[str, Any]) -> GeneralSettings:
    return GeneralSettings(
        agent_enabled=bool(item.get("agent_enabled", True)),
        migration_window_enabled=bool(item.get("migration_window_enabled", False)),
        migration_window_hour=int(item.get("migration_window_hour", 2)),
        analyst_escalation_enabled=bool(item.get("analyst_escalation_enabled", True)),
        voicebot_escalation_enabled=bool(item.get("voicebot_escalation_enabled", True)),
    )


def _infra_from_item(item: dict[str, Any]) -> InfraSettings:
    return InfraSettings(
        max_instances=int(item.get("max_instances", 8)),
        auto_scale=bool(item.get("auto_scale", True)),
        fraud_history_db_retention_days=int(
            item.get("fraud_history_db_retention_days", 90)
        ),
        fraud_history_cold_storage_retention_months=int(
            item.get("fraud_history_cold_storage_retention_months", 24)
        ),
    )


def _ops_from_item(item: dict[str, Any]) -> OpsSettings:
    capacity_item = item.get("analyst_capacity") or {}
    return OpsSettings(
        voicebot_max_concurrent_calls=int(
            item.get("voicebot_max_concurrent_calls", 40)
        ),
        analyst_capacity=AnalystCapacity(
            profiles=[],  # own table - filled in by DynamoConfigurationRepository._hydrate
            default_profile_id=capacity_item.get("default_profile_id") or "",
            day_overrides={
                int(day): profile_id
                for day, profile_id in (capacity_item.get("day_overrides") or {}).items()
            },
        ),
        queue_max_lifetime_value=int(item.get("queue_max_lifetime_value", 60)),
        queue_max_lifetime_unit=SamplingIntervalUnit(
            item.get("queue_max_lifetime_unit", "minutes")
        ),
        queue_discard_amount_threshold=float(
            item.get("queue_discard_amount_threshold", 0)
        ),
        queue_rule_filter_enabled=bool(item.get("queue_rule_filter_enabled", False)),
        queue_allowed_triggered_rules=list(
            item.get("queue_allowed_triggered_rules") or []
        ),
        voicebot_shortage_behavior=_shortage_behavior_from_item(
            item.get("voicebot_shortage_behavior") or {}
        ),
        analyst_shortage_behavior=_shortage_behavior_from_item(
            item.get("analyst_shortage_behavior") or {}
        ),
    )


def _evaluation_from_item(item: dict[str, Any]) -> TestSettings:
    return TestSettings(
        max_test_instances=int(item.get("max_test_instances", 4)),
        max_concurrent_experiments=int(item.get("max_concurrent_experiments", 3)),
        experiment_timeout_minutes=int(item.get("experiment_timeout_minutes", 30)),
        max_stored_test_runs=int(item.get("max_stored_test_runs", 20)),
        test_cleanup_policy=TestCleanupPolicy(
            item.get("test_cleanup_policy", "oldest")
        ),
    )


def _shortage_behavior_from_item(item: dict[str, Any]) -> ShortageBehavior:
    return ShortageBehavior(
        resolution_tag=ResolutionTag(item.get("resolution_tag", "block_soft")),
        resolution_method_id=item.get("resolution_method_id"),
    )


# --- sub-entity item <-> dataclass ---------------------------------------
# Each of these decodes one row from its own dedicated table (or, for the
# _from_item test helpers below, a hand-built dict shaped the same way).


def _day_profile_from_item(item: dict[str, Any]) -> DayProfile:
    return DayProfile(
        id=item["id"],
        name=item["name"],
        description=item.get("description") or "",
        hourly=[int(h) for h in item.get("hourly") or []],
    )


def _taxonomy_from_item(item: dict[str, Any]) -> Taxonomy:
    return Taxonomy(
        id=item["id"],
        code=item["code"],
        name=item["name"],
        description=item.get("description") or "",
        variables=list(item.get("variables") or []),
        examples=list(item.get("examples") or []),
        active=bool(item.get("active", True)),
        segmento=item.get("segmento") or "",
    )


def _modus_operandi_from_item(item: dict[str, Any]) -> ModusOperandi:
    return ModusOperandi(
        id=item["id"],
        title=item["title"],
        narrative=item.get("narrative") or "",
        taxonomy_id=item["taxonomy_id"],
        evolved_variables=list(item.get("evolved_variables") or []),
        active=bool(item.get("active", True)),
        segmento=item.get("segmento") or "",
    )


def _flag_from_item(item: dict[str, Any]) -> Flag:
    return Flag(
        id=item["id"],
        flag_type=FlagType(item["flag_type"]),
        name=item["name"],
        description=item.get("description") or "",
        evolved_variables=list(item.get("evolved_variables") or []),
        modus_operandi_ids=list(item.get("modus_operandi_ids") or []),
        segmento=item.get("segmento") or "",
    )


def _example_case_from_item(item: dict[str, Any]) -> ExampleCase:
    return ExampleCase(
        id=item["id"],
        text=item.get("text") or "",
        modus_operandi_id=item["modus_operandi_id"],
        taxonomy_id=item["taxonomy_id"],
        segmento=item.get("segmento") or "",
    )


def _playbook_from_item(item: dict[str, Any]) -> AnalystPlaybook:
    return AnalystPlaybook(
        id=item["id"],
        name=item["name"],
        strategy=item.get("strategy") or "",
        resolution_tag=ResolutionTag(
            item.get("resolution_tag", "scale_to_analyst")
        ),
        resolution_method_id=item.get("resolution_method_id"),
    )


def _voicebot_category_prompt_from_item(item: dict[str, Any]) -> VoicebotCategoryPrompt:
    return VoicebotCategoryPrompt(
        id=item["id"],
        taxonomy_id=item["taxonomy_id"],
        prompt=item.get("prompt") or "",
    )


def _sampling_criterion_from_item(item: dict[str, Any]) -> SamplingCriterion:
    return SamplingCriterion(
        id=item["id"],
        name=item["name"],
        values=[
            _distribution_value_from_item(v) for v in item.get("values") or []
        ],
    )


def _distribution_value_from_item(item: dict[str, Any]) -> DistributionValue:
    return DistributionValue(id=item["id"], label=item["label"], pct=int(item["pct"]))


def _filter_condition_from_item(item: dict[str, Any]) -> FilterCondition:
    return FilterCondition(
        id=item["id"],
        category=TagCategory(item["category"]),
        operator=FilterConditionOperator(item.get("operator", "in")),
        values=list(item.get("values") or []),
    )


# --- configuration_segments row sub-sections ------------------------------


def _segment_settings_from_item(item: dict[str, Any]) -> SegmentSettings:
    return SegmentSettings(
        enabled=bool(item.get("enabled", False)),
        filter=FilterGroup(id="root"),  # own tables - filled in by _hydrate
        monitoring=_monitoring_from_item(item.get("monitoring") or {}),
        agent=_agent_from_item(item.get("agent") or {}),
        # Pre-migration rows (written before this field existed) default to
        # 0 for every segment - same tie-break result as the old fixed
        # SegmentCode enum only for a 1-segment config; a multi-segment
        # pre-migration config falls back to dict order, which is no
        # longer guaranteed meaningful. No such records exist outside local
        # dev data at the time of this migration.
        order=int(item.get("order", 0)),
    )


def _monitoring_from_item(monitoring_item: dict[str, Any]) -> MonitoringSettings:
    # sampling_criteria isn't stored on this item (own tables, see
    # DynamoConfigurationRepository._hydrate) - defaults to [] here, the
    # caller fills it in after querying configuration_sampling_criteria.
    return MonitoringSettings(
        sampling_interval_value=int(
            monitoring_item.get("sampling_interval_value", 30)
        ),
        sampling_interval_unit=SamplingIntervalUnit(
            monitoring_item.get("sampling_interval_unit", "minutes")
        ),
        max_samples=int(monitoring_item.get("max_samples", 200)),
        prompt_clasificacion=monitoring_item.get("prompt_clasificacion") or "",
        prompt_clasificacion_vars=list(
            monitoring_item.get("prompt_clasificacion_vars") or []
        ),
        prompt_analista=monitoring_item.get("prompt_analista") or "",
        prompt_analista_vars=list(
            monitoring_item.get("prompt_analista_vars") or []
        ),
        prompt_monitoreo=monitoring_item.get("prompt_monitoreo") or "",
        prompt_monitoreo_vars=list(
            monitoring_item.get("prompt_monitoreo_vars") or []
        ),
    )


def _agent_from_item(agent_item: dict[str, Any]) -> AgentSettings:
    # taxonomies/modus_operandi/flags/example_cases and
    # analyst.playbooks/analyst.voicebot.category_prompts aren't stored on
    # this item (their own tables, see DynamoConfigurationRepository._hydrate)
    # - default to [] here, the caller fills them in after querying.
    return AgentSettings(
        profiling=_profiling_from_item(agent_item.get("profiling") or {}),
        classification=_classification_from_item(
            agent_item.get("classification") or {}
        ),
        adversarial=_adversarial_from_item(agent_item.get("adversarial") or {}),
        analyst=_analyst_from_item(agent_item.get("analyst") or {}),
        documentation=_documentation_from_item(agent_item.get("documentation") or {}),
        active_fields=list(agent_item.get("active_fields") or []),
    )


def _classification_from_item(item: dict[str, Any]) -> ClassificationConfig:
    return ClassificationConfig(
        vector_store_tools=[
            VectorStoreTool(t) for t in item.get("vector_store_tools") or []
        ],
        built_in_tools=[BuiltInTool(t) for t in item.get("built_in_tools") or []],
        prompt=item.get("prompt") or "",
        prompt_vars=list(item.get("prompt_vars") or []),
    )


def _adversarial_from_item(item: dict[str, Any]) -> AdversarialConfig:
    return AdversarialConfig(
        prompt=item.get("prompt") or "",
        prompt_vars=list(item.get("prompt_vars") or []),
        max_cycles=int(item.get("max_cycles", 1)),
        feed_feedback_to_classification=bool(
            item.get("feed_feedback_to_classification", True)
        ),
    )


def _analyst_from_item(item: dict[str, Any]) -> AnalystConfig:
    return AnalystConfig(voicebot=_voicebot_from_item(item.get("voicebot") or {}))


def _voicebot_from_item(item: dict[str, Any]) -> VoicebotConfig:
    return VoicebotConfig(
        base_prompt=item.get("base_prompt") or "",
        base_prompt_vars=list(item.get("base_prompt_vars") or []),
    )


def _documentation_from_item(item: dict[str, Any]) -> DocumentationConfig:
    return DocumentationConfig(
        strategy=DocumentationStrategy(item.get("strategy", "template")),
        template=item.get("template") or "",
        template_vars=list(item.get("template_vars") or []),
        agent_prompt=item.get("agent_prompt") or "",
        agent_prompt_vars=list(item.get("agent_prompt_vars") or []),
    )


def _profiling_from_item(profiling_item: dict[str, Any]) -> ProfilingConfig:
    strategies_raw = profiling_item.get("strategies")
    return ProfilingConfig(
        field_categorizations=[
            _field_categorization_from_item(fc)
            for fc in profiling_item.get("field_categorizations") or []
        ],
        strategies=(
            [_profiling_strategy_from_item(s) for s in strategies_raw]
            if strategies_raw
            else [ProfilingStrategy(key=key) for key in ProfilingStrategyKey]
        ),
    )


def _field_categorization_from_item(item: dict[str, Any]) -> FieldCategorization:
    return FieldCategorization(
        field=item["field"],
        kind=FieldKind(item["kind"]),
        criteria=[
            _field_criterion_from_item(c) for c in item.get("criteria") or []
        ],
        output_variable=item.get("output_variable") or "",
    )


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _criterion_to_item(criterion: FieldCriterion) -> dict[str, Any]:
    item = asdict(criterion)
    for key in ("min_value", "max_value", "numeric_value"):
        if item[key] is not None:
            item[key] = Decimal(str(item[key]))
    return item


def _field_criterion_from_item(item: dict[str, Any]) -> FieldCriterion:
    return FieldCriterion(
        id=item["id"],
        mode=CriteriaMode(item["mode"]),
        output=item["output"],
        min_value=_optional_float(item.get("min_value")),
        max_value=_optional_float(item.get("max_value")),
        operator=ComparisonOperator(item["operator"]) if item.get("operator") else None,
        numeric_value=_optional_float(item.get("numeric_value")),
        text_value=item.get("text_value"),
        values=list(item.get("values") or []),
    )


def _profiling_strategy_from_item(item: dict[str, Any]) -> ProfilingStrategy:
    return ProfilingStrategy(
        key=ProfilingStrategyKey(item["key"]),
        main_prompt=item.get("main_prompt") or "",
        main_prompt_vars=list(item.get("main_prompt_vars") or []),
        main_prompt_mode=ProfilingPromptMode(
            item.get("main_prompt_mode") or ProfilingPromptMode.FSTRING
        ),
        categorization_prompt=item.get("categorization_prompt") or "",
        categorization_prompt_vars=list(
            item.get("categorization_prompt_vars") or []
        ),
        use_pandas_history_mcp=bool(item.get("use_pandas_history_mcp", False)),
    )
