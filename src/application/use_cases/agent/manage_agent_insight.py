from __future__ import annotations

from dataclasses import replace

from src.application.ports.agent_insight_port import (
    AgentInsight,
    AgentInsightRepository,
    AgentInsightStatus,
)
from src.application.ports.agent_session_port import AgentSessionRepository
from src.application.ports.clock_port import Clock


class AgentInsightNotFoundError(Exception):
    pass


class AgentInsightStateError(Exception):
    pass


class ManageAgentInsightUseCase:
    def __init__(
        self,
        *,
        sessions: AgentSessionRepository,
        insights: AgentInsightRepository,
        clock: Clock,
    ) -> None:
        self._sessions = sessions
        self._insights = insights
        self._clock = clock

    def list_for_owner(
        self,
        session_id: str,
        owner_id: str,
        status: AgentInsightStatus | None = None,
    ) -> list[AgentInsight]:
        self._owned_session(session_id, owner_id)
        insights = self._insights.list_for_session(session_id, limit=100)
        now = self._clock.now()
        for insight in insights:
            if (
                insight.status
                in {AgentInsightStatus.PROPOSED, AgentInsightStatus.CONFIRMED, AgentInsightStatus.ACTIVE}
                and insight.expires_at is not None
                and insight.expires_at <= now
            ):
                self._save(insight, AgentInsightStatus.EXPIRED, owner_id)
        current = self._insights.list_for_session(session_id, status=status)
        return current

    def confirm(self, session_id: str, insight_id: str, owner_id: str) -> AgentInsight:
        insight = self._owned_insight(session_id, insight_id, owner_id)
        if insight.status == AgentInsightStatus.PROPOSED:
            insight = self._save(insight, AgentInsightStatus.CONFIRMED, owner_id)
        if insight.status != AgentInsightStatus.CONFIRMED:
            if insight.status == AgentInsightStatus.ACTIVE:
                return insight
            raise AgentInsightStateError("only a proposed insight can be confirmed")
        return self._save(insight, AgentInsightStatus.ACTIVE, owner_id)

    def reject(self, session_id: str, insight_id: str, owner_id: str) -> AgentInsight:
        insight = self._owned_insight(session_id, insight_id, owner_id)
        if insight.status == AgentInsightStatus.REJECTED:
            return insight
        if insight.status != AgentInsightStatus.PROPOSED:
            raise AgentInsightStateError("only a proposed insight can be rejected")
        return self._save(insight, AgentInsightStatus.REJECTED, owner_id)

    def record_evidence_result(
        self,
        session_id: str,
        insight_id: str,
        owner_id: str,
        target: AgentInsightStatus,
    ) -> AgentInsight:
        if target not in {
            AgentInsightStatus.APPLIED,
            AgentInsightStatus.REFUTED,
            AgentInsightStatus.SUPERSEDED,
            AgentInsightStatus.EXPIRED,
        }:
            raise AgentInsightStateError("invalid evidence result")
        insight = self._owned_insight(session_id, insight_id, owner_id)
        if insight.status != AgentInsightStatus.ACTIVE:
            raise AgentInsightStateError("only active insights can receive a result")
        return self._save(insight, target, owner_id)

    def _owned_insight(
        self, session_id: str, insight_id: str, owner_id: str
    ) -> AgentInsight:
        self._owned_session(session_id, owner_id)
        insight = self._insights.get(session_id, insight_id)
        if insight is None:
            raise AgentInsightNotFoundError("insight not found")
        return insight

    def _owned_session(self, session_id: str, owner_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is None or session.owner_id != owner_id:
            raise AgentInsightNotFoundError("session not found")

    def _save(
        self,
        insight: AgentInsight,
        status: AgentInsightStatus,
        actor_id: str,
    ) -> AgentInsight:
        now = self._clock.now()
        confirmed = status in {
            AgentInsightStatus.CONFIRMED,
            AgentInsightStatus.ACTIVE,
        }
        updated = replace(
            insight,
            status=status,
            updated_at=now,
            confirmed_by=actor_id if confirmed else insight.confirmed_by,
            confirmed_at=now if confirmed else insight.confirmed_at,
        )
        return self._insights.update(updated, expected_rev=insight.rev)
