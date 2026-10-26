"""The Channel Manager grants what a blocked optimizer session is waiting for."""

from __future__ import annotations

from dataclasses import dataclass, replace

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
    AgentInsight,
    AgentInsightKind,
    AgentInsightRepository,
    AgentInsightStatus,
)
from src.application.ports.agent_iteration_port import AgentIterationRepository
from src.application.ports.agent_link_port import AgentLink, AgentLinkRepository
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
from src.application.ports.personal_data_masker_port import PersonalDataMasker
from src.application.use_cases.agent.agent_timeline import AgentTimeline
from src.domain.agents.event import AgentEventKind, AgentEventOutcome
from src.domain.agents.failure_catalog import describe_failure

MAX_ALLOWANCE = 20
MAX_NOTE_CHARS = 1_000
_BUDGET_RESOURCES = {"tokens", "usd_micros", "seconds"}


class AgentBlockNotFoundError(Exception):
    pass


class AgentBlockPolicyError(Exception):
    """The grant is invalid for the block; `code` is safe to expose."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ResolveAgentBlockInput:
    session_id: str
    actor_id: str
    kind: str  # "budget" | "candidates" | "context"
    additions: dict[str, int] | None = None
    allowance: int | None = None
    note: str | None = None


class ResolveAgentBlockUseCase:
    def __init__(
        self,
        *,
        sessions: AgentSessionRepository,
        iterations: AgentIterationRepository,
        ledger: AgentBudgetLedgerRepository,
        settings: AssistantOptimizerSettingsPort,
        hypotheses: AgentHypothesisRepository,
        insights: AgentInsightRepository,
        links: AgentLinkRepository,
        masker: PersonalDataMasker,
        timeline: AgentTimeline,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._sessions = sessions
        self._iterations = iterations
        self._ledger = ledger
        self._settings = settings
        self._hypotheses = hypotheses
        self._insights = insights
        self._links = links
        self._masker = masker
        self._timeline = timeline
        self._clock = clock
        self._ids = ids

    def execute(self, request: ResolveAgentBlockInput) -> AgentSession:
        session = self._sessions.get(request.session_id)
        if (
            session is None
            or session.owner_id != request.actor_id
            or session.mode != "optimization"
        ):
            raise AgentBlockNotFoundError("session not found")
        code = session.block.get("code")
        if session.status != AgentSessionStatus.WAITING_USER or not code:
            raise AgentBlockPolicyError("SESSION_NOT_BLOCKED")
        accepted = {describe_failure(str(code)).approval, "context"}
        if request.kind not in accepted:
            raise AgentBlockPolicyError("GRANT_NOT_APPLICABLE")
        now = self._clock.now()
        if request.kind == "budget":
            granted, summary = self._grant_budget(session, request, now)
        elif request.kind == "candidates":
            granted, summary = self._grant_candidates(session, request)
        else:
            granted, summary = self._grant_context(session, request, now)
        updated = self._sessions.update(
            replace(
                granted,
                status=AgentSessionStatus.ACTIVE,
                block={},
                updated_at=now,
            ),
            expected_rev=session.rev,
        )
        self._timeline.record(
            session.session_id,
            AgentEventKind.USER_ACTION,
            AgentEventOutcome.SUCCEEDED,
            summary,
            reason_code=str(code),
            actor_id=request.actor_id,
            occurred_at=now,
        )
        return updated

    def _grant_budget(self, session, request, now):
        additions = request.additions or {}
        if (
            not additions
            or set(additions) - _BUDGET_RESOURCES
            or any(
                not isinstance(value, int) or value <= 0 for value in additions.values()
            )
        ):
            raise AgentBlockPolicyError("INVALID_BUDGET_GRANT")
        ceilings = self._settings.get()
        ceiling = {
            "tokens": ceilings.optimizer_session_budget_ceiling_tokens,
            "usd_micros": int(
                ceilings.optimizer_session_budget_ceiling_usd * 1_000_000
            ),
            "seconds": ceilings.optimizer_session_budget_ceiling_seconds,
        }
        limits = dict(session.budget_limits)
        for resource, amount in additions.items():
            limits[resource] = limits.get(resource, 0) + amount
            if limits[resource] > ceiling[resource]:
                raise AgentBlockPolicyError("BUDGET_CEILING_EXCEEDED")
        for resource, amount in sorted(additions.items()):
            self._ledger.append(
                AgentBudgetEntry(
                    session_id=session.session_id,
                    entry_id=str(self._ids.new_id()),
                    entry_type="RENEW",
                    resource=resource,
                    amount=amount,
                    actor=request.actor_id,
                    reason="channel_manager_authorized",
                    created_at=now,
                )
            )
        return (
            replace(
                session,
                budget_limits=limits,
                budget_renewals=session.budget_renewals + 1,
            ),
            "Aprobaste más presupuesto",
        )

    def _grant_candidates(self, session, request):
        allowance = request.allowance
        if not isinstance(allowance, int) or not 1 <= allowance <= MAX_ALLOWANCE:
            raise AgentBlockPolicyError("INVALID_ALLOWANCE")
        return (
            replace(
                session,
                candidate_allowance=session.candidate_allowance + allowance,
                stagnation_reset_after=self._last_iteration(session.session_id),
            ),
            f"Aprobaste {allowance} iteraciones más",
        )

    def _grant_context(self, session, request, now):
        note = (request.note or "").strip()
        if not note or len(note) > MAX_NOTE_CHARS:
            raise AgentBlockPolicyError("INVALID_CONTEXT")
        masked = self._masker.mask(note)
        if any(masked.counts.values()):
            raise AgentBlockPolicyError("PERSONAL_DATA_BLOCKED")
        insight_id = str(self._ids.new_id())
        self._insights.create(
            AgentInsight(
                session_id=session.session_id,
                insight_id=insight_id,
                kind=AgentInsightKind.DIRECTIVE,
                statement=masked.text,
                scope={},
                status=AgentInsightStatus.ACTIVE,
                proposed_by="user",
                author_id=request.actor_id,
                source_message_id=None,
                created_at=now,
                updated_at=now,
                confirmed_by=request.actor_id,
                confirmed_at=now,
            )
        )
        hypothesis_id = str(self._ids.new_id())
        self._hypotheses.create(
            AgentHypothesis(
                session_id=session.session_id,
                hypothesis_id=hypothesis_id,
                statement=masked.text,
                scope={},
                priority=100,
                status=AgentHypothesisStatus.ACTIVE,
                created_at=now,
                updated_at=now,
                source_insight_id=insight_id,
            )
        )
        self._links.create_once(
            AgentLink(
                session_id=session.session_id,
                source_type="insight",
                source_id=insight_id,
                relation="generates",
                target_type="hypothesis",
                target_id=hypothesis_id,
                created_at=now,
            )
        )
        return (
            replace(
                session,
                stagnation_reset_after=self._last_iteration(session.session_id),
            ),
            "Entregaste contexto nuevo",
        )

    def _last_iteration(self, session_id: str) -> int:
        return max(
            (
                item.number
                for item in self._iterations.list_for_session(session_id, 100)
            ),
            default=0,
        )
