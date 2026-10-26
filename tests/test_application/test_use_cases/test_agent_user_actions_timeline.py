from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from src.application.ports.agent_insight_port import (
    AgentInsight,
    AgentInsightKind,
    AgentInsightStatus,
)
from src.application.ports.agent_session_port import AgentSession, AgentSessionStatus
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.use_cases.agent.agent_timeline import AgentTimeline
from src.application.use_cases.agent.manage_agent_insight import (
    ManageAgentInsightUseCase,
)
from src.application.use_cases.agent.manage_agent_session import (
    ManageAgentSessionUseCase,
)

NOW = datetime(2026, 10, 26, tzinfo=UTC)


class FixedClock(Clock):
    def now(self) -> datetime:
        return NOW


class Ids(IdGenerator):
    def __init__(self) -> None:
        self.value = 0

    def new_id(self) -> UUID:
        self.value += 1
        return UUID(int=self.value)


class Events:
    def __init__(self) -> None:
        self.items = []

    def append(self, event):
        self.items.append(event)
        return event


class Sessions:
    def __init__(self, session):
        self.session = session

    def get(self, session_id):
        return self.session

    def update(self, session, expected_rev):
        self.session = replace(session, rev=expected_rev + 1)
        return self.session


class Insights:
    def __init__(self, insight):
        self.insight = insight

    def get(self, session_id, insight_id):
        return self.insight

    def update(self, insight, expected_rev):
        self.insight = replace(insight, rev=expected_rev + 1)
        return self.insight


def _session(status=AgentSessionStatus.ACTIVE):
    return AgentSession(
        session_id="s1",
        mode="optimization",
        status=status,
        owner_id="cm-1",
        created_at=NOW,
        updated_at=NOW,
    )


def test_pause_resume_and_cancel_are_on_the_session_timeline() -> None:
    events = Events()
    use_case = ManageAgentSessionUseCase(
        repository=Sessions(_session()),
        clock=FixedClock(),
        timeline=AgentTimeline(events=events, clock=FixedClock(), ids=Ids()),
    )

    use_case.pause("s1", "cm-1")
    use_case.resume("s1", "cm-1")
    use_case.cancel("s1", "cm-1")

    assert [
        (item.kind.value, item.reason_code, item.actor_id) for item in events.items
    ] == [
        ("user_action", "SESSION_PAUSED", "cm-1"),
        ("user_action", "SESSION_ACTIVE", "cm-1"),
        ("user_action", "SESSION_CANCELLED", "cm-1"),
    ]


def test_confirming_or_rejecting_an_insight_is_traced_with_its_reference() -> None:
    insight = AgentInsight(
        session_id="s1",
        insight_id="i1",
        kind=AgentInsightKind.HYPOTHESIS,
        statement="x",
        scope={},
        status=AgentInsightStatus.PROPOSED,
        proposed_by="agent",
        author_id="agent",
        source_message_id=None,
        created_at=NOW,
        updated_at=NOW,
    )
    events = Events()
    use_case = ManageAgentInsightUseCase(
        sessions=Sessions(_session()),
        insights=Insights(insight),
        clock=FixedClock(),
        timeline=AgentTimeline(events=events, clock=FixedClock(), ids=Ids()),
    )

    use_case.confirm("s1", "i1", "cm-1")

    assert [(item.summary, item.refs) for item in events.items] == [
        ("Confirmaste un insight", {"insight_id": "i1"})
    ]
