from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from src.application.ports.agent_budget_ledger_port import AgentBudgetEntry
from src.application.ports.agent_iteration_port import (
    AgentIteration,
    AgentIterationStatus,
)
from src.application.ports.agent_run_port import AgentRun, AgentRunStatus
from src.application.ports.agent_session_port import AgentSession, AgentSessionStatus
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettings,
    AssistantOptimizerSettingsPort,
)
from src.application.ports.clock_port import Clock
from src.application.use_cases.agent.get_optimizer_status import (
    GetOptimizerStatusUseCase,
)
from src.domain.agents.experiment import (
    AgentExperiment,
    AgentExperimentKind,
    AgentExperimentStatus,
)
from src.domain.datasets.mature_sample_entities import DatasetSnapshot

NOW = datetime(2026, 10, 26, 15, tzinfo=UTC)


class FixedClock(Clock):
    def now(self) -> datetime:
        return NOW


def _session(session_id, status, mode="optimization", block=None):
    return AgentSession(
        session_id=session_id,
        mode=mode,
        status=status,
        owner_id="cm",
        created_at=NOW,
        updated_at=NOW,
        budget_limits={"tokens": 100, "usd_micros": 1_000, "seconds": 60},
        block=block or {},
    )


class Sessions:
    def __init__(self, *sessions):
        self.sessions = sessions

    def list_by_status(self, status, limit=50):
        return [item for item in self.sessions if item.status == status]


class Iterations:
    def list_for_session(self, session_id, limit=50):
        if session_id != "sess-active-7f3a":
            return []
        return [
            AgentIteration(
                session_id=session_id, number=number, status=status, started_at=NOW
            )
            for number, status in (
                (1, AgentIterationStatus.RUNNING),
                (2, AgentIterationStatus.RUNNING),
                (3, AgentIterationStatus.SUCCEEDED),
            )
        ]


class Runs:
    def list_active(self, now, limit=100):
        return [
            AgentRun(
                run_id=f"r{index}",
                session_id="sess-active-7f3a",
                iteration_number=index,
                subagent="xgboost",
                status=AgentRunStatus.RUNNING,
                prompt_ref={},
                created_at=NOW,
                lease_expires_at=NOW + timedelta(seconds=60),
            )
            for index in (1, 2)
        ]


class Budget:
    def list_for_session(self, session_id, limit=100):
        return [
            AgentBudgetEntry(
                session_id=session_id,
                entry_id="e",
                entry_type="SPEND",
                resource="tokens",
                amount=10,
                actor="agent",
                reason="x",
                created_at=NOW,
            )
        ]


class Experiments:
    def list_for_session(self, session_id, limit=50):
        if session_id != "sess-active-7f3a":
            return []
        return [
            AgentExperiment(
                session_id=session_id,
                experiment_id=f"e{index}",
                iteration_number=index,
                kind=AgentExperimentKind.ISOLATED,
                status=status,
                components=(),
                objective_id="o",
                objective_version=1,
                created_at=NOW,
                snapshot_id="snap-1",
            )
            for index, status in (
                (1, AgentExperimentStatus.SUCCEEDED),
                (2, AgentExperimentStatus.FAILED),
            )
        ]


class Snapshots:
    def get(self, snapshot_id):
        return DatasetSnapshot(
            snapshot_id=snapshot_id,
            specification={},
            period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30),
            maturing_days=30,
            strata_counts={},
            partition_counts={"training": 60, "final": 30},
            schema_versions=(3,),
            content_hash="h",
            trigger="manual",
            dataset_refs={},
            created_at=NOW,
        )


class Settings(AssistantOptimizerSettingsPort):
    def get(self):
        return AssistantOptimizerSettings()

    def update(self, *args, **kwargs):
        raise NotImplementedError


def test_status_aggregates_live_optimizer_sessions_without_ids() -> None:
    use_case = GetOptimizerStatusUseCase(
        sessions=Sessions(
            _session("sess-active-7f3a", AgentSessionStatus.ACTIVE),
            _session(
                "blocked",
                AgentSessionStatus.WAITING_USER,
                block={"code": "BUDGET_EXHAUSTED"},
            ),
            _session("assistant", AgentSessionStatus.ACTIVE, mode="assistant"),
        ),
        iterations=Iterations(),
        runs=Runs(),
        budget=Budget(),
        experiments=Experiments(),
        snapshots=Snapshots(),
        settings=Settings(),
        clock=FixedClock(),
    )

    status = use_case.execute()

    assert status.sessions == {"ACTIVE": 1, "WAITING_USER": 1}
    assert status.blocked_by_reason == {"BUDGET_EXHAUSTED": 1}
    assert status.running_candidates == 2
    assert status.active_runs == 2
    assert (status.max_parallel_experiments, status.max_concurrent_runs) == (3, 6)
    assert status.budget["tokens"] == {"spent": 20, "limit": 200}
    assert status.experiments == {"SUCCEEDED": 1, "FAILED": 1}
    sample = status.samples[0]
    assert (
        sample.experiments,
        sample.partition_counts["final"],
        sample.schema_versions,
    ) == (
        2,
        30,
        (3,),
    )
    assert "sess-active-7f3a" not in repr(status)
    assert "sess-blocked-9c1d" not in repr(status)
