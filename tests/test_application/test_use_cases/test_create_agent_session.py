from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from src.application.ports.agent_experiment_component_port import (
    AgentExperimentComponentResolver,
)
from src.application.ports.agent_objective_port import AgentObjectiveRepository
from src.application.ports.agent_prompt_port import (
    ActiveAgentPrompt,
    AgentPrompt,
    AgentPromptRepository,
)
from src.application.ports.agent_session_port import (
    AgentSession,
    AgentSessionRepository,
)
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettings,
    AssistantOptimizerSettingsPort,
)
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.use_cases.agent.create_agent_session import (
    REQUIRED_PROMPTS,
    AgentSessionPolicyError,
    CreateAgentSessionInput,
    CreateAgentSessionUseCase,
)
from src.domain.agents.experiment import ComponentVersionReference
from src.domain.agents.objective import (
    GLOBAL_FRAUD_OBJECTIVE_ID,
    AgentObjective,
    AgentObjectiveStatus,
)

NOW = datetime(2026, 10, 20, tzinfo=UTC)


class InMemorySessions(AgentSessionRepository):
    def __init__(self) -> None:
        self.created: AgentSession | None = None

    def create(self, session: AgentSession) -> AgentSession:
        self.created = session
        return session

    def get(self, session_id: str) -> AgentSession | None:
        return None

    def list_by_owner(self, owner_id: str, limit: int = 50) -> list[AgentSession]:
        return []

    def list_by_status(self, status, limit: int = 50) -> list[AgentSession]:
        return []

    def update(self, session: AgentSession, expected_rev: int) -> AgentSession:
        return session

    def acquire_lease(self, session_id, owner, now, expires_at):
        return None

    def increment_message_seq(self, session_id: str) -> int:
        return 0


class InMemoryPrompts(AgentPromptRepository):
    def __init__(self) -> None:
        self.prompts = {
            name: AgentPrompt(
                name=name,
                version=1,
                content=f"prompt {name}",
                content_hash=f"hash-{name}",
                status="ACTIVE",
                created_at=NOW,
            )
            for name in REQUIRED_PROMPTS
        }

    def create_version(self, prompt: AgentPrompt) -> AgentPrompt:
        self.prompts[prompt.name] = prompt
        return prompt

    def get_version(self, name: str, version: int) -> AgentPrompt | None:
        prompt = self.prompts.get(name)
        return prompt if prompt and prompt.version == version else None

    def get_active(self, name: str) -> ActiveAgentPrompt | None:
        prompt = self.prompts.get(name)
        return ActiveAgentPrompt(name, prompt.version, NOW, "test") if prompt else None

    def activate(self, pointer, expected_version):
        return None


class InMemoryObjectives(AgentObjectiveRepository):
    def __init__(self, objective: AgentObjective | None) -> None:
        self.objective = objective

    def create(self, objective: AgentObjective) -> AgentObjective:
        return objective

    def get(self, objective_id: str, version: int) -> AgentObjective | None:
        if self.objective and (objective_id, version) == (
            self.objective.objective_id,
            self.objective.version,
        ):
            return self.objective
        return None

    def list_versions(self, objective_id: str) -> list[AgentObjective]:
        return [self.objective] if self.objective else []

    def get_active(self, objective_id: str) -> AgentObjective | None:
        return self.objective if self.objective_id_matches(objective_id) else None

    def activate(self, objective, *, expected_active_version):
        self.objective = objective
        return objective

    def objective_id_matches(self, objective_id: str) -> bool:
        return (
            self.objective is not None and self.objective.objective_id == objective_id
        )


class InMemorySettings(AssistantOptimizerSettingsPort):
    def get(self) -> AssistantOptimizerSettings:
        return AssistantOptimizerSettings(
            optimizer_enabled=True,
            optimizer_max_concurrent_sessions=3,
        )

    def update(
        self, settings: AssistantOptimizerSettings
    ) -> AssistantOptimizerSettings:
        return settings


class FixedClock(Clock):
    def now(self) -> datetime:
        return NOW


class FixedIds(IdGenerator):
    def new_id(self) -> UUID:
        return UUID(int=123)


class InMemoryBaselineResolver(AgentExperimentComponentResolver):
    def active_baseline(self):
        return tuple(
            ComponentVersionReference.pin(
                component, f"{component}-id", "1", {"component": component}
            )
            for component in ("model", "configuration", "library", "vector_store")
        )

    def pin(self, component, entity_id, version):
        return None

    def resolve(self, reference):
        return None


def _objective(version: int) -> AgentObjective:
    return AgentObjective(
        objective_id=GLOBAL_FRAUD_OBJECTIVE_ID,
        version=version,
        success_label="fraud_label",
        positive_label="fraud",
        negative_label="no_fraud",
        maturing_days=4,
        expected_coverage_pct=98.0,
        stable_months=6,
        primary_metrics=("precision", "recall"),
        precision_floor=0.91,
        minimum_support_per_segment=30,
        minimum_global_support=30,
        minimum_count_to_publish_aggregates=30,
        minimum_mature_alert_coverage_pct=80.0,
        unlabeled_rule="exclude_pending_from_precision_and_recall",
        schema_mapping={},
        status=AgentObjectiveStatus.ACTIVE,
        created_by="manager-1",
        created_at=NOW,
    )


def test_optimization_session_pins_active_objective_version_and_all_prompts() -> None:
    sessions = InMemorySessions()
    objective = _objective(5)
    use_case = CreateAgentSessionUseCase(
        sessions=sessions,
        prompts=InMemoryPrompts(),
        objectives=InMemoryObjectives(objective),
        components=InMemoryBaselineResolver(),
        settings=InMemorySettings(),
        clock=FixedClock(),
        id_generator=FixedIds(),
    )

    created = use_case.execute(
        CreateAgentSessionInput(
            owner_id="owner-safe",
            mode="optimization",
            scope={"areas": ["model"]},
            requested_budget={},
        )
    )

    assert created.objective_id == GLOBAL_FRAUD_OBJECTIVE_ID
    assert created.objective_version == 5
    assert {item.component for item in created.baseline_components} == {
        "model",
        "configuration",
        "library",
        "vector_store",
    }
    assert set(created.prompt_versions) == set(REQUIRED_PROMPTS)
    assert sessions.created == created


def test_optimization_session_requires_an_active_objective() -> None:
    use_case = CreateAgentSessionUseCase(
        sessions=InMemorySessions(),
        prompts=InMemoryPrompts(),
        objectives=InMemoryObjectives(None),
        settings=InMemorySettings(),
        clock=FixedClock(),
        id_generator=FixedIds(),
    )

    with pytest.raises(AgentSessionPolicyError, match="active optimizer objective"):
        use_case.execute(
            CreateAgentSessionInput(
                owner_id="owner-safe",
                mode="optimization",
                scope={"areas": ["model"]},
                requested_budget={},
            )
        )
