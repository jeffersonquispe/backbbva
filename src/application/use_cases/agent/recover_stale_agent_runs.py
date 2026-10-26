from __future__ import annotations

from dataclasses import replace

from src.application.ports.agent_experiment_port import AgentExperimentRepository
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
from src.application.ports.monitoring_port import MonitoringPort
from src.application.use_cases.agent.agent_timeline import AgentTimeline
from src.domain.agents.event import AgentEventKind
from src.domain.agents.experiment import AgentExperimentStatus

LEASE_EXPIRED = "WORKER_LEASE_EXPIRED"


class RecoverStaleAgentRunsUseCase:
    """Close expired run leases and return active sessions for another tick."""

    def __init__(
        self,
        *,
        sessions: AgentSessionRepository,
        iterations: AgentIterationRepository,
        runs: AgentRunRepository,
        clock: Clock,
        experiments: AgentExperimentRepository | None = None,
        timeline: AgentTimeline | None = None,
        monitoring: MonitoringPort | None = None,
    ) -> None:
        self._sessions = sessions
        self._iterations = iterations
        self._runs = runs
        self._experiments = experiments
        self._timeline = timeline
        self._monitoring = monitoring
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
                    error_code=LEASE_EXPIRED,
                )
            )
            iteration = self._iterations.get(run.session_id, run.iteration_number)
            if iteration and iteration.status == AgentIterationStatus.RUNNING:
                self._iterations.update(
                    replace(
                        iteration,
                        status=AgentIterationStatus.FAILED,
                        finished_at=now,
                        decision={"action": "recovered", "error_code": LEASE_EXPIRED},
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
                    self._record(session.session_id, now)
        for session in self._sessions.list_by_status(
            AgentSessionStatus.ACTIVE, limit=limit
        ):
            if session.session_id in recovered:
                continue
            if session.lease_expires_at is None or session.lease_expires_at > now:
                continue
            self._close_orphaned_work(session.session_id, now)
            self._sessions.update(
                replace(
                    session, lease_owner=None, lease_expires_at=None, updated_at=now
                ),
                expected_rev=session.rev,
            )
            recovered.append(session.session_id)
            self._record(session.session_id, now)
        return recovered

    def _record(self, session_id: str, now) -> None:
        if self._monitoring is not None:
            self._monitoring.record_optimizer_recovery(LEASE_EXPIRED)
        if self._timeline is not None:
            self._timeline.record_failure(
                session_id,
                AgentEventKind.RECOVERY,
                LEASE_EXPIRED,
                occurred_at=now,
            )

    def _close_orphaned_work(self, session_id: str, now) -> None:
        """Close iteration/experiment records left RUNNING by a dead orchestrator.

        The run may already be finished (so it is not listed as stale) while the
        orchestrator died before closing the iteration or the experiment.
        """
        for iteration in self._iterations.list_for_session(session_id, limit=100):
            if iteration.status == AgentIterationStatus.RUNNING:
                self._iterations.update(
                    replace(
                        iteration,
                        status=AgentIterationStatus.FAILED,
                        finished_at=now,
                        decision={"action": "recovered", "error_code": LEASE_EXPIRED},
                    )
                )
        if self._experiments is None:
            return
        for experiment in self._experiments.list_for_session(session_id, limit=100):
            if experiment.status == AgentExperimentStatus.RUNNING:
                self._experiments.update(
                    replace(
                        experiment,
                        status=AgentExperimentStatus.FAILED,
                        completed_at=now,
                        error_code=LEASE_EXPIRED,
                    ),
                    expected_status=AgentExperimentStatus.RUNNING.value,
                )
