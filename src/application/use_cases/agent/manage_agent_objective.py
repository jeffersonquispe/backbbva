from __future__ import annotations

from dataclasses import replace

from src.application.ports.agent_objective_port import AgentObjectiveRepository
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettingsPort,
)
from src.application.ports.audit_port import AuditEntry, AuditPort
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.mature_sampler_schema_mapping_port import (
    MatureSamplerSchemaMappingRepository,
)
from src.application.ports.operational_settings_port import (
    OperationalSettingsRepository,
)
from src.domain.agents.objective import (
    GLOBAL_FRAUD_OBJECTIVE_ID,
    AgentObjective,
    AgentObjectiveStatus,
)

MINIMUM_AGGREGATE_COUNT = 30


class AgentObjectiveNotFoundError(Exception):
    pass


class AgentObjectivePolicyError(Exception):
    pass


class CreateAgentObjectiveVersion:
    def __init__(
        self,
        *,
        objectives: AgentObjectiveRepository,
        optimizer_settings: AssistantOptimizerSettingsPort,
        operational_settings: OperationalSettingsRepository,
        schema_mapping: MatureSamplerSchemaMappingRepository,
        clock: Clock,
    ) -> None:
        self._objectives = objectives
        self._optimizer_settings = optimizer_settings
        self._operational_settings = operational_settings
        self._schema_mapping = schema_mapping
        self._clock = clock

    def execute(self, *, created_by: str) -> AgentObjective:
        settings = self._optimizer_settings.get()
        operational = self._operational_settings.get()
        mapping = self._schema_mapping.get()
        if (
            settings.objective_precision_floor <= 0
            or settings.objective_precision_floor > 1
            or settings.objective_minimum_support_per_segment < 1
            or settings.objective_minimum_mature_alert_coverage_pct < 0
            or settings.objective_minimum_mature_alert_coverage_pct > 100
        ):
            raise AgentObjectivePolicyError("objective settings are invalid")
        versions = self._objectives.list_versions(GLOBAL_FRAUD_OBJECTIVE_ID)
        version = max((item.version for item in versions), default=0) + 1
        return self._objectives.create(
            AgentObjective(
                objective_id=GLOBAL_FRAUD_OBJECTIVE_ID,
                version=version,
                success_label="fraud_label",
                positive_label="fraud",
                negative_label="no_fraud",
                maturing_days=operational.maturing_days,
                expected_coverage_pct=operational.expected_coverage_pct,
                stable_months=operational.stable_months,
                primary_metrics=("precision", "recall"),
                precision_floor=settings.objective_precision_floor,
                minimum_support_per_segment=settings.objective_minimum_support_per_segment,
                minimum_global_support=max(
                    MINIMUM_AGGREGATE_COUNT,
                    settings.objective_minimum_support_per_segment,
                ),
                minimum_count_to_publish_aggregates=max(
                    MINIMUM_AGGREGATE_COUNT,
                    settings.objective_minimum_count_to_publish_aggregates,
                ),
                minimum_mature_alert_coverage_pct=(
                    settings.objective_minimum_mature_alert_coverage_pct
                ),
                unlabeled_rule="exclude_pending_from_precision_and_recall",
                schema_mapping={
                    "initial_mark_field": mapping.initial_mark_field,
                    "initial_marking_date_field": mapping.initial_marking_date_field,
                    "target_field": mapping.target_field,
                    "marking_date_field": mapping.marking_date_field,
                    "label_value_mapping": mapping.label_value_mapping or {},
                },
                status=AgentObjectiveStatus.DRAFT,
                created_by=created_by,
                created_at=self._clock.now(),
            )
        )


class ActivateAgentObjectiveVersion:
    def __init__(
        self,
        *,
        objectives: AgentObjectiveRepository,
        audit: AuditPort,
        clock: Clock,
        id_generator: IdGenerator,
    ) -> None:
        self._objectives = objectives
        self._audit = audit
        self._clock = clock
        self._ids = id_generator

    def execute(
        self,
        *,
        version: int,
        actor_id: str,
        expected_active_version: int | None,
    ) -> AgentObjective:
        objective = self._objectives.get(GLOBAL_FRAUD_OBJECTIVE_ID, version)
        if objective is None:
            raise AgentObjectiveNotFoundError("objective version not found")
        if objective.status != AgentObjectiveStatus.DRAFT:
            raise AgentObjectivePolicyError("only a draft objective can be activated")
        current = self._objectives.get_active(GLOBAL_FRAUD_OBJECTIVE_ID)
        actual_version = current.version if current else None
        if actual_version != expected_active_version:
            raise AgentObjectivePolicyError("active objective version changed")
        now = self._clock.now()
        activated = replace(
            objective,
            status=AgentObjectiveStatus.ACTIVE,
            approved_by=actor_id,
            activated_at=now,
        )
        saved = self._objectives.activate(
            activated, expected_active_version=expected_active_version
        )
        self._audit.write(
            AuditEntry(
                actor_type="user",
                actor_id=actor_id,
                worker_name=None,
                action="agent.objective.activate",
                entity_type="agent_objective",
                entity_id=f"{saved.objective_id}:{saved.version}",
                correlation_id=str(self._ids.new_id()),
                parent_id=None,
                occurred_at=now,
                outcome="success",
            )
        )
        return saved
