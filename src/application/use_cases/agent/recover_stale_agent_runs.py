from __future__ import annotations

from dataclasses import replace

from src.application.ports.agent_iteration_port import (
    AgentIterationRepository,
    AgentIterationStatus,
)
from src.application.ports.agent_run_port import AgentRunRepository, AgentRunStatus
from src.application.ports.agent_session_port import (
    AgentSessionRepository,
    AgentSessionStatus,
)
from src.application.ports.clock_port import Clock


class RecoverStaleAgentRunsUseCase:
    """Close expired run leases and return active sessions for another tick."""

    def __init__(
        self,
        *,
        sessions: AgentSessionRepository,
        iterations: AgentIterationRepository,
        runs: AgentRunRepository,
        clock: Clock,
    ) -> None:
        self._sessions = sessions
        self._iterations = iterations
        self._runs = runs
        self._clock = clock

    def execute(self, limit: int = 100) -> list[str]:
        now = self._clock.now()
        recovered: list[str] = []
        for run in self._runs.list_stale(now, limit):
            if run.status != AgentRunStatus.RUNNING:
                continue
            self._runs.update(
                replace(
                    run,
                    status=AgentRunStatus.FAILED,
                    lease_expires_at=None,
                    error_code="WORKER_LEASE_EXPIRED",
                )
            )
            iteration = self._iterations.get(run.session_id, run.iteration_number)
            if iteration and iteration.status == AgentIterationStatus.RUNNING:
                self._iterations.update(
                    replace(
                        iteration,
                        status=AgentIterationStatus.FAILED,
                        finished_at=now,
                        decision={"action": "recovered", "error_code": "WORKER_LEASE_EXPIRED"},
                    )
                )
            session = self._sessions.get(run.session_id)
            if session is None:
                continue
            lease_is_stale = (
                session.lease_expires_at is None or session.lease_expires_at <= now
            )
            if lease_is_stale:
                self._sessions.update(
                    replace(
                        session,
                        lease_owner=None,
                        lease_expires_at=None,
                        updated_at=now,
                    ),
                    expected_rev=session.rev,
                )
                if session.status == AgentSessionStatus.ACTIVE:
                    recovered.append(session.session_id)
        return recovered
