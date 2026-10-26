from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from src.application.errors import ConfigurationWriteConflict
from src.application.ports.configuration_port import (
    ConfigurationRepository,
)
from src.domain.configurations.entities import (
    ConfigurationRecord,
    FilterGroup,
    LogicalOperator,
    ProfilingStrategy,
    ProfilingStrategyKey,
    SamplingCriterion,
    SegmentSettings,
    default_segments,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.repositories.configuration_item_mapping import (
    _distribution_value_from_item,
    _evaluation_from_item,
    _example_case_from_item,
    _filter_condition_from_item,
    _flag_from_item,
    _from_item,
    _general_from_item,
    _infra_from_item,
    _modus_operandi_from_item,
    _owned_item,
    _profiling_strategy_from_item,
    _segment_settings_from_item,
    _segment_to_item,
    _taxonomy_from_item,
    _to_item,
    _voicebot_category_prompt_from_item,
)

CONFIGURATIONS_TABLE_NAME = "configurations"


GENERAL_TABLE_NAME = "configuration_general"


INFRASTRUCTURE_TABLE_NAME = "configuration_infrastructure"


EVALUATION_TABLE_NAME = "configuration_evaluation"


SEGMENTS_TABLE_NAME = "configuration_segments"


PROFILING_STRATEGIES_TABLE_NAME = "configuration_profiling_strategies"


TAXONOMIES_TABLE_NAME = "configuration_taxonomies"


MODUS_OPERANDI_TABLE_NAME = "configuration_modus_operandi"


FLAGS_TABLE_NAME = "configuration_red_yellow_flags"


EXAMPLES_TABLE_NAME = "configuration_examples"


VOICEBOT_PROMPTS_TABLE_NAME = "configuration_voicebot_prompts"


SAMPLING_CRITERIA_TABLE_NAME = "configuration_sampling_criteria"


SAMPLING_CRITERIA_VALUES_TABLE_NAME = "configuration_sampling_criteria_values"


FILTER_GROUPS_TABLE_NAME = "configuration_filter_groups"


FILTER_CONDITIONS_TABLE_NAME = "configuration_filter_conditions"


def _config_key(configuration_id: str, version: int) -> str:
    """FK used by tables scoped to a whole configuration version (not a
    single segment) - e.g. configuration_segments itself."""
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
        self._evaluation = resource.Table(EVALUATION_TABLE_NAME)
        self._segments = resource.Table(SEGMENTS_TABLE_NAME)
        self._profiling_strategies = resource.Table(PROFILING_STRATEGIES_TABLE_NAME)
        self._taxonomies = resource.Table(TAXONOMIES_TABLE_NAME)
        self._modus_operandi = resource.Table(MODUS_OPERANDI_TABLE_NAME)
        self._flags = resource.Table(FLAGS_TABLE_NAME)
        self._examples = resource.Table(EXAMPLES_TABLE_NAME)
        self._voicebot_prompts = resource.Table(VOICEBOT_PROMPTS_TABLE_NAME)
        self._sampling_criteria = resource.Table(SAMPLING_CRITERIA_TABLE_NAME)
        self._sampling_criteria_values = resource.Table(
            SAMPLING_CRITERIA_VALUES_TABLE_NAME
        )
        self._filter_groups = resource.Table(FILTER_GROUPS_TABLE_NAME)
        self._filter_conditions = resource.Table(FILTER_CONDITIONS_TABLE_NAME)

    def create(self, config: ConfigurationRecord) -> ConfigurationRecord:
        return self._write_version(config)

    def mark_tested(self, configuration_id: str, version: int) -> None:
        self._table.update_item(
            Key={"configuration_id": configuration_id, "version": version},
            UpdateExpression="SET ever_tested = :tested",
            ExpressionAttributeValues={":tested": True},
            ConditionExpression="attribute_exists(configuration_id)",
        )

    def _write_version(self, config: ConfigurationRecord) -> ConfigurationRecord:
        try:
            self._table.put_item(
                Item=_to_item(config),
                ConditionExpression="attribute_not_exists(configuration_id)",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ConfigurationWriteConflict(
                    f"Configuration {config.configuration_id}:v{config.version} already exists"
                ) from exc
            raise

        configuration_id, version = config.configuration_id, config.version
        config_key = _config_key(configuration_id, version)
        self._general.put_item(
            Item=_owned_item(configuration_id, version, asdict(config.general))
        )
        self._infrastructure.put_item(
            Item=_owned_item(configuration_id, version, asdict(config.infra))
        )
        self._evaluation.put_item(
            Item=_owned_item(configuration_id, version, asdict(config.test))
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
                self._voicebot_prompts,
                "segment_id",
                segment_id,
                agent.executor.voicebot_call.category_prompts,
            )
            self._put_sampling_criteria(
                segment_id, segment.monitoring.sampling_criteria
            )
        return config

    def get(self, configuration_id: str, version: int) -> ConfigurationRecord | None:
        response = self._table.get_item(
            Key={"configuration_id": configuration_id, "version": version}
        )
        item = response.get("Item")
        return self._hydrate(item) if item else None

    def get_latest_version(self, configuration_id: str) -> ConfigurationRecord | None:
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
        # This API returns summary rows, so scan owner items only and page
        # through the full table. Hydrating every historical version here
        # made the selector slow and a single-page scan hid newer configs
        # once the table grew past DynamoDB's 1 MiB scan response limit.
        for config in self.list_all_versions():
            current = by_lineage.get(config.configuration_id)
            if current is None or config.version > current.version:
                by_lineage[config.configuration_id] = config
        return list(by_lineage.values())

    def list_versions(self, configuration_id: str) -> list[ConfigurationRecord]:
        response = self._table.query(
            KeyConditionExpression=Key("configuration_id").eq(configuration_id),
        )
        return [self._hydrate(item) for item in response.get("Items", [])]

    def list_all_versions(self) -> list[ConfigurationRecord]:
        # Owner-item fields only: _hydrate costs several table reads per
        # version, which made a 237-version scan take ~3.7 s.
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {}
        while True:
            response = self._table.scan(**kwargs)
            items.extend(response.get("Items", []))
            if "LastEvaluatedKey" not in response:
                break
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return [_from_item(item) for item in items]

    def activate(
        self,
        configuration_id: str,
        version: int,
        expected_current: tuple[str, int] | None = None,
    ) -> ConfigurationRecord:
        current_active = self.get_active()
        current_key = (
            (current_active.configuration_id, current_active.version)
            if current_active is not None
            else None
        )
        if expected_current is not None and current_key != expected_current:
            raise ConfigurationWriteConflict(
                "Production configuration changed since this deployment was requested"
            )
        if current_key == (configuration_id, version):
            activated = self.get(configuration_id, version)
            assert activated is not None
            return activated

        now = datetime.now(UTC).isoformat()
        client = self._table.meta.client
        updates = []
        if current_active is not None:
            current_condition = (
                "active = :active AND configuration_id = :current_configuration_id "
                "AND version = :current_version"
            )
            updates.append(
                {
                    "Update": {
                        "TableName": self._table.name,
                        "Key": {
                            "configuration_id": current_active.configuration_id,
                            "version": current_active.version,
                        },
                        "UpdateExpression": "SET active = :inactive, updated_at = :updated_at",
                        "ConditionExpression": current_condition,
                        "ExpressionAttributeValues": {
                            ":inactive": False,
                            ":active": True,
                            ":current_configuration_id": current_active.configuration_id,
                            ":current_version": current_active.version,
                            ":updated_at": now,
                        },
                    }
                }
            )
        updates.append(
            {
                "Update": {
                    "TableName": self._table.name,
                    "Key": {
                        "configuration_id": configuration_id,
                        "version": version,
                    },
                    "UpdateExpression": "SET active = :active, ever_activated = :ever_activated, activated_at = :activated_at, updated_at = :updated_at",
                    "ConditionExpression": "attribute_exists(configuration_id) AND active = :inactive",
                    "ExpressionAttributeValues": {
                        ":active": True,
                        ":inactive": False,
                        ":ever_activated": True,
                        ":activated_at": now,
                        ":updated_at": now,
                    },
                }
            }
        )
        try:
            client.transact_write_items(TransactItems=updates)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code == "TransactionCanceledException":
                raise ConfigurationWriteConflict(
                    "Production configuration changed during deployment; refresh and retry"
                ) from exc
            raise
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
        activated_at: datetime | None = None,
    ) -> None:
        expression = "SET active = :active, updated_at = :updated_at"
        values: dict[str, Any] = {
            ":active": active,
            ":updated_at": datetime.now(UTC).isoformat(),
        }
        # ever_activated is sticky - only ever set to True (going live),
        # never reset back to False when a version is later superseded.
        if ever_activated:
            expression += ", ever_activated = :ever_activated"
            values[":ever_activated"] = True
        if activated_at is not None:
            expression += ", activated_at = :activated_at"
            values[":activated_at"] = activated_at.isoformat()
        self._table.update_item(
            Key={"configuration_id": configuration_id, "version": version},
            UpdateExpression=expression,
            ExpressionAttributeValues=values,
        )

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
        evaluation_item = self._evaluation.get_item(
            Key={"configuration_id": configuration_id, "version": version}
        ).get("Item")

        config.general = _general_from_item(general_item or {})
        config.infra = _infra_from_item(infra_item or {})
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
            agent.executor.voicebot_call.category_prompts = self._query_entities(
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
            criteria.append(
                SamplingCriterion(id=item["id"], name=item["name"], values=values)
            )
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
        return [by_key[key] for key in ProfilingStrategyKey if key in by_key] or [
            ProfilingStrategy(key=key) for key in ProfilingStrategyKey
        ]

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
