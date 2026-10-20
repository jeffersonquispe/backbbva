from __future__ import annotations

from datetime import timedelta

from src.application.ports.agent_entity_claim_port import (
    AgentEntityClaim,
    AgentEntityClaimRepository,
)
from src.application.ports.agent_session_port import (
    AgentSessionRepository,
    AgentSessionStatus,
)
from src.application.ports.clock_port import Clock


class AgentEntityClaimUseCase:
    def __init__(
        self,
        *,
        sessions: AgentSessionRepository,
        claims: AgentEntityClaimRepository,
        clock: Clock,
    ) -> None:
        self._sessions = sessions
        self._claims = claims
        self._clock = clock

    def heartbeat(self, session_id: str, lease_seconds: int = 120) -> list[AgentEntityClaim]:
        session = self._sessions.get(session_id)
        if session is None or session.mode != "optimization":
            return []
        now = self._clock.now()
        expires = now + timedelta(seconds=lease_seconds)
        claims = []
        for area in sorted(set(session.scope.get("areas", []))):
            key = f"scope#{area}"
            existing = next(
                (item for item in self._claims.list_by_session(session_id) if item.entity_key == key),
                None,
            )
            claims.append(
                self._claims.claim(
                    AgentEntityClaim(
                        entity_key=key,
                        session_id=session_id,
                        claimed_at=existing.claimed_at if existing else now,
                        heartbeat_at=now,
                        expires_at=expires,
                        reason="session_scope",
                    )
                )
            )
        return claims

    def list_active(self, entity_key: str) -> list[AgentEntityClaim]:
        now = self._clock.now()
        return [
            claim
            for claim in self._claims.list_by_entity(entity_key)
            if claim.expires_at > now
            and (session := self._sessions.get(claim.session_id)) is not None
            and session.status == AgentSessionStatus.ACTIVE
        ]
