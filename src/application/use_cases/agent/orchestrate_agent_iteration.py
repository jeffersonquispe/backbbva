from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta

from src.application.ports.agent_budget_ledger_port import (
    AgentBudgetEntry,
    AgentBudgetLedgerRepository,
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

LEASE_SECONDS = 90


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

    def execute(self, session_id: str) -> str:
        # Settings are deliberately read on each invocation, never captured in
        # the factory or session snapshot, so kill switches take immediate effect.
        current_settings = self._settings.get()
        session = self._sessions.get(session_id)
        if session is None or session.status != AgentSessionStatus.ACTIVE:
            return "not_active"

        enabled = (
            current_settings.assistant_enabled
            if session.mode == "assistant"
            else current_settings.optimizer_enabled
        )
        if not enabled:
            self._sessions.update(
                replace(session, status=AgentSessionStatus.PAUSED, updated_at=self._clock.now()),
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
            if len(active_optimizers) > current_settings.optimizer_max_concurrent_sessions:
                return "deferred_by_session_limit"
            active_runs = self._runs.list_active(now, limit=100)
            if len(active_runs) >= current_settings.optimizer_max_concurrent_runs:
                return "deferred_by_run_limit"

        lease_expires = now + timedelta(seconds=LEASE_SECONDS)
        leased = self._sessions.acquire_lease(
            session_id, str(self._ids.new_id()), now, lease_expires
        )
        if leased is None:
            return "lease_unavailable"

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

        for resource in ("tokens", "usd_micros", "seconds"):
            if not self._budget.reserve(session_id, resource, 1, effective_budget[resource]):
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
        prompt_ref = leased.prompt_versions.get(self._subagent.name, {})
        if not prompt_ref:
            prompt_ref = {
                "name": f"subagent.{self._subagent.name}",
                "version": "0",
                "hash": "stub",
            }
        run = AgentRun(
            run_id=run_id,
            session_id=session_id,
            iteration_number=number,
            subagent=self._subagent.name,
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

        output = self._subagent.execute(
            AgentSubagentInput(
                session_id=session_id,
                iteration_number=number,
                scope=leased.scope,
                hypothesis=(
                    hypothesis.statement
                    if hypothesis is not None
                    else "Exercise the configured specialist."
                ),
                budget=effective_budget,
            )
        )
        finished = self._clock.now()
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
        if leased.mode == "assistant":
            package_id = str(self._ids.new_id())
            content = {
                "subagent": output.subagent,
                "contribution": output.contribution,
                "verification_status": output.verification_status,
            }
            content_hash = hashlib.sha256(
                json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            self._packages.create(
                AgentPackage(
                    package_id=package_id,
                    session_id=session_id,
                    iteration_number=number,
                    status="SEALED",
                    content=content,
                    content_hash=content_hash,
                    created_at=finished,
                    sealed_at=finished,
                )
            )
        verification_id = str(self._ids.new_id())
        self._verifications.create(
            AgentVerification(
                verification_id=verification_id,
                subject_id=package_id or run_id,
                verifier="stub_contract",
                status=output.verification_status,
                safe_metrics=output.safe_metrics,
                error_code=output.error_code,
                created_at=finished,
            )
        )
        if hypothesis is not None and self._hypotheses is not None:
            precision = output.safe_metrics.get("precision")
            recall = output.safe_metrics.get("recall")
            if isinstance(precision, (int, float)) and isinstance(recall, (int, float)):
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
            metrics=output.safe_metrics,
            verification_id=verification_id,
            error_code=output.error_code,
            settings=current_settings,
        )
        if hypothesis is not None:
            decision["hypothesis"] = hypothesis.statement
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
        return "stopped_by_critical_failure" if decision.get("reason") == "critical_failure" else (
            "stopped_by_stagnation" if decision.get("reason") == "stagnation" else "iteration_completed"
        )

    def _select_hypothesis(self, session, now, prior):
        if session.mode != "optimization" or self._hypotheses is None:
            return None
        all_hypotheses = self._hypotheses.list_for_session(session.session_id)
        active = [item for item in all_hypotheses if item.status == AgentHypothesisStatus.ACTIVE]
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
    decision.update({"score": float(recall), "improved": improved, "stale_iterations": stale})
    if stale >= settings.optimizer_iterations_without_improvement:
        decision.update({"action": "stop", "reason": "stagnation"})
    return decision


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
