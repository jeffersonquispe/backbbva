from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from src.application.ports.audit_port import AuditEntry
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.use_cases.agent.agent_timeline import AgentTimeline
from src.domain.agents.event import AgentEvent, AgentEventKind, AgentEventOutcome

NOW = datetime(2026, 10, 26, tzinfo=UTC)


class FixedClock(Clock):
    def now(self) -> datetime:
        return NOW


class SequenceIds(IdGenerator):
    def __init__(self) -> None:
        self.value = 0

    def new_id(self) -> UUID:
        self.value += 1
        return UUID(int=self.value)


class InMemoryEvents:
    def __init__(self, fail: bool = False) -> None:
        self.items: list[AgentEvent] = []
        self.fail = fail

    def append(self, event):
        if self.fail:
            raise RuntimeError("storage down")
        stored = AgentEvent(**{**event.__dict__, "seq": len(self.items) + 1})
        self.items.append(stored)
        return stored

    def list_for_session(self, session_id, *, after_seq=0, limit=100):
        return [item for item in self.items if item.seq > after_seq][:limit]

    def list_latest(self, session_id, limit=20):
        return list(reversed(self.items))[:limit]


class RecordingAudit:
    def __init__(self, fail: bool = False) -> None:
        self.entries: list[AuditEntry] = []
        self.fail = fail

    def write(self, entry: AuditEntry) -> None:
        if self.fail:
            raise RuntimeError("audit down")
        self.entries.append(entry)


def _timeline(events=None, audit=None) -> AgentTimeline:
    return AgentTimeline(
        events=events or InMemoryEvents(),
        clock=FixedClock(),
        ids=SequenceIds(),
        audit=audit,
    )


def test_record_assigns_sequence_and_drops_unsafe_refs() -> None:
    events = InMemoryEvents()
    timeline = _timeline(events)

    timeline.record(
        "s1",
        AgentEventKind.ITERATION,
        AgentEventOutcome.STARTED,
        "Iteración 1",
        refs={"iteration": 1, "customer_id": "c-9", "amount": 100},
    )
    timeline.record("s1", AgentEventKind.ITERATION, AgentEventOutcome.SUCCEEDED, "ok")

    assert [item.seq for item in events.items] == [1, 2]
    assert events.items[0].refs == {"iteration": "1"}
    assert events.items[0].expires_at is not None


def test_storage_failure_never_breaks_the_caller() -> None:
    timeline = _timeline(InMemoryEvents(fail=True))

    assert (
        timeline.record("s1", AgentEventKind.SESSION, AgentEventOutcome.INFO, "x")
        is None
    )


def test_failure_uses_catalogue_copy_and_hides_raw_codes() -> None:
    events = InMemoryEvents()
    timeline = _timeline(events)

    timeline.record_failure("s1", AgentEventKind.SPECIALIST, "MODEL_TRAINING_FAILED")
    timeline.record_failure("s1", AgentEventKind.SPECIALIST, "KeyError: customer 55")

    assert events.items[0].summary == "Falló el entrenamiento"
    assert events.items[0].reason_code == "MODEL_TRAINING_FAILED"
    assert events.items[1].reason_code == "UNKNOWN_FAILURE"
    assert "customer" not in events.items[1].summary


def test_blocked_event_carries_the_approval_reason() -> None:
    events = InMemoryEvents()

    _timeline(events).record_blocked("s1", "BUDGET_EXHAUSTED")

    assert events.items[0].kind is AgentEventKind.BLOCKED
    assert events.items[0].outcome is AgentEventOutcome.BLOCKED
    assert events.items[0].reason_code == "BUDGET_EXHAUSTED"


def test_production_change_lands_in_both_audit_log_and_timeline() -> None:
    events, audit = InMemoryEvents(), RecordingAudit()
    timeline = _timeline(events, audit)

    event = timeline.record_production_change(
        "s1",
        action="agent.release.approved",
        entity_type="agent_release",
        entity_id="rel-1",
        actor_id="manager-1",
        outcome="approved",
        summary="Release aprobado",
        refs={"release_id": "rel-1"},
    )

    assert len(audit.entries) == 1
    assert audit.entries[0].action == "agent.release.approved"
    assert event.kind is AgentEventKind.PRODUCTION_CHANGE
    assert event.outcome is AgentEventOutcome.SUCCEEDED
    assert event.refs["audit_correlation_id"] == audit.entries[0].correlation_id
    assert event.refs["release_id"] == "rel-1"


def test_production_change_aborts_when_the_audit_log_is_down() -> None:
    events = InMemoryEvents()
    timeline = _timeline(events, RecordingAudit(fail=True))

    with pytest.raises(RuntimeError):
        timeline.record_production_change(
            "s1",
            action="a",
            entity_type="t",
            entity_id=None,
            actor_id="u",
            outcome="success",
            summary="x",
        )

    assert events.items == []


def test_production_change_requires_an_audit_port() -> None:
    with pytest.raises(RuntimeError, match="AUDIT_PORT_REQUIRED"):
        _timeline().record_production_change(
            "s1",
            action="a",
            entity_type="t",
            entity_id=None,
            actor_id="u",
            outcome="success",
            summary="x",
        )
