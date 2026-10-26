"""Single writer of the per-session `agent_events` timeline.

Timeline writes are best-effort: a storage hiccup must never fail an
iteration. The exception is a production change, which is also written to the
global audit log and must fail loudly when that write cannot be done.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta

from src.application.ports.agent_event_port import AgentEventRepository
from src.application.ports.audit_port import AuditEntry, AuditPort
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.domain.agents.event import (
    AgentEvent,
    AgentEventKind,
    AgentEventOutcome,
    safe_refs,
)
from src.domain.agents.failure_catalog import describe_failure

RETENTION_DAYS = 730  # same two-year retention as the chat and audit trail.
_LOGGER = logging.getLogger(__name__)


class AgentTimeline:
    def __init__(
        self,
        *,
        events: AgentEventRepository,
        clock: Clock,
        ids: IdGenerator,
        audit: AuditPort | None = None,
    ) -> None:
        self._events = events
        self._clock = clock
        self._ids = ids
        self._audit = audit

    def record(
        self,
        session_id: str,
        kind: AgentEventKind,
        outcome: AgentEventOutcome,
        summary: str,
        *,
        reason_code: str | None = None,
        refs: Mapping[str, object] | None = None,
        duration_ms: int | None = None,
        cost_micros: int | None = None,
        actor_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> AgentEvent | None:
        try:
            return self._append(
                session_id,
                kind,
                outcome,
                summary,
                reason_code,
                refs,
                duration_ms,
                cost_micros,
                actor_id,
                occurred_at,
            )
        except Exception:  # noqa: BLE001 - observability never breaks the run
            _LOGGER.warning("agent timeline write failed", exc_info=True)
            return None

    def record_failure(
        self,
        session_id: str,
        kind: AgentEventKind,
        code: str | None,
        *,
        refs: Mapping[str, object] | None = None,
        duration_ms: int | None = None,
        occurred_at: datetime | None = None,
    ) -> AgentEvent | None:
        failure = describe_failure(code)
        return self.record(
            session_id,
            kind,
            AgentEventOutcome.FAILED,
            failure.title,
            reason_code=failure.code,
            refs=refs,
            duration_ms=duration_ms,
            occurred_at=occurred_at,
        )

    def record_blocked(
        self,
        session_id: str,
        code: str,
        *,
        refs: Mapping[str, object] | None = None,
        occurred_at: datetime | None = None,
    ) -> AgentEvent | None:
        failure = describe_failure(code)
        return self.record(
            session_id,
            AgentEventKind.BLOCKED,
            AgentEventOutcome.BLOCKED,
            failure.title,
            reason_code=failure.code,
            refs=refs,
            occurred_at=occurred_at,
        )

    def record_production_change(
        self,
        session_id: str,
        *,
        action: str,
        entity_type: str,
        entity_id: str | None,
        actor_id: str,
        outcome: str,
        summary: str,
        refs: Mapping[str, object] | None = None,
        correlation_id: str | None = None,
        parent_id: str | None = None,
        actor_type: str = "user",
    ) -> AgentEvent:
        """Write the change to the audit log and to the timeline, in that order.

        The audit write is the legal record, so it comes first and its failure
        aborts the change. Both rows share `correlation_id`.
        """
        if self._audit is None:
            raise RuntimeError("AUDIT_PORT_REQUIRED_FOR_PRODUCTION_CHANGE")
        now = self._clock.now()
        correlation = correlation_id or str(self._ids.new_id())
        self._audit.write(
            AuditEntry(
                actor_type=actor_type,
                actor_id=actor_id,
                worker_name=None,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                correlation_id=correlation,
                parent_id=parent_id,
                occurred_at=now,
                outcome=outcome,
            )
        )
        merged = {**(refs or {}), "audit_correlation_id": correlation}
        succeeded = outcome in {"success", "approved"}
        event = self._append(
            session_id,
            AgentEventKind.PRODUCTION_CHANGE,
            AgentEventOutcome.SUCCEEDED if succeeded else AgentEventOutcome.FAILED,
            summary,
            None,
            merged,
            None,
            None,
            actor_id,
            now,
        )
        return event

    def record_applied_change(
        self,
        session_id: str,
        *,
        entity_type: str,
        entity_id: str | None,
        actor_id: str,
        package_id: str,
    ) -> AgentEvent | None:
        """Timeline row for a draft the user confirmed and the system applied.

        The draft use cases already wrote the audit-log entry (correlated by the
        package id), so only the timeline row is added here.
        """
        return self.record(
            session_id,
            AgentEventKind.PRODUCTION_CHANGE,
            AgentEventOutcome.SUCCEEDED,
            "Borrador aplicado a producción",
            refs={"package_id": package_id, "audit_correlation_id": package_id},
            actor_id=actor_id,
        )

    def _append(
        self,
        session_id,
        kind,
        outcome,
        summary,
        reason_code,
        refs,
        duration_ms,
        cost_micros,
        actor_id,
        occurred_at,
    ) -> AgentEvent:
        now = occurred_at or self._clock.now()
        event = AgentEvent(
            session_id=session_id,
            seq=0,
            event_id=str(self._ids.new_id()),
            occurred_at=now,
            kind=kind,
            outcome=outcome,
            summary=summary[:200],
            reason_code=reason_code,
            refs=safe_refs(refs),
            duration_ms=duration_ms,
            cost_micros=cost_micros,
            actor_id=actor_id,
            expires_at=int((now + timedelta(days=RETENTION_DAYS)).timestamp()),
        )
        return self._events.append(replace(event))
