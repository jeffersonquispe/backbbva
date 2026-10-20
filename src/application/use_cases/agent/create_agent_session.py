from __future__ import annotations

from dataclasses import dataclass

from src.application.ports.agent_objective_port import AgentObjectiveRepository
from src.application.ports.agent_prompt_port import AgentPromptRepository
from src.application.ports.agent_session_port import (
    AgentSession,
    AgentSessionRepository,
    AgentSessionStatus,
)
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettingsPort,
)
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.domain.agents.objective import GLOBAL_FRAUD_OBJECTIVE_ID

REQUIRED_PROMPTS = (
    "orchestrator.system",
    "subagent.stub.generator",
    "agent.chat.system",
    "agent.specialist.configuration",
    "agent.specialist.library",
    "agent.specialist.vector_store",
    "agent.specialist.xgboost",
)
OPEN_STATUSES = {
    AgentSessionStatus.DRAFT,
    AgentSessionStatus.ACTIVE,
    AgentSessionStatus.PAUSED,
    AgentSessionStatus.WAITING_USER,
    AgentSessionStatus.WAITING_APPROVAL,
}


@dataclass(frozen=True)
class CreateAgentSessionInput:
    owner_id: str
    mode: str
    scope: dict
    requested_budget: dict[str, int]


class AgentSessionPolicyError(Exception):
    pass


class AgentPromptMissingError(Exception):
    pass


class CreateAgentSessionUseCase:
    def __init__(
        self,
        *,
        sessions: AgentSessionRepository,
        prompts: AgentPromptRepository,
        settings: AssistantOptimizerSettingsPort,
        objectives: AgentObjectiveRepository | None = None,
        clock: Clock,
        id_generator: IdGenerator,
    ) -> None:
        self._sessions = sessions
        self._prompts = prompts
        self._settings = settings
        self._objectives = objectives
        self._clock = clock
        self._ids = id_generator

    def execute(self, request: CreateAgentSessionInput) -> AgentSession:
        settings = self._settings.get()
        if request.mode == "assistant":
            if not settings.assistant_enabled:
                raise AgentSessionPolicyError("assistant sessions are disabled")
        elif request.mode == "optimization":
            if not settings.optimizer_enabled:
                raise AgentSessionPolicyError("optimizer sessions are disabled")
        else:
            raise AgentSessionPolicyError("unsupported session mode")

        existing = self._sessions.list_by_owner(request.owner_id, limit=1000)
        open_sessions = [item for item in existing if item.status in OPEN_STATUSES]
        if len(open_sessions) >= settings.max_sessions_per_user:
            raise AgentSessionPolicyError("session limit reached")
        if request.mode == "optimization":
            active = [
                item
                for item in self._sessions.list_by_status(
                    AgentSessionStatus.ACTIVE,
                    limit=settings.optimizer_max_concurrent_sessions + 1,
                )
                if item.mode == "optimization"
            ]
            if len(active) >= settings.optimizer_max_concurrent_sessions:
                raise AgentSessionPolicyError("optimizer concurrency limit reached")

        ceilings = {
            "tokens": settings.optimizer_session_budget_ceiling_tokens,
            "usd_micros": int(settings.optimizer_session_budget_ceiling_usd * 1_000_000),
            "seconds": settings.optimizer_session_budget_ceiling_seconds,
        }
        budget = {
            key: min(max(0, request.requested_budget.get(key, maximum)), maximum)
            for key, maximum in ceilings.items()
        }
        prompt_versions: dict[str, dict[str, str]] = {}
        for name in REQUIRED_PROMPTS:
            active_prompt = self._prompts.get_active(name)
            if active_prompt is None:
                raise AgentPromptMissingError(f"active prompt missing: {name}")
            prompt = self._prompts.get_version(name, active_prompt.version)
            if prompt is None:
                raise AgentPromptMissingError(f"prompt version missing: {name}")
            prompt_versions[name] = {
                "name": prompt.name,
                "version": str(prompt.version),
                "hash": prompt.content_hash,
            }

        now = self._clock.now()
        active_objective = (
            self._objectives.get_active(GLOBAL_FRAUD_OBJECTIVE_ID)
            if request.mode == "optimization" and self._objectives is not None
            else None
        )
        if (
            request.mode == "optimization"
            and self._objectives is not None
            and active_objective is None
        ):
            raise AgentSessionPolicyError("an active optimizer objective is required")
        session = AgentSession(
            session_id=str(self._ids.new_id()),
            mode=request.mode,
            status=AgentSessionStatus.DRAFT,
            owner_id=request.owner_id,
            created_at=now,
            updated_at=now,
            scope=request.scope,
            objective_id=active_objective.objective_id if active_objective else None,
            objective_version=active_objective.version if active_objective else None,
            budget_limits=budget,
            prompt_versions=prompt_versions,
        )
        return self._sessions.create(session)
