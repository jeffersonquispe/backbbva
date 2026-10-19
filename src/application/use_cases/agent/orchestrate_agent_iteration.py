from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta

from src.application.ports.agent_budget_ledger_port import (
    AgentBudgetEntry,
    AgentBudgetLedgerRepository,
)
from src.application.ports.agent_iteration_port import (
    AgentIteration,
    AgentIterationRepository,
    AgentIterationStatus,
)
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

        prior = self._iterations.list_for_session(session_id, limit=100)
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
                hypothesis="Exercise the configured specialist.",
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
                    else AgentRunStatus.CANCELLED
                ),
                prompt_ref=run.prompt_ref,
                created_at=run.created_at,
                lease_expires_at=None,
                error_code=output.error_code,
            )
        )
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
                subject_id=package_id,
                verifier="stub_contract",
                status=output.verification_status,
                safe_metrics=output.safe_metrics,
                error_code=output.error_code,
                created_at=finished,
            )
        )
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
                decision={"action": "stub_completed", "verification_id": verification_id},
            )
        )
        self._sessions.update(
            replace(
                current_session,
                status=(
                    AgentSessionStatus.PAUSED
                    if current_session.mode == "assistant"
                    else current_session.status
                ),
                lease_owner=None,
                lease_expires_at=None,
                updated_at=finished,
            ),
            expected_rev=current_session.rev,
        )
        return "iteration_completed"
