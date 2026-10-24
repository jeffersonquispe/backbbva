from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta

from src.application.ports.agent_audit_port import AgentAuditEvent, AgentAuditRepository
from src.application.ports.agent_budget_ledger_port import (
    AgentBudgetEntry,
    AgentBudgetLedgerRepository,
)
from src.application.ports.agent_experiment_component_port import (
    AgentExperimentComponentResolver,
)
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
from src.application.use_cases.agent.evaluate_agent_experiment import (
    EvaluateAgentExperiment,
)
from src.domain.agents.experiment import AgentExperimentKind

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

    def execute(self, session_id: str) -> str:
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
            active_runs = self._runs.list_active(now, limit=100)
            if len(active_runs) >= current_settings.optimizer_max_concurrent_runs:
                return "deferred_by_run_limit"

        lease_expires = now + timedelta(seconds=LEASE_SECONDS)
        if session.lease_expires_at is not None and session.lease_expires_at <= now:
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
        ):
            self._sessions.update(
                replace(
                    leased,
                    status=AgentSessionStatus.PAUSED,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=now,
                ),
                expected_rev=leased.rev,
            )
            self._record_audit(session_id, now, "lease", "succeeded", "LEASE_RELEASED")
            return "paused_by_candidate_limit"

        prior = self._iterations.list_for_session(session_id, limit=100)
        hypothesis = self._select_hypothesis(leased, now, prior)
        if leased.mode == "optimization" and self._hypotheses and hypothesis is None:
            self._sessions.update(
                replace(
                    leased,
                    status=AgentSessionStatus.STOPPED,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=now,
                ),
                expected_rev=leased.rev,
            )
            self._record_audit(session_id, now, "lease", "succeeded", "LEASE_RELEASED")
            self._save_session_memory(
                session_id,
                leased,
                now,
                {
                    "action": "stop",
                    "reason": "no_signal",
                    "completed_iterations": len(prior),
                },
            )
            return "stopped_no_signal"

        cost_before = sum(
            entry.amount
            for entry in self._budget.list_for_session(session_id)
            if entry.entry_type == "SPEND" and entry.resource == "usd_micros"
        )
        for resource in ("tokens", "usd_micros", "seconds"):
            if not self._budget.reserve(
                session_id, resource, 1, effective_budget[resource]
            ):
                self._sessions.update(
                    replace(
                        leased,
                        status=AgentSessionStatus.PAUSED,
                        lease_owner=None,
                        lease_expires_at=None,
                        updated_at=now,
                    ),
                    expected_rev=leased.rev,
                )
                self._record_audit(
                    session_id, now, "lease", "succeeded", "LEASE_RELEASED"
                )
                return "paused_by_budget"
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

        number = max((item.number for item in prior), default=0) + 1
        run_id = str(self._ids.new_id())
        selected_subagent = self._select_subagent(leased, hypothesis, prior)
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

        subagent_input = AgentSubagentInput(
            session_id=session_id,
            iteration_number=number,
            scope=leased.scope,
            hypothesis=(
                hypothesis.statement
                if hypothesis is not None
                else "Exercise the configured specialist."
            ),
            budget=effective_budget,
            prompt_versions=leased.prompt_versions,
            objective_id=leased.objective_id,
            objective_version=leased.objective_version,
            objective=objective,
            baseline_components=leased.baseline_components,
        )
        if self._monitoring is None:
            output = selected_subagent.execute(subagent_input)
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
                            output = selected_subagent.execute(subagent_input)
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
                            - cost_before
                        )
                    if isinstance(cost, (int, float)) and cost >= 0:
                        audit_result["agent.cost_usd_micros"] = int(cost)
                    iteration_span.write_operation_metas(audit_result)
                    session_span.write_operation_metas(audit_result)
                    specialist_span.write_operation_metas(audit_result)
                    tool_span.write_operation_metas(audit_result)
        finished = self._clock.now()
        elapsed_ms = max(0, int((finished - now).total_seconds() * 1000))
        result_status = "failed" if output.error_code else "succeeded"
        cost_value = output.safe_metrics.get("cost_usd_micros")
        cost_micros = (
            int(cost_value)
            if isinstance(cost_value, (int, float)) and cost_value >= 0
            else None
        )
        self._record_audit(
            session_id,
            finished,
            "tool",
            result_status,
            output.error_code,
            elapsed_ms,
            cost_micros,
            tool=selected_subagent.name,
        )
        self._record_audit(
            session_id,
            finished,
            "specialist",
            result_status,
            output.error_code,
            elapsed_ms,
            cost_micros,
            specialist=selected_subagent.name,
        )
        self._record_audit(
            session_id,
            finished,
            "iteration",
            result_status,
            output.error_code,
            elapsed_ms,
            cost_micros,
        )
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
        package_id = None
        has_optimization_proposal = (
            leased.mode == "optimization"
            and bool(output.contribution)
            and output.error_code is None
        )
        if leased.mode == "assistant" or has_optimization_proposal:
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
                    session_id=session_id,
                    iteration_number=number,
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
        experiment = None
        if (
            leased.mode == "optimization"
            and verified
            and output.experiment_candidate_components
            and self._experiment_evaluator is not None
        ):
            baseline_by_type = {
                item.component: item for item in leased.baseline_components
            }
            candidate_by_type = {
                item.component: item for item in output.experiment_candidate_components
            }
            required_types = {"model", "configuration", "library", "vector_store"}
            if (
                set(candidate_by_type) == required_types
                and set(baseline_by_type) == required_types
            ):
                changed = sum(
                    candidate_by_type[name] != baseline_by_type[name]
                    for name in required_types
                )
                if changed:
                    self._record_audit(session_id, finished, "experiment", "started")
                    experiment = self._experiment_evaluator.execute(
                        experiment_id=str(self._ids.new_id()),
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
                    )
                    experiment_status = (
                        "succeeded"
                        if experiment.status.value == "SUCCEEDED"
                        else "failed"
                    )
                    self._record_audit(
                        session_id,
                        self._clock.now(),
                        "experiment",
                        experiment_status,
                        (
                            "GLOBAL_CONSTRAINT_REJECTED"
                            if experiment.status.value == "REJECTED_GLOBAL_CONSTRAINT"
                            else experiment.error_code
                        ),
                    )
        if hypothesis is not None and self._hypotheses is not None:
            precision = output.safe_metrics.get("precision")
            recall = output.safe_metrics.get("recall")
            if (
                verified
                and isinstance(precision, (int, float))
                and isinstance(recall, (int, float))
            ):
                outcome = (
                    AgentHypothesisStatus.VALIDATED
                    if precision >= current_settings.objective_precision_floor
                    else AgentHypothesisStatus.REFUTED
                )
            else:
                outcome = AgentHypothesisStatus.NONCONCLUSIVE
            self._hypotheses.update(
                replace(
                    hypothesis,
                    status=outcome,
                    evidence_id=verification_id,
                    evidence_outcome=outcome.value,
                    updated_at=finished,
                ),
                expected_rev=hypothesis.rev,
            )
            if hypothesis.source_insight_id and self._insights is not None:
                source_insight = self._insights.get(
                    session_id, hypothesis.source_insight_id
                )
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
        decision = _iteration_decision(
            mode=leased.mode,
            prior=prior,
            metrics=output.safe_metrics if verified else {},
            verification_id=verification_id,
            error_code=output.error_code,
            settings=current_settings,
        )
        if hypothesis is not None:
            decision["hypothesis"] = hypothesis.statement
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
        terminal_status = (
            AgentSessionStatus.PAUSED
            if current_session.mode == "assistant"
            else AgentSessionStatus.STOPPED
            if decision.get("action") == "stop"
            else current_session.status
        )
        self._sessions.update(
            replace(
                current_session,
                status=terminal_status,
                lease_owner=None,
                lease_expires_at=None,
                updated_at=finished,
            ),
            expected_rev=current_session.rev,
        )
        self._record_audit(session_id, finished, "lease", "succeeded", "LEASE_RELEASED")
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
        return (
            "stopped_by_critical_failure"
            if decision.get("reason") == "critical_failure"
            else (
                "stopped_by_stagnation"
                if decision.get("reason") == "stagnation"
                else "iteration_completed"
            )
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
        """Route each tick from the active hypothesis and latest experiment result."""
        if not self._specialists:
            return self._subagent
        area = " ".join(
            str(value).lower()
            for value in ((hypothesis.scope if hypothesis else {}).values())
        )
        if not area:
            area = " ".join(
                str(value).lower() for value in session.scope.get("areas", [])
            )
        last = prior[-1].decision if prior else {}
        if last.get("experiment_verified") is False:
            selected = "library"
        elif any(term in area for term in ("vector", "retrieval", "embedding")):
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
                self._hypotheses.create(
                    AgentHypothesis(
                        session_id=session.session_id,
                        hypothesis_id=str(self._ids.new_id()),
                        statement=(
                            f"Evaluar si el área {area} puede mejorar el recall "
                            "sin incumplir el piso de precisión."
                        ),
                        scope={"area": area},
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
