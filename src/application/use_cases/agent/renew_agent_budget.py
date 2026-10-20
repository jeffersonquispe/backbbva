from __future__ import annotations

from dataclasses import replace

from src.application.ports.agent_budget_ledger_port import (
    AgentBudgetEntry,
    AgentBudgetLedgerRepository,
)
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


class AgentBudgetRenewalError(Exception):
    pass


class RenewAgentBudgetUseCase:
    def __init__(
        self,
        *,
        sessions: AgentSessionRepository,
        ledger: AgentBudgetLedgerRepository,
        settings: AssistantOptimizerSettingsPort,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._sessions = sessions
        self._ledger = ledger
        self._settings = settings
        self._clock = clock
        self._ids = ids

    def execute(
        self, session_id: str, actor_id: str, additions: dict[str, int]
    ) -> AgentSession:
        session = self._sessions.get(session_id)
        if session is None or session.mode != "optimization":
            raise AgentBudgetRenewalError("optimization session not found")
        if session.status != AgentSessionStatus.PAUSED:
            raise AgentBudgetRenewalError("session must be paused to renew budget")
        settings = self._settings.get()
        if session.budget_renewals >= settings.optimizer_max_budget_renewals:
            raise AgentBudgetRenewalError("budget renewal limit reached")
        valid = {"tokens", "usd_micros", "seconds"}
        if not additions or set(additions) - valid or any(value <= 0 for value in additions.values()):
            raise AgentBudgetRenewalError("invalid budget renewal")
        now = self._clock.now()
        limits = dict(session.budget_limits)
        for resource, amount in additions.items():
            limits[resource] = limits.get(resource, 0) + amount
        updated = self._sessions.update(
            replace(
                session,
                budget_limits=limits,
                budget_renewals=session.budget_renewals + 1,
                updated_at=now,
            ),
            expected_rev=session.rev,
        )
        for resource, amount in sorted(additions.items()):
            self._ledger.append(
                AgentBudgetEntry(
                    session_id=session_id,
                    entry_id=str(self._ids.new_id()),
                    entry_type="RENEW",
                    resource=resource,
                    amount=amount,
                    actor=actor_id,
                    reason="channel_manager_authorized",
                    created_at=now,
                )
            )
        return updated
