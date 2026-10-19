from datetime import UTC, datetime

import pytest

from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettings,
)
from src.application.ports.audit_port import AuditEntry
from src.application.use_cases.agent.manage_agent_objective import (
    ActivateAgentObjectiveVersion,
    AgentObjectivePolicyError,
    CreateAgentObjectiveVersion,
)
from src.domain.agents.objective import AgentObjectiveStatus
from src.domain.datasets.mature_sample_entities import MatureSamplerSchemaMapping


class InMemoryObjectives:
    def __init__(self):
        self.items = {}
        self.active = None

    def create(self, objective):
        self.items[(objective.objective_id, objective.version)] = objective
        return objective

    def get(self, objective_id, version):
        return self.items.get((objective_id, version))

    def list_versions(self, objective_id):
        return [item for (name, _), item in self.items.items() if name == objective_id]

    def get_active(self, objective_id):
        return self.active

    def activate(self, objective, *, expected_active_version):
        self.active = objective
        self.items[(objective.objective_id, objective.version)] = objective
        return objective


class FixedClock:
    def now(self):
        return datetime(2026, 10, 19, tzinfo=UTC)


class FixedIds:
    def new_id(self):
        return "correlation"


class InMemoryAudit:
    def __init__(self):
        self.entries = []

    def write(self, entry: AuditEntry):
        self.entries.append(entry)


def test_objective_versions_snapshot_settings_and_activation_is_audited():
    repository = InMemoryObjectives()
    creator = CreateAgentObjectiveVersion(
        objectives=repository,
        optimizer_settings=type(
            "OptimizerSettings",
            (),
            {"get": lambda self: AssistantOptimizerSettings(objective_minimum_support_per_segment=18)},
        )(),
        operational_settings=type(
            "OperationalSettings",
            (),
            {
                "get": lambda self: type(
                    "Runtime",
                    (),
                    {"maturing_days": 4, "expected_coverage_pct": 98.0, "stable_months": 6},
                )()
            },
        )(),
        schema_mapping=type(
            "MappingRepository",
            (),
            {"get": lambda self: MatureSamplerSchemaMapping("mark", "first_date", "label", "marked_at", {"yes": "fraud"})},
        )(),
        clock=FixedClock(),
    )

    first = creator.execute(created_by="manager-1")
    assert first.version == 1
    assert first.status == AgentObjectiveStatus.DRAFT
    assert first.minimum_global_support == 30
    assert first.maturing_days == 4
    assert first.schema_mapping["target_field"] == "label"
    assert creator.execute(created_by="manager-1").version == 2

    audit = InMemoryAudit()
    activated = ActivateAgentObjectiveVersion(
        objectives=repository,
        audit=audit,
        clock=FixedClock(),
        id_generator=FixedIds(),
    ).execute(version=1, actor_id="manager-2", expected_active_version=None)

    assert activated.status == AgentObjectiveStatus.ACTIVE
    assert activated.approved_by == "manager-2"
    assert audit.entries[0].action == "agent.objective.activate"


def test_activation_rejects_stale_expected_active_version():
    repository = InMemoryObjectives()
    creator = CreateAgentObjectiveVersion(
        objectives=repository,
        optimizer_settings=type("Settings", (), {"get": lambda self: AssistantOptimizerSettings()})(),
        operational_settings=type(
            "OperationalSettings",
            (),
            {"get": lambda self: type("Runtime", (), {"maturing_days": 4, "expected_coverage_pct": 98, "stable_months": 6})()},
        )(),
        schema_mapping=type(
            "MappingRepository",
            (),
            {"get": lambda self: MatureSamplerSchemaMapping("mark", "first_date", "label", "marked_at", {})},
        )(),
        clock=FixedClock(),
    )
    creator.execute(created_by="manager")
    repository.active = type("Active", (), {"version": 5})()

    with pytest.raises(AgentObjectivePolicyError, match="active objective version changed"):
        ActivateAgentObjectiveVersion(
            objectives=repository,
            audit=InMemoryAudit(),
            clock=FixedClock(),
            id_generator=FixedIds(),
        ).execute(version=1, actor_id="manager", expected_active_version=None)
