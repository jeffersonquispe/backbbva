"""Aggregate optimizer status for the Monitor: no session ids, rows or prompts."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from src.application.ports.agent_budget_ledger_port import AgentBudgetLedgerRepository
from src.application.ports.agent_experiment_port import AgentExperimentRepository
from src.application.ports.agent_iteration_port import (
    AgentIterationRepository,
    AgentIterationStatus,
)
from src.application.ports.agent_run_port import AgentRunRepository
from src.application.ports.agent_session_port import (
    AgentSessionRepository,
    AgentSessionStatus,
)
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettingsPort,
)
from src.application.ports.clock_port import Clock
from src.application.ports.dataset_snapshot_port import DatasetSnapshotRepository
from src.domain.agents.failure_catalog import describe_failure

# Sessions the Monitor counts; terminal ones are history, not current load.
_LIVE_STATUSES = (
    AgentSessionStatus.ACTIVE,
    AgentSessionStatus.WAITING_USER,
    AgentSessionStatus.PAUSED,
)
_RESOURCES = ("tokens", "usd_micros", "seconds")


@dataclass(frozen=True)
class OptimizerSampleUse:
    """A mature sample and how many experiments were measured on it."""

    snapshot_id: str
    period_start: str
    period_end: str
    maturing_days: int
    partition_counts: dict[str, int]
    schema_versions: tuple[int, ...]
    experiments: int


@dataclass(frozen=True)
class OptimizerStatus:
    sessions: dict[str, int] = field(default_factory=dict)
    blocked_by_reason: dict[str, int] = field(default_factory=dict)
    # Spanish title of each blocking code, so readers need no catalogue access.
    reason_titles: dict[str, str] = field(default_factory=dict)
    running_candidates: int = 0
    active_runs: int = 0
    max_concurrent_runs: int = 0
    max_parallel_experiments: int = 0
    max_concurrent_sessions: int = 0
    budget: dict[str, dict[str, int]] = field(default_factory=dict)
    experiments: dict[str, int] = field(default_factory=dict)
    samples: tuple[OptimizerSampleUse, ...] = ()


class GetOptimizerStatusUseCase:
    def __init__(
        self,
        *,
        sessions: AgentSessionRepository,
        iterations: AgentIterationRepository,
        runs: AgentRunRepository,
        budget: AgentBudgetLedgerRepository,
        experiments: AgentExperimentRepository,
        snapshots: DatasetSnapshotRepository,
        settings: AssistantOptimizerSettingsPort,
        clock: Clock,
    ) -> None:
        self._sessions = sessions
        self._iterations = iterations
        self._runs = runs
        self._budget = budget
        self._experiments = experiments
        self._snapshots = snapshots
        self._settings = settings
        self._clock = clock

    def execute(self, limit: int = 50) -> OptimizerStatus:
        settings = self._settings.get()
        live = [
            session
            for status in _LIVE_STATUSES
            for session in self._sessions.list_by_status(status, limit=limit)
            if session.mode == "optimization"
        ]
        running = 0
        spent: Counter[str] = Counter()
        limits: Counter[str] = Counter()
        experiment_status: Counter[str] = Counter()
        by_snapshot: Counter[str] = Counter()
        for session in live:
            running += sum(
                1
                for item in self._iterations.list_for_session(
                    session.session_id, limit=100
                )
                if item.status == AgentIterationStatus.RUNNING
            )
            for entry in self._budget.list_for_session(session.session_id):
                if entry.entry_type == "SPEND" and entry.resource in _RESOURCES:
                    spent[entry.resource] += entry.amount
            for resource in _RESOURCES:
                limits[resource] += int(session.budget_limits.get(resource, 0))
            for experiment in self._experiments.list_for_session(
                session.session_id, 100
            ):
                experiment_status[experiment.status.value] += 1
                if experiment.snapshot_id:
                    by_snapshot[experiment.snapshot_id] += 1
        samples = []
        for snapshot_id, count in by_snapshot.most_common(5):
            snapshot = self._snapshots.get(snapshot_id)
            if snapshot is None:
                continue
            samples.append(
                OptimizerSampleUse(
                    snapshot_id=snapshot.snapshot_id,
                    period_start=snapshot.period_start.isoformat(),
                    period_end=snapshot.period_end.isoformat(),
                    maturing_days=snapshot.maturing_days,
                    partition_counts=dict(snapshot.partition_counts),
                    schema_versions=tuple(snapshot.schema_versions),
                    experiments=count,
                )
            )
        blocked = dict(
            Counter(
                str(session.block.get("code"))
                for session in live
                if session.status == AgentSessionStatus.WAITING_USER
                and session.block.get("code")
            )
        )
        return OptimizerStatus(
            sessions=dict(Counter(session.status.value for session in live)),
            blocked_by_reason=blocked,
            reason_titles={code: describe_failure(code).title for code in blocked},
            running_candidates=running,
            active_runs=len(self._runs.list_active(self._clock.now(), limit=100)),
            max_concurrent_runs=settings.optimizer_max_concurrent_runs,
            max_parallel_experiments=settings.optimizer_max_parallel_experiments,
            max_concurrent_sessions=settings.optimizer_max_concurrent_sessions,
            budget={
                resource: {"spent": spent[resource], "limit": limits[resource]}
                for resource in _RESOURCES
            },
            experiments=dict(experiment_status),
            samples=tuple(samples),
        )
