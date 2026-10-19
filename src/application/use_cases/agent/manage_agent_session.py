from __future__ import annotations

from dataclasses import replace

from src.application.ports.agent_session_port import (
    AgentSession,
    AgentSessionRepository,
    AgentSessionStatus,
)
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettingsPort,
)
from src.application.ports.clock_port import Clock


class AgentSessionNotFoundError(Exception):
    pass


class AgentSessionStateError(Exception):
    pass


class ManageAgentSessionUseCase:
    def __init__(
        self,
        repository: AgentSessionRepository,
        clock: Clock,
        settings: AssistantOptimizerSettingsPort | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._settings = settings

    def list_for_owner(self, owner_id: str, limit: int = 50) -> list[AgentSession]:
        return self._repository.list_by_owner(owner_id, limit)

    def get(self, session_id: str, owner_id: str) -> AgentSession:
        session = self._owned(session_id, owner_id)
        return session

    def pause(self, session_id: str, owner_id: str) -> AgentSession:
        return self._transition(
            session_id,
            owner_id,
            AgentSessionStatus.ACTIVE,
            AgentSessionStatus.PAUSED,
        )

    def start(self, session_id: str, owner_id: str) -> AgentSession:
        session = self._owned(session_id, owner_id)
        if session.status != AgentSessionStatus.DRAFT:
            raise AgentSessionStateError("only draft sessions can be started")
        if self._settings is None:
            raise AgentSessionStateError("session policy is unavailable")
        settings = self._settings.get()
        if session.mode == "assistant" and not settings.assistant_enabled:
            raise AgentSessionStateError("assistant sessions are disabled")
        if session.mode == "optimization":
            if not settings.optimizer_enabled:
                raise AgentSessionStateError("optimizer sessions are disabled")
            active = [
                item
                for item in self._repository.list_by_status(
                    AgentSessionStatus.ACTIVE,
                    limit=settings.optimizer_max_concurrent_sessions + 1,
                )
                if item.mode == "optimization"
            ]
            if len(active) >= settings.optimizer_max_concurrent_sessions:
                raise AgentSessionStateError("optimizer concurrency limit reached")
        return self._save(session, AgentSessionStatus.ACTIVE)

    def resume(self, session_id: str, owner_id: str) -> AgentSession:
        return self._transition(
            session_id,
            owner_id,
            AgentSessionStatus.PAUSED,
            AgentSessionStatus.ACTIVE,
        )

    def cancel(self, session_id: str, owner_id: str) -> AgentSession:
        session = self._owned(session_id, owner_id)
        if session.status in {
            AgentSessionStatus.COMPLETED,
            AgentSessionStatus.STOPPED,
            AgentSessionStatus.CANCELLED,
            AgentSessionStatus.FAILED,
        }:
            raise AgentSessionStateError("terminal session cannot be cancelled")
        return self._save(session, AgentSessionStatus.CANCELLED)

    def _transition(
        self,
        session_id: str,
        owner_id: str,
        expected: AgentSessionStatus,
        target: AgentSessionStatus,
    ) -> AgentSession:
        session = self._owned(session_id, owner_id)
        if session.status != expected:
            raise AgentSessionStateError(
                f"session must be {expected.value.lower()} to transition"
            )
        return self._save(session, target)

    def _owned(self, session_id: str, owner_id: str) -> AgentSession:
        session = self._repository.get(session_id)
        if session is None or session.owner_id != owner_id:
            raise AgentSessionNotFoundError("session not found")
        return session

    def _save(
        self, session: AgentSession, status: AgentSessionStatus
    ) -> AgentSession:
        updated = replace(session, status=status, updated_at=self._clock.now())
        return self._repository.update(updated, expected_rev=session.rev)
