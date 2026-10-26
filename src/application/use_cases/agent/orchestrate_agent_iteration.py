from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from src.application.ports.agent_audit_port import AgentAuditEvent, AgentAuditRepository
from src.application.ports.agent_budget_ledger_port import (
    AgentBudgetEntry,
    AgentBudgetLedgerRepository,
)
from src.application.ports.agent_candidate_dispatcher_port import (
    AgentCandidateDispatcher,
)
from src.application.ports.agent_experiment_component_port import (
    AgentExperimentComponentResolver,
)
from src.application.ports.agent_experiment_port import AgentExperimentRepository
from src.application.ports.agent_hypothesis_port import (
    AgentHypothesis,
    AgentHypothesisRepository,
    AgentHypothesisStatus,
)
from src.application.ports.agent_insight_port import (
    AgentInsightKind,
    AgentInsightRepository,
    AgentInsightStatus,
)
from src.application.ports.agent_iteration_port import (
    AgentIteration,
    AgentIterationRepository,
    AgentIterationStatus,
)
from src.application.ports.agent_link_port import AgentLink, AgentLinkRepository
from src.application.ports.agent_objective_port import AgentObjectiveRepository
from src.application.ports.agent_package_port import (
    AgentPackage,
    AgentPackageRepository,
)
from src.application.ports.agent_run_port import (
    AgentRun,
    AgentRunRepository,
    AgentRunStatus,
)
from src.application.ports.agent_session_port import (
    AgentSession,
    AgentSessionRepository,
    AgentSessionStatus,
)
from src.application.ports.agent_session_summary_port import (
    AgentSessionSummary,
    AgentSessionSummaryRepository,
)
from src.application.ports.agent_subagent_port import (
    AgentSubagent,
    AgentSubagentInput,
    AgentSubagentOutput,
)
from src.application.ports.agent_verification_port import (
    AgentVerification,
    AgentVerificationRepository,
)
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettingsPort,
)
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.optimization_run_port import OptimizationRunRepository
from src.application.ports.project_graph_port import ProjectGraphRepository
from src.application.use_cases.agent.agent_timeline import AgentTimeline
from src.application.use_cases.agent.evaluate_agent_experiment import (
    EvaluateAgentExperiment,
)
from src.application.use_cases.agent.optimizer_memory import OptimizerMemory
from src.domain.agents.event import AgentEventKind, AgentEventOutcome
from src.domain.agents.experiment import AgentExperimentKind
from src.domain.agents.optimization_run import (
    COMBINATION_AREA,
    OptimizationRun,
    OptimizationRunConflictError,
    OptimizationRunStatus,
    RunWinner,
    component_for_area,
    experiment_stream_key,
    rank_winners,
)
from src.domain.project_graph.index import tokenize

LEASE_SECONDS = 90
_SAFE_AUDIT_REASONS = {
    "LEASE_ACQUIRED",
    "LEASE_RELEASED",
    "LEASE_EXPIRED",
    "CONTEXT_UNAVAILABLE",
    "DISPATCH_FAILED",
    "EVALUATION_FAILED",
    "EXECUTION_FAILED",
    "EXECUTION_INVALID",
    "GENERATION_FAILED",
    "GENERATION_INVALID",
    "GLOBAL_EVALUATION_FAILED",
    "PROMPT_NOT_PINNED",
    "PROMPT_UNAVAILABLE",
    "PROMPT_VERSION_MISMATCH",
    "RUN_CANCELLED",
    "WORKER_LEASE_EXPIRED",
    "CONFIGURATION_CHANGES_REQUIRED",
    "ACTIVE_CONFIGURATION_REQUIRED",
    "CONFIGURATION_PATH_OR_VALUE_INVALID",
    "CONFIGURATION_CANDIDATE_REJECTED",
    "LIBRARY_DRAFT_INVALID",
    "PERSONAL_DATA_BLOCKED",
    "LIBRARY_REFERENCE_INVALID",
    "LIBRARY_DUPLICATE",
    "PLAYBOOK_FALLBACK_INVALID",
    "VECTOR_QUERY_NOT_AUTHORIZED",
    "VECTOR_MANIFEST_UNAVAILABLE",
    "VECTOR_MANIFEST_EMPTY",
    "VECTOR_CANDIDATE_BUILD_FAILED",
    "VECTOR_CANDIDATE_VERIFICATION_FAILED",
    "AUTHORIZED_MODEL_BASELINE_REQUIRED",
    "TRAINING_PARAMETER_NOT_SUPPORTED",
    "MODEL_CANDIDATE_LOST",
    "MODEL_TRAINING_FAILED",
    "MODEL_CANDIDATE_START_FAILED",
    "MODEL_TRAINING_BUDGET_INVALID",
    "MODEL_REPORT_INCOMPLETE",
}


@dataclass
class _Gate:
    """Admission result: the session passed the kill switch and concurrency caps."""

    session_id: str
    session: AgentSession
    settings: Any
    objective: Any
    now: datetime


@dataclass
class _Tick:
    """Mutable state shared by the phases of one orchestrator tick."""

    session_id: str
    settings: Any
    objective: Any
    leased: AgentSession
    now: datetime
    effective_budget: dict[str, int]
    prior: list[AgentIteration]
    hypothesis: AgentHypothesis | None
    cost_before: int
    number: int
    run_id: str
    run: AgentRun
    iteration: AgentIteration
    subagent: Any
    project_map: dict[str, dict[str, str]]
    finished: datetime
    output: Any = None
    finding_ids: tuple[str, ...] = ()
    cost_micros: int | None = None


def _decision_summary(decision: dict[str, object]) -> str:
    if decision.get("action") == "stop":
        return "El agente se detiene y espera tu decisión"
    if decision.get("improved") is True:
        return "El agente mejoró el objetivo y continúa"
    if decision.get("improved") is False:
        return "Sin mejora en esta iteración; el agente continúa"
    return "El agente continúa con la siguiente iteración"


class OrchestrateAgentIterationUseCase:
    """Advance one persisted iteration, re-reading policy on every tick."""

    def __init__(
        self,
        *,
        sessions: AgentSessionRepository,
        iterations: AgentIterationRepository,
        runs: AgentRunRepository,
        budget: AgentBudgetLedgerRepository,
        packages: AgentPackageRepository,
        verifications: AgentVerificationRepository,
        settings: AssistantOptimizerSettingsPort,
        subagent: AgentSubagent,
        clock: Clock,
        id_generator: IdGenerator,
        hypotheses: AgentHypothesisRepository | None = None,
        insights: AgentInsightRepository | None = None,
        links: AgentLinkRepository | None = None,
        summaries: AgentSessionSummaryRepository | None = None,
        specialists: dict[str, AgentSubagent] | None = None,
        objectives: AgentObjectiveRepository | None = None,
        monitoring: MonitoringPort | None = None,
        audit: AgentAuditRepository | None = None,
        components: AgentExperimentComponentResolver | None = None,
        experiment_evaluator: EvaluateAgentExperiment | None = None,
        project_graph: ProjectGraphRepository | None = None,
        timeline: AgentTimeline | None = None,
        memory: OptimizerMemory | None = None,
        experiments: AgentExperimentRepository | None = None,
        optimization_runs: OptimizationRunRepository | None = None,
        dispatcher: AgentCandidateDispatcher | None = None,
    ) -> None:
        self._sessions = sessions
        self._iterations = iterations
        self._runs = runs
        self._budget = budget
        self._packages = packages
        self._verifications = verifications
        self._settings = settings
        self._subagent = subagent
        self._clock = clock
        self._ids = id_generator
        self._hypotheses = hypotheses
        self._insights = insights
        self._links = links
        self._summaries = summaries
        self._specialists = specialists or {}
        self._objectives = objectives
        self._monitoring = monitoring
        self._audit = audit
        self._components = components
        self._experiment_evaluator = experiment_evaluator
        self._project_graph = project_graph
        self._timeline = timeline
        self._memory = memory
        self._experiments = experiments
        self._optimization_runs = optimization_runs
        self._dispatcher = dispatcher

    def execute(self, session_id: str) -> str:
        """One orchestrator tick: admit, plan, then run or dispatch candidates.

        Each phase persists before the next one begins and records its own
        timeline event, so a crash leaves a visible, recoverable trace. With a
        dispatcher, optimizer candidates run as separate jobs in parallel and
        this tick only plans them; without one, the single candidate runs here.
        """
        gate = self._admit(session_id)
        if isinstance(gate, str):
            return gate
        planned = self._start_iteration(gate)
        if isinstance(planned, str):
            return planned
        if self._parallel(gate.session) and self._dispatcher is not None:
            self._release_lease(planned[0].leased, gate.now)
            for candidate in planned:
                self._dispatcher.dispatch(candidate.session_id, candidate.number)
            return f"dispatched_{len(planned)}"
        tick = planned[0]
        self._run_specialist(tick)
        return self._finish_iteration(tick)

    def run_candidate(self, session_id: str, number: int) -> str:
        """Run one planned candidate (a dispatched job) to its conclusion."""
        tick = self._resume_candidate(session_id, number)
        if isinstance(tick, str):
            return tick
        self._run_specialist(tick)
        return self._finish_iteration(tick, owns_lease=False)

    def _parallel(self, session: AgentSession) -> bool:
        return self._dispatcher is not None and session.mode == "optimization"

    # ------------------------------------------------------------------ admit
    def _admit(self, session_id: str) -> _Gate | str:
        # Settings are deliberately read on each invocation, never captured in
        # the factory or session snapshot, so kill switches take immediate effect.
        current_settings = self._settings.get()
        session = self._sessions.get(session_id)
        if session is None or session.status != AgentSessionStatus.ACTIVE:
            return "not_active"
        objective = (
            self._objectives.get(session.objective_id, session.objective_version)
            if self._objectives is not None
            and session.objective_id
            and session.objective_version is not None
            else None
        )
        if (
            session.objective_id
            and session.objective_version is not None
            and objective is None
        ):
            self._sessions.update(
                replace(
                    session,
                    status=AgentSessionStatus.STOPPED,
                    updated_at=self._clock.now(),
                ),
                expected_rev=session.rev,
            )
            self._event(
                session_id,
                AgentEventKind.SESSION,
                AgentEventOutcome.FAILED,
                "Sesión detenida: el objetivo fijado ya no existe",
            )
            return "stopped_missing_objective"
        if objective is not None:
            current_settings = replace(
                current_settings,
                objective_precision_floor=objective.precision_floor,
            )

        enabled = (
            current_settings.assistant_enabled
            if session.mode == "assistant"
            else current_settings.optimizer_enabled
        )
        if not enabled:
            self._sessions.update(
                replace(
                    session,
                    status=AgentSessionStatus.PAUSED,
                    updated_at=self._clock.now(),
                ),
                expected_rev=session.rev,
            )
            self._event(
                session_id,
                AgentEventKind.SESSION,
                AgentEventOutcome.INFO,
                "Sesión en pausa: el interruptor de seguridad está apagado",
            )
            return "paused_by_kill_switch"

        now = self._clock.now()
        if session.mode == "optimization":
            active_optimizers = [
                item
                for item in self._sessions.list_by_status(
                    AgentSessionStatus.ACTIVE,
                    limit=current_settings.optimizer_max_concurrent_sessions + 1,
                )
                if item.mode == "optimization"
            ]
            if (
                len(active_optimizers)
                > current_settings.optimizer_max_concurrent_sessions
            ):
                return "deferred_by_session_limit"
            if self._dispatcher is None:
                active_runs = self._runs.list_active(now, limit=100)
                if len(active_runs) >= current_settings.optimizer_max_concurrent_runs:
                    return "deferred_by_run_limit"
        return _Gate(session_id, session, current_settings, objective, now)

    # ------------------------------------------------------------------ start
    def _start_iteration(self, gate: _Gate) -> list[_Tick] | str:
        session_id, now = gate.session_id, gate.now
        current_settings = gate.settings
        lease_expires = now + timedelta(seconds=LEASE_SECONDS)
        if (
            gate.session.lease_expires_at is not None
            and gate.session.lease_expires_at <= now
        ):
            self._record_audit(session_id, now, "lease", "expired", "LEASE_EXPIRED")
        leased = self._sessions.acquire_lease(
            session_id, str(self._ids.new_id()), now, lease_expires
        )
        if leased is None:
            return "lease_unavailable"
        self._record_audit(session_id, now, "lease", "succeeded", "LEASE_ACQUIRED")

        limits = {
            "tokens": current_settings.optimizer_session_budget_ceiling_tokens,
            "usd_micros": int(
                current_settings.optimizer_session_budget_ceiling_usd * 1_000_000
            ),
            "seconds": current_settings.optimizer_session_budget_ceiling_seconds,
        }
        effective_budget = {
            resource: min(leased.budget_limits.get(resource, maximum), maximum)
            for resource, maximum in limits.items()
        }
        if (
            leased.mode == "optimization"
            and len(self._packages.list_for_session(session_id, limit=100))
            >= current_settings.optimizer_max_candidates_per_session
            + leased.candidate_allowance
        ):
            return self._block(
                leased, now, "CANDIDATE_LIMIT_REACHED", "blocked_by_candidate_limit"
            )

        prior = self._iterations.list_for_session(session_id, limit=100)
        self._ensure_run_root(leased, current_settings, now)
        if self._parallel(leased):
            in_flight = [
                item for item in prior if item.status == AgentIterationStatus.RUNNING
            ]
            active_runs = self._runs.list_active(now, limit=100)
            slots = min(
                current_settings.optimizer_max_parallel_experiments - len(in_flight),
                current_settings.optimizer_max_concurrent_runs - len(active_runs),
            )
            if slots <= 0:
                self._release_lease(leased, now)
                return (
                    "waiting_for_experiments" if in_flight else "deferred_by_run_limit"
                )
            hypotheses: list[AgentHypothesis | None] = list(
                self._select_candidates(leased, now, prior, in_flight, slots)
            )
            if not hypotheses:
                if in_flight:
                    self._release_lease(leased, now)
                    return "waiting_for_experiments"
                if self._current_winners(session_id):
                    return self._complete(leased, now)
        else:
            hypotheses = [self._select_hypothesis(leased, now, prior)]
            if (
                hypotheses == [None]
                and leased.mode == "optimization"
                and self._hypotheses
            ):
                hypotheses = []
        if leased.mode == "optimization" and self._hypotheses and not hypotheses:
            self._save_session_memory(
                session_id,
                leased,
                now,
                {
                    "action": "blocked",
                    "reason": "no_signal",
                    "completed_iterations": len(prior),
                },
            )
            return self._block(leased, now, "CONTEXT_MISSING", "blocked_no_context")

        cost_before = sum(
            entry.amount
            for entry in self._budget.list_for_session(session_id)
            if entry.entry_type == "SPEND" and entry.resource == "usd_micros"
        )
        number = max((item.number for item in prior), default=0) + 1
        planned: list[_Tick] = []
        for hypothesis in hypotheses:
            if not self._reserve_budget(session_id, effective_budget, now):
                if planned:
                    break
                return self._block(leased, now, "BUDGET_EXHAUSTED", "blocked_by_budget")
            planned.append(
                self._open_candidate(
                    gate,
                    leased,
                    hypothesis,
                    prior,
                    number,
                    effective_budget,
                    cost_before,
                    lease_expires,
                )
            )
            number += 1
        return planned

    def _reserve_budget(self, session_id, effective_budget, now) -> bool:
        for resource in ("tokens", "usd_micros", "seconds"):
            if not self._budget.reserve(
                session_id, resource, 1, effective_budget[resource]
            ):
                return False
            self._budget.append(
                AgentBudgetEntry(
                    session_id=session_id,
                    entry_id=str(self._ids.new_id()),
                    entry_type="SPEND",
                    resource=resource,
                    amount=1,
                    actor="agent",
                    reason="stub iteration reservation",
                    created_at=now,
                )
            )
        return True

    def _open_candidate(
        self,
        gate: _Gate,
        leased: AgentSession,
        hypothesis: AgentHypothesis | None,
        prior: list[AgentIteration],
        number: int,
        effective_budget: dict[str, int],
        cost_before: int,
        lease_expires: datetime,
    ) -> _Tick:
        session_id, now = gate.session_id, gate.now
        run_id = str(self._ids.new_id())
        selected_subagent = (
            _COMBINATION_SUBAGENT
            if _is_combination(hypothesis)
            else self._select_subagent(leased, hypothesis, prior)
        )
        project_map = self._optimizer_project_map()
        prompt_key = (
            f"agent.specialist.{selected_subagent.name}"
            if selected_subagent.name in self._specialists
            else selected_subagent.name
        )
        prompt_ref = leased.prompt_versions.get(prompt_key, {})
        if not prompt_ref:
            prompt_ref = {
                "name": f"subagent.{selected_subagent.name}",
                "version": "0",
                "hash": "stub",
            }
        run = AgentRun(
            run_id=run_id,
            session_id=session_id,
            iteration_number=number,
            subagent=selected_subagent.name,
            status=AgentRunStatus.RUNNING,
            prompt_ref={key: str(value) for key, value in prompt_ref.items()},
            created_at=now,
            lease_expires_at=lease_expires,
        )
        self._runs.create(run)
        iteration = AgentIteration(
            session_id=session_id,
            number=number,
            status=AgentIterationStatus.RUNNING,
            started_at=now,
            run_ids=(run_id,),
            decision=(
                {"hypothesis_id": hypothesis.hypothesis_id, "action": "running"}
                if hypothesis is not None
                else {}
            ),
        )
        self._iterations.create(iteration)
        self._record_audit(session_id, now, "session", "started")
        self._record_audit(session_id, now, "iteration", "started")
        self._record_audit(
            session_id, now, "specialist", "started", specialist=selected_subagent.name
        )
        self._record_audit(
            session_id, now, "tool", "started", tool=selected_subagent.name
        )
        refs = {"iteration": number, "run_id": run_id}
        self._event(
            session_id,
            AgentEventKind.ITERATION,
            AgentEventOutcome.STARTED,
            f"Iteración {number} iniciada",
            refs=refs,
            occurred_at=now,
        )
        if hypothesis is not None:
            self._event(
                session_id,
                AgentEventKind.HYPOTHESIS,
                AgentEventOutcome.STARTED,
                "Hipótesis en prueba",
                refs={**refs, "hypothesis_id": hypothesis.hypothesis_id},
                occurred_at=now,
            )
        self._event(
            session_id,
            AgentEventKind.SPECIALIST,
            AgentEventOutcome.STARTED,
            f"Especialista {selected_subagent.name} en ejecución",
            refs={**refs, "specialist": selected_subagent.name},
            occurred_at=now,
        )
        return _Tick(
            session_id=session_id,
            settings=gate.settings,
            objective=gate.objective,
            leased=leased,
            now=now,
            effective_budget=effective_budget,
            prior=prior,
            hypothesis=hypothesis,
            cost_before=cost_before,
            number=number,
            run_id=run_id,
            run=run,
            iteration=iteration,
            subagent=selected_subagent,
            project_map=project_map,
            finished=now,
        )

    def _resume_candidate(self, session_id: str, number: int) -> _Tick | str:
        """Rebuild a planned candidate from what the tick persisted."""
        settings = self._settings.get()
        session = self._sessions.get(session_id)
        iteration = self._iterations.get(session_id, number)
        if (
            session is None
            or iteration is None
            or iteration.status != AgentIterationStatus.RUNNING
            or not iteration.run_ids
        ):
            return "candidate_not_running"
        run = self._runs.get(iteration.run_ids[0])
        if run is None or run.status != AgentRunStatus.RUNNING:
            return "candidate_not_running"
        hypothesis_id = iteration.decision.get("hypothesis_id")
        hypothesis = next(
            (
                item
                for item in (
                    self._hypotheses.list_for_session(session_id)
                    if self._hypotheses is not None
                    else []
                )
                if item.hypothesis_id == hypothesis_id
            ),
            None,
        )
        objective = (
            self._objectives.get(session.objective_id, session.objective_version)
            if self._objectives is not None
            and session.objective_id
            and session.objective_version is not None
            else None
        )
        if objective is not None:
            settings = replace(
                settings, objective_precision_floor=objective.precision_floor
            )
        limits = {
            "tokens": settings.optimizer_session_budget_ceiling_tokens,
            "usd_micros": int(
                settings.optimizer_session_budget_ceiling_usd * 1_000_000
            ),
            "seconds": settings.optimizer_session_budget_ceiling_seconds,
        }
        subagent = (
            _COMBINATION_SUBAGENT
            if run.subagent == _COMBINATION_SUBAGENT.name
            else self._specialists.get(run.subagent, self._subagent)
        )
        now = self._clock.now()
        return _Tick(
            session_id=session_id,
            settings=settings,
            objective=objective,
            leased=session,
            now=now,
            effective_budget={
                resource: min(session.budget_limits.get(resource, maximum), maximum)
                for resource, maximum in limits.items()
            },
            prior=[
                item
                for item in self._iterations.list_for_session(session_id, limit=100)
                if item.number != number
            ],
            hypothesis=hypothesis,
            cost_before=sum(
                entry.amount
                for entry in self._budget.list_for_session(session_id)
                if entry.entry_type == "SPEND" and entry.resource == "usd_micros"
            ),
            number=number,
            run_id=run.run_id,
            run=run,
            iteration=iteration,
            subagent=subagent,
            project_map=self._optimizer_project_map(),
            finished=now,
        )

    def _release_lease(self, leased: AgentSession, now) -> None:
        current = self._sessions.get(leased.session_id) or leased
        self._sessions.update(
            replace(current, lease_owner=None, lease_expires_at=None, updated_at=now),
            expected_rev=current.rev,
        )
        self._record_audit(
            leased.session_id, now, "lease", "succeeded", "LEASE_RELEASED"
        )

    def _block(self, leased: AgentSession, now, code: str, result: str) -> str:
        """Stop and wait for the Channel Manager; never fail silently."""
        self._sessions.update(
            replace(
                leased,
                status=AgentSessionStatus.WAITING_USER,
                lease_owner=None,
                lease_expires_at=None,
                updated_at=now,
                block={"code": code, "since": now.isoformat()},
            ),
            expected_rev=leased.rev,
        )
        self._record_audit(
            leased.session_id, now, "lease", "succeeded", "LEASE_RELEASED"
        )
        if self._timeline is not None:
            self._timeline.record_blocked(leased.session_id, code, occurred_at=now)
        if self._monitoring is not None:
            self._monitoring.record_optimizer_block(code)
        return result

    # -------------------------------------------------------------- specialist
    def _run_specialist(self, tick: _Tick) -> None:
        session_id, now, number = tick.session_id, tick.now, tick.number
        leased, objective = tick.leased, tick.objective
        selected_subagent, hypothesis = tick.subagent, tick.hypothesis
        subagent_input = AgentSubagentInput(
            session_id=session_id,
            iteration_number=number,
            scope=leased.scope,
            hypothesis=(
                hypothesis.statement
                if hypothesis is not None
                else "Exercise the configured specialist."
            ),
            budget=tick.effective_budget,
            prompt_versions=leased.prompt_versions,
            objective_id=leased.objective_id,
            objective_version=leased.objective_version,
            objective=objective,
            baseline_components=leased.baseline_components,
            project_map=tick.project_map,
        )
        if self._monitoring is None:
            tick.output = self._call_subagent(tick, subagent_input)
        else:
            # Identifiers belong on trace spans for audit correlation, never
            # on metric dimensions. Tool/specialist names and states are
            # bounded values; no experiment rows or prompt content are sent.
            with self._monitoring.start(
                "agent.session",
                "agent",
                {"agent.session_id": session_id, "agent.status": "ACTIVE"},
            ) as session_span:
                with self._monitoring.start(
                    "agent.iteration",
                    "agent",
                    {
                        "agent.session_id": session_id,
                        "agent.iteration": number,
                        "agent.status": "RUNNING",
                    },
                ) as iteration_span:
                    with self._monitoring.start(
                        "agent.specialist",
                        "agent",
                        {
                            "agent.specialist": selected_subagent.name,
                            "agent.status": "RUNNING",
                        },
                    ) as specialist_span:
                        with self._monitoring.start(
                            "agent.tool",
                            "agent",
                            {
                                "agent.tool": selected_subagent.name,
                                "agent.status": "RUNNING",
                            },
                        ) as tool_span:
                            tick.output = self._call_subagent(tick, subagent_input)
                    output = tick.output
                    duration_ms = max(
                        0, int((self._clock.now() - now).total_seconds() * 1000)
                    )
                    audit_result = {
                        "agent.status": (
                            "FAILED" if output.error_code else "SUCCEEDED"
                        ),
                        "agent.duration_ms": duration_ms,
                        "agent.specialist": selected_subagent.name,
                    }
                    cost = output.safe_metrics.get("cost_usd_micros")
                    if not isinstance(cost, (int, float)):
                        cost = (
                            sum(
                                entry.amount
                                for entry in self._budget.list_for_session(session_id)
                                if entry.entry_type == "SPEND"
                                and entry.resource == "usd_micros"
                            )
                            - tick.cost_before
                        )
                    if isinstance(cost, (int, float)) and cost >= 0:
                        audit_result["agent.cost_usd_micros"] = int(cost)
                    iteration_span.write_operation_metas(audit_result)
                    session_span.write_operation_metas(audit_result)
                    specialist_span.write_operation_metas(audit_result)
                    tool_span.write_operation_metas(audit_result)
        tick.finished = self._clock.now()
        output = tick.output
        elapsed_ms = max(0, int((tick.finished - now).total_seconds() * 1000))
        result_status = "failed" if output.error_code else "succeeded"
        cost_value = output.safe_metrics.get("cost_usd_micros")
        cost_micros = (
            int(cost_value)
            if isinstance(cost_value, (int, float)) and cost_value >= 0
            else None
        )
        tick.cost_micros = cost_micros
        for category, extra in (
            ("tool", {"tool": selected_subagent.name}),
            ("specialist", {"specialist": selected_subagent.name}),
            ("iteration", {}),
        ):
            self._record_audit(
                session_id,
                tick.finished,
                category,
                result_status,
                output.error_code,
                elapsed_ms,
                cost_micros,
                **extra,
            )
        refs = {
            "iteration": number,
            "run_id": tick.run_id,
            "specialist": selected_subagent.name,
        }
        if output.error_code:
            if self._timeline is not None:
                self._timeline.record_failure(
                    session_id,
                    AgentEventKind.SPECIALIST,
                    _safe_specialist_error_code(output.error_code),
                    refs=refs,
                    duration_ms=elapsed_ms,
                    occurred_at=tick.finished,
                )
        else:
            self._event(
                session_id,
                AgentEventKind.SPECIALIST,
                AgentEventOutcome.SUCCEEDED,
                f"Especialista {selected_subagent.name} terminó",
                refs=refs,
                duration_ms=elapsed_ms,
                cost_micros=cost_micros,
                occurred_at=tick.finished,
            )

    # ------------------------------------------------------------------ finish
    def _finish_iteration(self, tick: _Tick, *, owns_lease: bool = True) -> str:
        session_id, now, number = tick.session_id, tick.now, tick.number
        leased, hypothesis = tick.leased, tick.hypothesis
        current_settings, prior = tick.settings, tick.prior
        selected_subagent, run, run_id = tick.subagent, tick.run, tick.run_id
        iteration, output, finished = tick.iteration, tick.output, tick.finished
        current_session = self._sessions.get(session_id)
        if current_session is None:
            return "session_missing_after_run"
        if current_session.status == AgentSessionStatus.CANCELLED:
            self._runs.update(
                replace(
                    run,
                    status=AgentRunStatus.CANCELLED,
                    lease_expires_at=None,
                    error_code="RUN_CANCELLED",
                )
            )
            self._iterations.update(
                replace(
                    iteration,
                    status=AgentIterationStatus.FAILED,
                    finished_at=finished,
                    decision={"action": "cancelled"},
                )
            )
            if owns_lease:
                self._sessions.update(
                    replace(
                        current_session,
                        lease_owner=None,
                        lease_expires_at=None,
                        updated_at=finished,
                    ),
                    expected_rev=current_session.rev,
                )
                self._record_audit(
                    session_id, finished, "lease", "succeeded", "LEASE_RELEASED"
                )
            self._event(
                session_id,
                AgentEventKind.ITERATION,
                AgentEventOutcome.FAILED,
                f"Iteración {number} cancelada",
                reason_code="RUN_CANCELLED",
                refs={"iteration": number, "run_id": run_id},
                occurred_at=finished,
            )
            return "cancelled"
        self._runs.update(
            AgentRun(
                run_id=run.run_id,
                session_id=run.session_id,
                iteration_number=run.iteration_number,
                subagent=run.subagent,
                status=(
                    AgentRunStatus.SUCCEEDED
                    if output.error_code is None
                    else AgentRunStatus.FAILED
                ),
                prompt_ref=run.prompt_ref,
                created_at=run.created_at,
                lease_expires_at=None,
                error_code=output.error_code,
            )
        )
        package_id = self._persist_package(tick)
        verification_id = str(self._ids.new_id())
        self._verifications.create(
            AgentVerification(
                verification_id=verification_id,
                subject_id=package_id or run_id,
                verifier=f"{selected_subagent.name}_contract",
                status=output.verification_status,
                safe_metrics=output.safe_metrics,
                error_code=output.error_code,
                created_at=finished,
            )
        )
        verified = output.verification_status == "PASSED" and output.error_code is None
        self._event(
            session_id,
            AgentEventKind.VERIFICATION,
            AgentEventOutcome.SUCCEEDED if verified else AgentEventOutcome.FAILED,
            "Verificación aprobada" if verified else "Verificación no aprobada",
            reason_code=_safe_specialist_error_code(output.error_code),
            refs={
                "iteration": number,
                "run_id": run_id,
                "verification_id": verification_id,
                "package_id": package_id,
            },
            occurred_at=finished,
        )
        experiment = self._run_experiment(tick, verified)
        outcome = None
        if hypothesis is not None and self._hypotheses is not None:
            outcome = self._resolve_hypothesis(
                tick, verified, verification_id, experiment
            )
        self._learn(tick, experiment, outcome)
        decision = _iteration_decision(
            mode=leased.mode,
            prior=[
                item for item in prior if item.number > leased.stagnation_reset_after
            ],
            metrics=output.safe_metrics if verified else {},
            verification_id=verification_id,
            error_code=output.error_code,
            settings=current_settings,
        )
        if hypothesis is not None:
            decision["hypothesis"] = hypothesis.statement
            decision["hypothesis_id"] = hypothesis.hypothesis_id
        if tick.cost_micros is not None:
            decision["cost_micros"] = tick.cost_micros
            if (
                _is_cost_anomaly(prior, tick.cost_micros)
                and decision.get("action") != "stop"
            ):
                decision.update({"action": "stop", "reason": "cost_anomaly"})
        decision["specialist"] = selected_subagent.name
        decision["verification_status"] = output.verification_status
        decision["specialist_verified"] = verified
        decision["failure_stage"] = (
            "specialist_execution" if output.error_code else None
        )
        decision["failure_code"] = _safe_specialist_error_code(output.error_code)
        decision["experiment_verified"] = bool(
            experiment is not None and experiment.status.value == "SUCCEEDED"
        )
        decision["objective_id"] = leased.objective_id
        decision["objective_version"] = leased.objective_version
        if experiment is not None:
            decision["experiment_id"] = experiment.experiment_id
            decision["experiment_status"] = experiment.status.value
            decision["global_evaluation"] = experiment.global_evaluation
        self._iterations.update(
            AgentIteration(
                session_id=session_id,
                number=number,
                status=(
                    AgentIterationStatus.SUCCEEDED
                    if output.error_code is None
                    else AgentIterationStatus.FAILED
                ),
                started_at=now,
                finished_at=finished,
                run_ids=(run_id,),
                package_id=package_id,
                decision=decision,
            )
        )
        stop_reason = (
            decision.get("reason") if decision.get("action") == "stop" else None
        )
        block_code = {
            "critical_failure": "CRITICAL_FAILURE",
            "stagnation": "STAGNATION",
            "cost_anomaly": "COST_ANOMALY",
        }.get(str(stop_reason))
        if owns_lease:
            if current_session.mode == "assistant":
                terminal_status = AgentSessionStatus.PAUSED
            elif block_code is not None:
                terminal_status = AgentSessionStatus.WAITING_USER
            else:
                terminal_status = current_session.status
            self._sessions.update(
                replace(
                    current_session,
                    status=terminal_status,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=finished,
                    block=(
                        {
                            "code": block_code,
                            "since": finished.isoformat(),
                            "iteration": number,
                        }
                        if block_code is not None
                        and current_session.mode != "assistant"
                        else current_session.block
                    ),
                ),
                expected_rev=current_session.rev,
            )
            self._record_audit(
                session_id, finished, "lease", "succeeded", "LEASE_RELEASED"
            )
        elif block_code is not None:
            self._set_block(session_id, block_code, finished, number)
        iteration_refs = {"iteration": number, "run_id": run_id}
        self._event(
            session_id,
            AgentEventKind.ITERATION,
            AgentEventOutcome.FAILED
            if output.error_code
            else AgentEventOutcome.SUCCEEDED,
            f"Iteración {number} terminó",
            reason_code=_safe_specialist_error_code(output.error_code),
            refs=iteration_refs,
            duration_ms=max(0, int((finished - now).total_seconds() * 1000)),
            occurred_at=finished,
        )
        self._event(
            session_id,
            AgentEventKind.DECISION,
            AgentEventOutcome.BLOCKED if block_code else AgentEventOutcome.INFO,
            _decision_summary(decision),
            reason_code=block_code,
            refs={**iteration_refs, "verification_id": verification_id},
            occurred_at=finished,
        )
        if block_code is not None and self._timeline is not None:
            self._timeline.record_blocked(
                session_id, block_code, refs=iteration_refs, occurred_at=finished
            )
        if self._monitoring is not None:
            self._monitoring.record_optimizer_iteration(
                selected_subagent.name,
                "FAILED" if output.error_code else "SUCCEEDED",
                max(0.0, (finished - now).total_seconds()),
            )
            if block_code is not None:
                self._monitoring.record_optimizer_block(block_code)
        if self._summaries is not None:
            self._save_session_memory(
                session_id,
                current_session,
                finished,
                {
                    "iteration": number,
                    "hypothesis": hypothesis.statement if hypothesis else None,
                    "outcome": (
                        hypothesis.evidence_outcome
                        if hypothesis
                        else output.verification_status
                    ),
                    "evidence_id": verification_id,
                    "decision": decision,
                },
            )
        self._refresh_run_root(session_id, finished)
        if block_code == "CRITICAL_FAILURE":
            return "blocked_by_critical_failure"
        if block_code == "STAGNATION":
            return "blocked_by_stagnation"
        if block_code == "COST_ANOMALY":
            return "blocked_by_cost_anomaly"
        return "iteration_completed"

    def _persist_package(self, tick: _Tick) -> str | None:
        leased, output, finished = tick.leased, tick.output, tick.finished
        has_optimization_proposal = (
            leased.mode == "optimization"
            and bool(output.contribution)
            and output.error_code is None
        )
        if not (leased.mode == "assistant" or has_optimization_proposal):
            return None
        package_id = str(self._ids.new_id())
        content = {
            "subagent": output.subagent,
            "contribution": output.contribution,
            "verification_status": output.verification_status,
            "experiment_candidate_components": [
                {
                    "component": item.component,
                    "entity_id": item.entity_id,
                    "version": item.version,
                    "content_sha256": item.content_sha256,
                }
                for item in output.experiment_candidate_components
            ],
        }
        content_hash = hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self._packages.create(
            AgentPackage(
                package_id=package_id,
                session_id=tick.session_id,
                iteration_number=tick.number,
                status=(
                    "SEALED"
                    if leased.mode == "assistant"
                    else "VERIFIED"
                    if output.verification_status == "PASSED"
                    and output.error_code is None
                    else "PENDING_VERIFICATION"
                ),
                content=content,
                content_hash=content_hash,
                created_at=finished,
                sealed_at=(
                    finished
                    if leased.mode == "assistant"
                    or (
                        output.verification_status == "PASSED"
                        and output.error_code is None
                    )
                    else None
                ),
            )
        )
        return package_id

    def _run_experiment(self, tick: _Tick, verified: bool):
        leased, output, finished = tick.leased, tick.output, tick.finished
        session_id, number = tick.session_id, tick.number
        if not (
            leased.mode == "optimization"
            and verified
            and output.experiment_candidate_components
            and self._experiment_evaluator is not None
        ):
            return None
        baseline_by_type = {item.component: item for item in leased.baseline_components}
        candidate_by_type = {
            item.component: item for item in output.experiment_candidate_components
        }
        required_types = {"model", "configuration", "library", "vector_store"}
        if not (
            set(candidate_by_type) == required_types
            and set(baseline_by_type) == required_types
        ):
            return None
        changed = sum(
            candidate_by_type[name] != baseline_by_type[name] for name in required_types
        )
        if not changed:
            return None
        self._record_audit(session_id, finished, "experiment", "started")
        experiment_id = str(self._ids.new_id())
        refs = {
            "iteration": number,
            "experiment_id": experiment_id,
            "run_id": tick.run_id,
        }
        if tick.hypothesis is not None:
            refs["hypothesis_id"] = tick.hypothesis.hypothesis_id
        self._event(
            session_id,
            AgentEventKind.EXPERIMENT,
            AgentEventOutcome.STARTED,
            "Experimento iniciado",
            refs=refs,
            occurred_at=finished,
        )
        experiment = self._experiment_evaluator.execute(
            experiment_id=experiment_id,
            session_id=session_id,
            kind=(
                AgentExperimentKind.ISOLATED
                if changed == 1
                else AgentExperimentKind.COMBINATION
            ),
            iteration_number=number,
            components=tuple(
                candidate_by_type[name] for name in sorted(required_types)
            ),
            baseline_components=tuple(
                baseline_by_type[name] for name in sorted(required_types)
            ),
            objective_id=leased.objective_id or "",
            objective_version=leased.objective_version or 0,
            candidate_id=(
                tick.hypothesis.hypothesis_id if tick.hypothesis is not None else None
            ),
        )
        self._experiment_stream_event(session_id, experiment, refs)
        experiment_status = (
            "succeeded" if experiment.status.value == "SUCCEEDED" else "failed"
        )
        audit_reason = (
            "GLOBAL_CONSTRAINT_REJECTED"
            if experiment.status.value == "REJECTED_GLOBAL_CONSTRAINT"
            else experiment.error_code
        )
        self._record_audit(
            session_id,
            self._clock.now(),
            "experiment",
            experiment_status,
            audit_reason,
        )
        if experiment.status.value == "SUCCEEDED":
            self._event(
                session_id,
                AgentEventKind.EXPERIMENT,
                AgentEventOutcome.SUCCEEDED,
                "Experimento cumplió el objetivo global",
                refs=refs,
            )
        elif experiment.status.value == "REJECTED_GLOBAL_CONSTRAINT":
            self._event(
                session_id,
                AgentEventKind.EXPERIMENT,
                AgentEventOutcome.FAILED,
                "Experimento rechazado: incumple una restricción global",
                reason_code="GLOBAL_CONSTRAINT_REJECTED",
                refs=refs,
            )
        elif self._timeline is not None:
            self._timeline.record_failure(
                session_id,
                AgentEventKind.EXPERIMENT,
                experiment.error_code,
                refs=refs,
            )
        self._remember_experiment(tick, experiment, refs)
        return experiment

    def _remember_experiment(self, tick: _Tick, experiment, refs) -> None:
        """Persist aggregate findings and re-check what earlier sessions learned."""
        if self._memory is None or not experiment.global_evaluation:
            return
        findings = self._memory.record_experiment_findings(
            session_id=tick.session_id,
            experiment_id=experiment.experiment_id,
            evaluation=experiment.global_evaluation,
            snapshot_id=experiment.snapshot_id,
        )
        tick.finding_ids = tuple(item.finding_id for item in findings)
        if findings:
            self._event(
                tick.session_id,
                AgentEventKind.EXPERIMENT,
                AgentEventOutcome.INFO,
                "Hallazgos agregados registrados",
                refs={**refs, "finding_id": findings[0].finding_id},
            )
        self._memory.reevaluate(
            tick.subagent.name,
            improved=experiment.status.value == "SUCCEEDED",
            sample_count=int(experiment.global_evaluation.get("eligible_count") or 0),
        )

    def _learn(self, tick: _Tick, experiment, outcome) -> None:
        """A validated, well-supported result becomes memory for future sessions."""
        if (
            self._memory is None
            or experiment is None
            or outcome != AgentHypothesisStatus.VALIDATED
            or experiment.status.value != "SUCCEEDED"
        ):
            return
        insight = self._memory.learn(
            area=tick.subagent.name,
            statement=(
                tick.hypothesis.statement
                if tick.hypothesis is not None
                else f"El área {tick.subagent.name} mejora el objetivo global."
            ),
            evaluation=experiment.global_evaluation,
            session_id=tick.session_id,
            run_id=tick.run_id,
            finding_ids=tick.finding_ids,
            snapshot_ids=(experiment.snapshot_id,) if experiment.snapshot_id else (),
        )
        if insight is not None:
            self._event(
                tick.session_id,
                AgentEventKind.EXPERIMENT,
                AgentEventOutcome.INFO,
                "Aprendizaje guardado para futuras sesiones",
                refs={"experiment_id": experiment.experiment_id},
            )

    def _resolve_hypothesis(
        self,
        tick: _Tick,
        verified: bool,
        verification_id: str,
        experiment=None,
    ) -> AgentHypothesisStatus | None:
        hypothesis, output, finished = tick.hypothesis, tick.output, tick.finished
        session_id = tick.session_id
        if hypothesis is None or self._hypotheses is None:
            return None
        # An experiment measured against the mature sample is the strongest
        # evidence; the specialist's own metrics are the fallback.
        evaluation = (experiment.global_evaluation or {}) if experiment else {}
        measured = evaluation.get("candidate") or {}
        baseline = evaluation.get("baseline") or {}
        precision = measured.get("precision", output.safe_metrics.get("precision"))
        recall = measured.get("recall", output.safe_metrics.get("recall"))
        if experiment is not None and experiment.status.value in {
            "REJECTED_GLOBAL_CONSTRAINT",
            "FAILED",
        }:
            outcome = (
                AgentHypothesisStatus.REFUTED
                if experiment.status.value == "REJECTED_GLOBAL_CONSTRAINT"
                else AgentHypothesisStatus.NONCONCLUSIVE
            )
        elif (
            verified
            and isinstance(precision, (int, float))
            and isinstance(recall, (int, float))
        ):
            outcome = (
                AgentHypothesisStatus.VALIDATED
                if precision >= tick.settings.objective_precision_floor
                else AgentHypothesisStatus.REFUTED
            )
        else:
            outcome = AgentHypothesisStatus.NONCONCLUSIVE
        base_recall = baseline.get("recall")
        recall_delta = (
            float(recall) - float(base_recall)
            if isinstance(recall, (int, float))
            and isinstance(base_recall, (int, float))
            else None
        )
        conclusion = {
            "verdict": outcome.value,
            "summary": _conclusion_summary(outcome, recall_delta),
            "evidence": {
                key: value
                for key, value in {
                    "precision": precision,
                    "recall": recall,
                    "baseline_recall": base_recall,
                    "recall_delta": recall_delta,
                    "sample_count": evaluation.get("eligible_count"),
                }.items()
                if isinstance(value, (int, float))
            },
            "experiment_id": experiment.experiment_id if experiment else None,
            "verification_id": verification_id,
            "decision": {
                AgentHypothesisStatus.VALIDATED: "keep",
                AgentHypothesisStatus.REFUTED: "discard",
            }.get(outcome, "retry"),
            "recommendation": {
                AgentHypothesisStatus.VALIDATED: (
                    "Candidato a promover o a combinar con otros ganadores."
                ),
                AgentHypothesisStatus.REFUTED: "Descartar este cambio.",
            }.get(outcome, "Repetir con más evidencia o con otro enfoque."),
            "decided_at": finished.isoformat(),
        }
        self._hypotheses.update(
            replace(
                hypothesis,
                status=outcome,
                evidence_id=verification_id,
                evidence_outcome=outcome.value,
                updated_at=finished,
                conclusion=conclusion,
            ),
            expected_rev=hypothesis.rev,
        )
        self._event(
            session_id,
            AgentEventKind.HYPOTHESIS,
            {
                AgentHypothesisStatus.VALIDATED: AgentEventOutcome.SUCCEEDED,
                AgentHypothesisStatus.REFUTED: AgentEventOutcome.FAILED,
            }.get(outcome, AgentEventOutcome.INFO),
            {
                AgentHypothesisStatus.VALIDATED: "Hipótesis validada",
                AgentHypothesisStatus.REFUTED: "Hipótesis refutada",
            }.get(outcome, "Hipótesis inconclusa"),
            refs={
                "iteration": tick.number,
                "hypothesis_id": hypothesis.hypothesis_id,
                "verification_id": verification_id,
            },
            occurred_at=finished,
        )
        if not (hypothesis.source_insight_id and self._insights is not None):
            return outcome
        source_insight = self._insights.get(session_id, hypothesis.source_insight_id)
        if source_insight is not None and outcome in {
            AgentHypothesisStatus.VALIDATED,
            AgentHypothesisStatus.REFUTED,
        }:
            self._insights.update(
                replace(
                    source_insight,
                    status=(
                        AgentInsightStatus.APPLIED
                        if outcome == AgentHypothesisStatus.VALIDATED
                        else AgentInsightStatus.REFUTED
                    ),
                    updated_at=finished,
                ),
                expected_rev=source_insight.rev,
            )
        if self._links is not None:
            self._links.create_once(
                AgentLink(
                    session_id=session_id,
                    source_type="insight",
                    source_id=hypothesis.source_insight_id,
                    relation=(
                        "supported_by"
                        if outcome == AgentHypothesisStatus.VALIDATED
                        else "refuted_by"
                        if outcome == AgentHypothesisStatus.REFUTED
                        else "inconclusive_by"
                    ),
                    target_type="verification",
                    target_id=verification_id,
                    created_at=finished,
                )
            )
        return outcome

    # --------------------------------------------------- parallel candidates
    def _call_subagent(self, tick: _Tick, subagent_input: AgentSubagentInput):
        if tick.subagent is _COMBINATION_SUBAGENT:
            return self._combination_output(tick)
        return tick.subagent.execute(subagent_input)

    def _combination_output(self, tick: _Tick) -> AgentSubagentOutput:
        """Merge each winner's changed component into one candidate stack."""
        hypothesis = tick.hypothesis
        experiments = (
            self._experiments.list_for_session(tick.session_id, limit=200)
            if self._experiments is not None
            else []
        )
        stack = {pin.component: pin for pin in tick.leased.baseline_components}
        merged: list[str] = []
        for candidate_id in hypothesis.depends_on if hypothesis else ():
            winner = next(
                (
                    item
                    for item in experiments
                    if item.candidate_id == candidate_id
                    and item.status.value == "SUCCEEDED"
                ),
                None,
            )
            if winner is None:
                continue
            for pin in winner.components:
                if pin not in winner.baseline_components:
                    stack[pin.component] = pin
                    merged.append(pin.component)
        if len(set(merged)) < 2:
            return AgentSubagentOutput(
                subagent=_COMBINATION_SUBAGENT.name, error_code="EXECUTION_INVALID"
            )
        return AgentSubagentOutput(
            subagent=_COMBINATION_SUBAGENT.name,
            contribution={"combined_components": sorted(set(merged))},
            verification_status="PASSED",
            safe_metrics={"combined_components": len(set(merged))},
            experiment_candidate_components=tuple(stack[key] for key in sorted(stack)),
        )

    def _select_candidates(
        self,
        session: AgentSession,
        now,
        prior: list[AgentIteration],
        in_flight: list[AgentIteration],
        slots: int,
    ) -> list[AgentHypothesis]:
        """Up to `slots` ready candidates that change distinct components."""
        if self._hypotheses is None:
            return []
        hypotheses = self._hypotheses.list_for_session(session.session_id)
        if not hypotheses and not prior:
            self._create_initial_candidates(session, now)
            hypotheses = self._hypotheses.list_for_session(session.session_id)
        if not in_flight and self._maybe_add_combination(session, now, hypotheses):
            hypotheses = self._hypotheses.list_for_session(session.session_id)
        by_id = {item.hypothesis_id: item for item in hypotheses}
        running = {str(item.decision.get("hypothesis_id")) for item in in_flight}
        busy = {
            _candidate_component(by_id[hypothesis_id])
            for hypothesis_id in running
            if hypothesis_id in by_id
        }
        ready = sorted(
            (
                item
                for item in hypotheses
                if item.status == AgentHypothesisStatus.ACTIVE
                and item.hypothesis_id not in running
                and all(
                    dependency in by_id
                    and by_id[dependency].status != AgentHypothesisStatus.ACTIVE
                    for dependency in item.depends_on
                )
            ),
            key=lambda item: (-item.priority, item.created_at, item.hypothesis_id),
        )
        chosen: list[AgentHypothesis] = []
        for item in ready:
            component = _candidate_component(item)
            exclusive = component == _ALL_COMPONENTS
            if _ALL_COMPONENTS in busy or component in busy or (exclusive and busy):
                continue
            chosen.append(item)
            busy.add(component)
            if exclusive or len(chosen) >= slots:
                break
        return chosen

    def _create_initial_candidates(self, session: AgentSession, now) -> None:
        """One candidate per active insight, else one per area in scope."""
        insights = (
            self._insights.list_for_session(
                session.session_id, status=AgentInsightStatus.ACTIVE
            )
            if self._insights is not None
            else []
        )
        hypotheses = self._hypotheses
        if hypotheses is None:
            return
        if insights:
            for insight in insights:
                hypotheses.create(
                    AgentHypothesis(
                        session_id=session.session_id,
                        hypothesis_id=str(self._ids.new_id()),
                        statement=insight.statement,
                        scope=insight.scope,
                        priority=_insight_priority(insight.kind),
                        status=AgentHypothesisStatus.ACTIVE,
                        created_at=now,
                        updated_at=now,
                        source_insight_id=insight.insight_id,
                        insight_ids=(insight.insight_id,),
                    )
                )
            return
        for area in sorted(session.scope.get("areas", [])) or ["pipeline"]:
            remembered = self._memory.recall(area) if self._memory is not None else []
            statement = (
                f"Evaluar si el área {area} puede mejorar el recall "
                "sin incumplir el piso de precisión."
            )
            scope = {"area": area}
            if remembered:
                statement += f" Respaldado por datos de sesiones previas: {remembered[0].statement}"
                scope["memory"] = ",".join(item.insight_id for item in remembered)
            hypotheses.create(
                AgentHypothesis(
                    session_id=session.session_id,
                    hypothesis_id=str(self._ids.new_id()),
                    statement=statement,
                    scope=scope,
                    priority=0,
                    status=AgentHypothesisStatus.ACTIVE,
                    created_at=now,
                    updated_at=now,
                )
            )
        self._event(
            session.session_id,
            AgentEventKind.HYPOTHESIS,
            AgentEventOutcome.INFO,
            "Candidatos iniciales creados, uno por área del alcance",
            occurred_at=now,
        )

    def _maybe_add_combination(
        self, session: AgentSession, now, hypotheses: list[AgentHypothesis]
    ) -> bool:
        """Winners on distinct components are measured together, once, in series."""
        if self._hypotheses is None or any(
            _is_combination(item) for item in hypotheses
        ):
            return False
        best_by_component: dict[str, RunWinner] = {}
        for winner in self._current_winners(session.session_id):
            if "+" not in winner.component:
                best_by_component.setdefault(winner.component, winner)
        if len(best_by_component) < 2:
            return False
        winners = sorted(best_by_component.values(), key=lambda item: item.component)
        self._hypotheses.create(
            AgentHypothesis(
                session_id=session.session_id,
                hypothesis_id=str(self._ids.new_id()),
                statement=(
                    "Combinar los ganadores ("
                    + ", ".join(item.component for item in winners)
                    + ") y medirlos juntos contra la línea base."
                ),
                scope={"area": COMBINATION_AREA},
                priority=200,
                status=AgentHypothesisStatus.ACTIVE,
                created_at=now,
                updated_at=now,
                depends_on=tuple(item.candidate_id for item in winners),
            )
        )
        self._event(
            session.session_id,
            AgentEventKind.HYPOTHESIS,
            AgentEventOutcome.INFO,
            "Nuevo candidato: combinación de ganadores",
            occurred_at=now,
        )
        return True

    def _current_winners(self, session_id: str) -> tuple[RunWinner, ...]:
        if self._experiments is None:
            return ()
        return rank_winners(
            [
                (item.candidate_id, item)
                for item in self._experiments.list_for_session(session_id, limit=200)
                if item.candidate_id
            ]
        )

    def _set_block(self, session_id: str, code: str, now, number: int) -> None:
        """Parallel candidates may finish together: retry on a stale revision."""
        for _ in range(_ROOT_RETRIES):
            current = self._sessions.get(session_id)
            if current is None or current.status != AgentSessionStatus.ACTIVE:
                return
            try:
                self._sessions.update(
                    replace(
                        current,
                        status=AgentSessionStatus.WAITING_USER,
                        updated_at=now,
                        block={
                            "code": code,
                            "since": now.isoformat(),
                            "iteration": number,
                        },
                    ),
                    expected_rev=current.rev,
                )
                return
            except Exception:  # noqa: BLE001 - revision race with a sibling candidate
                continue

    def _complete(self, leased: AgentSession, now) -> str:
        winners = self._current_winners(leased.session_id)
        self._sessions.update(
            replace(
                leased,
                status=AgentSessionStatus.COMPLETED,
                lease_owner=None,
                lease_expires_at=None,
                updated_at=now,
            ),
            expected_rev=leased.rev,
        )
        self._record_audit(
            leased.session_id, now, "lease", "succeeded", "LEASE_RELEASED"
        )
        self._event(
            leased.session_id,
            AgentEventKind.SESSION,
            AgentEventOutcome.SUCCEEDED,
            f"Corrida terminada con {len(winners)} ganador"
            + ("es" if len(winners) != 1 else ""),
            occurred_at=now,
        )
        self._refresh_run_root(
            leased.session_id, now, status=OptimizationRunStatus.COMPLETED
        )
        return "completed_with_winners"

    def _ensure_run_root(self, session: AgentSession, settings, now) -> None:
        if self._optimization_runs is None or session.mode != "optimization":
            return
        if self._optimization_runs.get(session.session_id) is not None:
            return
        areas = tuple(sorted(session.scope.get("areas", [])))
        insight_ids = (
            tuple(
                item.insight_id
                for item in self._insights.list_for_session(
                    session.session_id, status=AgentInsightStatus.ACTIVE
                )
            )
            if self._insights is not None
            else ()
        )
        memory_ids = (
            tuple(
                item.insight_id for area in areas for item in self._memory.recall(area)
            )
            if self._memory is not None
            else ()
        )
        self._optimization_runs.create_once(
            OptimizationRun(
                run_id=session.session_id,
                status=OptimizationRunStatus.RUNNING,
                created_at=now,
                updated_at=now,
                objective_id=session.objective_id,
                objective_version=session.objective_version,
                baseline_components=session.baseline_components,
                budget_limits=dict(session.budget_limits),
                optimizer_settings={
                    "max_parallel_experiments": settings.optimizer_max_parallel_experiments,
                    "max_concurrent_runs": settings.optimizer_max_concurrent_runs,
                    "max_candidates_per_session": (
                        settings.optimizer_max_candidates_per_session
                    ),
                    "iterations_without_improvement": (
                        settings.optimizer_iterations_without_improvement
                    ),
                    "precision_floor": settings.objective_precision_floor,
                },
                scope_areas=areas,
                insight_ids=insight_ids,
                memory_insight_ids=memory_ids,
                events_stream=session.session_id,
            )
        )

    def _refresh_run_root(
        self, session_id: str, now, status: OptimizationRunStatus | None = None
    ) -> None:
        """Winners, winning stack and strategy, recomputed after each candidate."""
        if self._optimization_runs is None:
            return
        for _ in range(_ROOT_RETRIES):
            root = self._optimization_runs.get(session_id)
            if root is None:
                return
            winners = self._current_winners(session_id)
            experiments = (
                self._experiments.list_for_session(session_id, limit=200)
                if self._experiments is not None
                else []
            )
            best = winners[0] if winners else None
            best_experiment = next(
                (
                    item
                    for item in experiments
                    if best is not None and item.experiment_id == best.experiment_id
                ),
                None,
            )
            hypotheses = (
                self._hypotheses.list_for_session(session_id)
                if self._hypotheses is not None
                else []
            )
            distinct = {item.component for item in winners if "+" not in item.component}
            if best is None:
                strategy = {
                    "action": "explore",
                    "rationale": "Aún no hay un candidato que mejore el objetivo.",
                }
            elif len(distinct) >= 2 and not any(_is_combination(h) for h in hypotheses):
                strategy = {
                    "action": "combine",
                    "rationale": "Hay ganadores en componentes distintos; se medirán juntos.",
                }
            else:
                strategy = {
                    "action": "promote",
                    "rationale": (
                        "El mejor candidato mejora el recall en "
                        f"{best.recall_delta * 100:.1f} pts sobre la línea base."
                    ),
                    "winner": best.candidate_id,
                }
            try:
                self._optimization_runs.update(
                    replace(
                        root,
                        winners=winners,
                        winning_components=(
                            best_experiment.components if best_experiment else ()
                        ),
                        strategy=strategy,
                        status=status or root.status,
                        updated_at=now,
                    ),
                    expected_rev=root.rev,
                )
                return
            except OptimizationRunConflictError:
                continue

    def _experiment_stream_event(self, session_id: str, experiment, refs) -> None:
        """Each experiment keeps its own timeline, referenced from its node."""
        stream = experiment_stream_key(session_id, experiment.experiment_id)
        status = experiment.status.value
        self._event(
            stream,
            AgentEventKind.EXPERIMENT,
            AgentEventOutcome.SUCCEEDED
            if status == "SUCCEEDED"
            else AgentEventOutcome.FAILED,
            {
                "SUCCEEDED": "Experimento cumplió el objetivo global",
                "REJECTED_GLOBAL_CONSTRAINT": "Experimento rechazado por una restricción",
            }.get(status, "Experimento falló"),
            reason_code=experiment.error_code,
            refs=refs,
        )

    def _event(
        self,
        session_id,
        kind,
        outcome,
        summary,
        *,
        reason_code=None,
        refs=None,
        duration_ms=None,
        cost_micros=None,
        occurred_at=None,
    ) -> None:
        if self._timeline is None:
            return
        self._timeline.record(
            session_id,
            kind,
            outcome,
            summary,
            reason_code=reason_code,
            refs=refs,
            duration_ms=duration_ms,
            cost_micros=cost_micros,
            occurred_at=occurred_at,
        )

    def _record_audit(
        self,
        session_id,
        occurred_at,
        category,
        status,
        reason_code=None,
        duration_ms=None,
        cost_micros=None,
        specialist=None,
        tool=None,
    ) -> None:
        if self._audit is None:
            return
        self._audit.append(
            AgentAuditEvent(
                session_id=session_id,
                occurred_at=occurred_at,
                event_id=str(self._ids.new_id()),
                category=category,
                status=status,
                reason_code=reason_code
                if isinstance(reason_code, str) and reason_code in _SAFE_AUDIT_REASONS
                else None,
                duration_ms=duration_ms,
                cost_micros=cost_micros,
                specialist=specialist
                if specialist in {"configuration", "library", "vector_store", "xgboost"}
                else None,
                tool=tool
                if tool in {"configuration", "library", "vector_store", "xgboost"}
                else None,
            )
        )

    def _select_subagent(self, session, hypothesis, prior):
        """Route through graph levers, retaining the legacy route as fallback."""
        if not self._specialists:
            return self._subagent
        area = hypothesis.scope.get("area") if hypothesis is not None else None
        if self._dispatcher is not None and area:
            # Parallel candidates are independent: each one's own area decides.
            specialist = "xgboost" if area == "model" else str(area)
            if specialist in self._specialists:
                return self._specialists[specialist]
        last = prior[-1].decision if prior else {}
        if last.get("experiment_verified") is False:
            return self._specialists.get("library", self._subagent)
        lever = self._graph_optimizer_lever(session, hypothesis)
        if lever:
            specialist = "xgboost" if lever == "model" else lever
            if specialist in self._specialists:
                return self._specialists[specialist]
        area = " ".join(
            str(value).lower()
            for value in ((hypothesis.scope if hypothesis else {}).values())
        )
        if not area:
            area = " ".join(
                str(value).lower() for value in session.scope.get("areas", [])
            )
        if any(term in area for term in ("vector", "retrieval", "embedding")):
            selected = "vector_store"
        elif any(term in area for term in ("model", "xgboost", "classifier")):
            selected = "xgboost"
        elif any(
            term in area for term in ("config", "prompt", "rubric", "threshold", "rule")
        ):
            selected = "configuration"
        else:
            selected = "library"
        return self._specialists.get(selected, self._subagent)

    def _optimizer_project_map(self) -> dict[str, dict[str, str]]:
        if self._project_graph is None:
            return {}
        graph = self._project_graph.load()
        result: dict[str, dict[str, str]] = {}
        for node_id, node in graph.nodes.items():
            prefix = "concept:optimizer-lever-"
            if not node_id.startswith(prefix):
                continue
            lever = node_id.removeprefix(prefix).replace("-", "_")
            specialist = "xgboost" if lever == "model" else lever
            result[specialist] = {
                "name": node.display,
                "description": node.description,
                "keywords": " ".join(node.keywords),
            }
        return result

    def _graph_optimizer_lever(self, session, hypothesis) -> str | None:
        if self._project_graph is None:
            return None
        graph = self._project_graph.load()
        query_parts = [str(value) for value in session.scope.get("areas", [])]
        query_parts.extend(str(value) for value in session.scope.values())
        if hypothesis is not None:
            query_parts.append(hypothesis.statement)
            query_parts.extend(str(value) for value in hypothesis.scope.values())
        weights = {token: 1.0 for token in tokenize(" ".join(query_parts))}
        if not weights:
            return None
        prefix = "concept:optimizer-lever-"
        scores = graph.index.score(weights)
        ranked = sorted(
            (
                (node_id.removeprefix(prefix).replace("-", "_"), score)
                for node_id, score in scores.items()
                if node_id.startswith(prefix)
            ),
            key=lambda item: (-item[1], item[0]),
        )
        return ranked[0][0] if ranked and ranked[0][1] > 0 else None

    def _select_hypothesis(self, session, now, prior):
        if session.mode != "optimization" or self._hypotheses is None:
            return None
        all_hypotheses = self._hypotheses.list_for_session(session.session_id)
        active = [
            item
            for item in all_hypotheses
            if item.status == AgentHypothesisStatus.ACTIVE
        ]
        if not active and not all_hypotheses and not prior:
            insights = (
                self._insights.list_for_session(
                    session.session_id, status=AgentInsightStatus.ACTIVE
                )
                if self._insights is not None
                else []
            )
            if insights:
                for insight in insights:
                    self._hypotheses.create(
                        AgentHypothesis(
                            session_id=session.session_id,
                            hypothesis_id=str(self._ids.new_id()),
                            statement=insight.statement,
                            scope=insight.scope,
                            priority=_insight_priority(insight.kind),
                            status=AgentHypothesisStatus.ACTIVE,
                            created_at=now,
                            updated_at=now,
                            source_insight_id=insight.insight_id,
                        )
                    )
            else:
                areas = sorted(session.scope.get("areas", []))
                area = areas[0] if areas else "pipeline"
                remembered = (
                    self._memory.recall(area) if self._memory is not None else []
                )
                statement = (
                    f"Evaluar si el área {area} puede mejorar el recall "
                    "sin incumplir el piso de precisión."
                )
                scope = {"area": area}
                if remembered:
                    statement += (
                        " Respaldado por datos de sesiones previas: "
                        f"{remembered[0].statement}"
                    )
                    scope["memory"] = ",".join(item.insight_id for item in remembered)
                    self._event(
                        session.session_id,
                        AgentEventKind.HYPOTHESIS,
                        AgentEventOutcome.INFO,
                        f"Memoria cargada: {len(remembered)} aprendizajes respaldados",
                        occurred_at=now,
                    )
                self._hypotheses.create(
                    AgentHypothesis(
                        session_id=session.session_id,
                        hypothesis_id=str(self._ids.new_id()),
                        statement=statement,
                        scope=scope,
                        priority=0,
                        status=AgentHypothesisStatus.ACTIVE,
                        created_at=now,
                        updated_at=now,
                    )
                )
            active = [
                item
                for item in self._hypotheses.list_for_session(session.session_id)
                if item.status == AgentHypothesisStatus.ACTIVE
            ]
        if not active:
            return None
        return min(
            active,
            key=lambda item: (-item.priority, item.created_at, item.hypothesis_id),
        )

    def _save_session_memory(self, session_id, session, now, optimizer_state) -> None:
        if self._summaries is None:
            return
        previous = self._summaries.get_latest(session_id)
        content = dict(previous.content) if previous else {}
        content["optimizer"] = optimizer_state
        self._summaries.create(
            AgentSessionSummary(
                session_id=session_id,
                version=(previous.version + 1) if previous else 1,
                content=content,
                covers_seq_from=previous.covers_seq_from if previous else 0,
                covers_seq_to=(
                    previous.covers_seq_to if previous else session.message_seq
                ),
                created_at=now,
            )
        )


def _iteration_decision(
    *,
    mode: str,
    prior: list[AgentIteration],
    metrics: dict[str, object],
    verification_id: str,
    error_code: str | None,
    settings,
) -> dict[str, object]:
    decision: dict[str, object] = {
        "action": "continue" if mode == "optimization" else "stub_completed",
        "verification_id": verification_id,
    }
    if mode != "optimization":
        return decision
    if error_code and settings.optimizer_stop_on_critical_failure:
        return {**decision, "action": "stop", "reason": "critical_failure"}
    recall = metrics.get("recall")
    precision = metrics.get("precision")
    if not isinstance(recall, (int, float)) or not isinstance(precision, (int, float)):
        return decision
    if precision < settings.objective_precision_floor:
        stale = _stale_iteration_count(prior) + 1
        decision.update(
            {
                "improved": False,
                "stale_iterations": stale,
                "reason": "precision_floor_not_met",
            }
        )
        if stale >= settings.optimizer_iterations_without_improvement:
            decision.update({"action": "stop", "reason": "stagnation"})
        return decision
    prior_scores = [
        float(item.decision["score"])
        for item in prior
        if isinstance(item.decision.get("score"), (int, float))
    ]
    best = max(prior_scores, default=float("-inf"))
    stale = _stale_iteration_count(prior)
    improved = float(recall) > best
    stale = 0 if improved else stale + 1
    decision.update(
        {"score": float(recall), "improved": improved, "stale_iterations": stale}
    )
    if stale >= settings.optimizer_iterations_without_improvement:
        decision.update({"action": "stop", "reason": "stagnation"})
    return decision


_ROOT_RETRIES = 5
_ALL_COMPONENTS = "*"


class _CombinationSubagent:
    """Placeholder: combinations are built deterministically, without an LLM."""

    name = COMBINATION_AREA


_COMBINATION_SUBAGENT = _CombinationSubagent()


def _is_combination(hypothesis) -> bool:
    return bool(hypothesis) and hypothesis.scope.get("area") == COMBINATION_AREA


def _candidate_component(hypothesis) -> str:
    area = hypothesis.scope.get("area")
    if area == COMBINATION_AREA:
        return _ALL_COMPONENTS
    return component_for_area(area) or str(area or "pipeline")


def _conclusion_summary(outcome, recall_delta: float | None) -> str:
    if outcome == AgentHypothesisStatus.VALIDATED:
        if recall_delta is not None:
            return f"Mejora el recall en {recall_delta * 100:.1f} pts sin bajar del piso de precisión."
        return "Cumple el piso de precisión con la evidencia disponible."
    if outcome == AgentHypothesisStatus.REFUTED:
        return "No cumple el objetivo: se descarta."
    return "La evidencia no alcanza para concluir."


_COST_ANOMALY_FACTOR = 3
_COST_ANOMALY_MIN_HISTORY = 3


def _is_cost_anomaly(prior: list[AgentIteration], cost_micros: int) -> bool:
    """An iteration costing more than 3x the median of earlier ones is unusual."""
    history = sorted(
        float(item.decision["cost_micros"])
        for item in prior
        if isinstance(item.decision.get("cost_micros"), (int, float))
        and item.decision["cost_micros"] > 0
    )
    if len(history) < _COST_ANOMALY_MIN_HISTORY or cost_micros <= 0:
        return False
    median = history[len(history) // 2]
    return cost_micros > _COST_ANOMALY_FACTOR * median


def _safe_specialist_error_code(error_code: str | None) -> str | None:
    """Expose only bounded, known codes; never persist exception text in decisions."""
    if error_code is None:
        return None
    if error_code in _SAFE_AUDIT_REASONS:
        return error_code
    return "SPECIALIST_FAILED"


def _stale_iteration_count(prior: list[AgentIteration]) -> int:
    stale = 0
    for item in reversed(prior):
        if item.decision.get("improved") is True:
            break
        if item.decision.get("action") in {"continue", "stop"}:
            stale += 1
    return stale


def _insight_priority(kind: AgentInsightKind) -> int:
    return {
        AgentInsightKind.DIRECTIVE: 100,
        AgentInsightKind.HYPOTHESIS: 90,
        AgentInsightKind.CONSTRAINT: 80,
        AgentInsightKind.PREFERENCE: 70,
        AgentInsightKind.OBSERVATION: 60,
        AgentInsightKind.DECISION: 50,
        AgentInsightKind.QUESTION: 40,
    }[kind]
