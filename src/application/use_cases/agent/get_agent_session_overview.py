"""One honest answer to "what is this session doing, and did it fail?"."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.application.ports.agent_event_port import AgentEventRepository
from src.application.ports.agent_experiment_port import AgentExperimentRepository
from src.application.ports.agent_hypothesis_port import (
    AgentHypothesisRepository,
    AgentHypothesisStatus,
)
from src.application.ports.agent_iteration_port import (
    AgentIterationRepository,
    AgentIterationStatus,
)
from src.application.ports.agent_session_port import (
    AgentSession,
    AgentSessionRepository,
    AgentSessionStatus,
)
from src.application.ports.clock_port import Clock
from src.domain.agents.failure_catalog import describe_failure

# An ACTIVE session whose lease expired this long ago is reported as stalled.
STALL_GRACE_SECONDS = 30


class AgentOverviewNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class AgentVerdict:
    state: str  # draft | running | stalled | failing | blocked | paused | completed | inconclusive | stopped | failed | cancelled
    title: str
    detail: str
    action: str | None = None
    code: str | None = None
    approval: str | None = None
    retryable: bool = False


@dataclass(frozen=True)
class AgentHealth:
    lease: str  # NONE | ACTIVE | EXPIRED
    stalled: bool
    last_event_at: datetime | None = None
    seconds_since_last_event: int | None = None


@dataclass(frozen=True)
class AgentSessionOverview:
    session_id: str
    status: str
    verdict: AgentVerdict
    health: AgentHealth
    iterations: dict[str, int] = field(default_factory=dict)
    hypotheses: dict[str, int] = field(default_factory=dict)
    experiments: dict[str, int] = field(default_factory=dict)
    events_total: int = 0
    block: dict[str, Any] = field(default_factory=dict)


class GetAgentSessionOverviewUseCase:
    def __init__(
        self,
        *,
        sessions: AgentSessionRepository,
        iterations: AgentIterationRepository,
        hypotheses: AgentHypothesisRepository,
        experiments: AgentExperimentRepository,
        events: AgentEventRepository,
        clock: Clock,
    ) -> None:
        self._sessions = sessions
        self._iterations = iterations
        self._hypotheses = hypotheses
        self._experiments = experiments
        self._events = events
        self._clock = clock

    def execute(self, session_id: str, owner_id: str) -> AgentSessionOverview:
        session = self._sessions.get(session_id)
        if session is None or session.owner_id != owner_id:
            raise AgentOverviewNotFoundError("session not found")
        now = self._clock.now()
        iterations = self._iterations.list_for_session(session_id, limit=100)
        hypotheses = self._hypotheses.list_for_session(session_id)
        experiments = self._experiments.list_for_session(session_id, limit=100)
        latest = self._events.list_latest(session_id, limit=1)
        health = self._health(session, latest[0].occurred_at if latest else None, now)
        return AgentSessionOverview(
            session_id=session_id,
            status=session.status.value,
            verdict=self._verdict(session, iterations, hypotheses, health),
            health=health,
            iterations=dict(Counter(item.status.value for item in iterations)),
            hypotheses=dict(Counter(item.status.value for item in hypotheses)),
            experiments=dict(Counter(item.status.value for item in experiments)),
            events_total=latest[0].seq if latest else 0,
            block=dict(session.block),
        )

    @staticmethod
    def _health(session: AgentSession, last_event_at, now) -> AgentHealth:
        expires = session.lease_expires_at
        if expires is None:
            lease = "NONE"
        elif expires > now:
            lease = "ACTIVE"
        else:
            lease = "EXPIRED"
        stalled = (
            session.status == AgentSessionStatus.ACTIVE
            and expires is not None
            and (now - expires).total_seconds() > STALL_GRACE_SECONDS
        )
        return AgentHealth(
            lease=lease,
            stalled=stalled,
            last_event_at=last_event_at,
            seconds_since_last_event=(
                max(0, int((now - last_event_at).total_seconds()))
                if last_event_at
                else None
            ),
        )

    @staticmethod
    def _verdict(session, iterations, hypotheses, health) -> AgentVerdict:
        status = session.status
        if status == AgentSessionStatus.DRAFT:
            return AgentVerdict(
                "draft", "Sin iniciar", "La sesión aún no se ha lanzado."
            )
        if status == AgentSessionStatus.WAITING_USER and session.block.get("code"):
            failure = describe_failure(str(session.block["code"]))
            return AgentVerdict(
                "blocked",
                failure.title,
                failure.detail,
                failure.action,
                failure.code,
                failure.approval,
                failure.retryable,
            )
        if status in {
            AgentSessionStatus.WAITING_USER,
            AgentSessionStatus.WAITING_APPROVAL,
        }:
            return AgentVerdict(
                "blocked",
                "Esperando tu respuesta",
                "El agente necesita una aclaración.",
            )
        if status == AgentSessionStatus.PAUSED:
            return AgentVerdict(
                "paused",
                "En pausa",
                "La sesión está en pausa; puedes reanudarla cuando quieras.",
            )
        if status == AgentSessionStatus.CANCELLED:
            return AgentVerdict("cancelled", "Cancelada", "La sesión fue cancelada.")
        if status == AgentSessionStatus.FAILED:
            return AgentVerdict(
                "failed",
                "La sesión falló",
                "La sesión terminó con un error.",
                "Revisa la línea de tiempo.",
            )
        if status in {AgentSessionStatus.COMPLETED, AgentSessionStatus.STOPPED}:
            validated = any(
                item.status == AgentHypothesisStatus.VALIDATED for item in hypotheses
            )
            if not validated:
                return AgentVerdict(
                    "inconclusive",
                    "Sin hallazgos concluyentes",
                    "Ninguna hipótesis llegó a validarse con la evidencia disponible.",
                    "Revisa las hipótesis refutadas o inconclusas.",
                )
            return AgentVerdict(
                "completed" if status == AgentSessionStatus.COMPLETED else "stopped",
                "Terminada",
                "La sesión terminó con al menos una hipótesis validada.",
            )
        # ACTIVE
        last = iterations[-1] if iterations else None
        if health.stalled:
            failure = describe_failure("WORKER_LEASE_EXPIRED")
            return AgentVerdict(
                "stalled",
                failure.title,
                failure.detail,
                failure.action,
                failure.code,
                retryable=True,
            )
        if last is not None and last.status == AgentIterationStatus.FAILED:
            failure = describe_failure(str(last.decision.get("failure_code") or ""))
            return AgentVerdict(
                "failing",
                f"La iteración {last.number} falló: {failure.title}",
                failure.detail,
                failure.action,
                failure.code,
                failure.approval,
                failure.retryable,
            )
        if last is not None and last.status == AgentIterationStatus.RUNNING:
            return AgentVerdict(
                "running",
                f"Trabajando en la iteración {last.number}",
                "Un especialista está ejecutando el experimento.",
            )
        return AgentVerdict("running", "En marcha", "El agente está entre iteraciones.")
