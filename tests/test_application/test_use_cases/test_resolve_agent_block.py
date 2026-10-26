from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from src.application.ports.agent_budget_ledger_port import AgentBudgetEntry
from src.application.ports.agent_hypothesis_port import (
    AgentHypothesis,
    AgentHypothesisStatus,
)
from src.application.ports.agent_insight_port import AgentInsight
from src.application.ports.agent_iteration_port import (
    AgentIteration,
    AgentIterationStatus,
)
from src.application.ports.agent_link_port import AgentLink
from src.application.ports.agent_session_port import (
    AgentSession,
    AgentSessionStatus,
)
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettings,
    AssistantOptimizerSettingsPort,
)
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.personal_data_masker_port import (
    MaskedPersonalData,
    PersonalDataMasker,
)
from src.application.use_cases.agent.agent_timeline import AgentTimeline
from src.application.use_cases.agent.resolve_agent_block import (
    AgentBlockNotFoundError,
    AgentBlockPolicyError,
    ResolveAgentBlockInput,
    ResolveAgentBlockUseCase,
)
from src.domain.agents.event import AgentEvent

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


class Sessions:
    def __init__(self, session: AgentSession) -> None:
        self.session = session

    def get(self, session_id):
        return self.session if session_id == self.session.session_id else None

    def update(self, session, expected_rev):
        assert expected_rev == self.session.rev
        self.session = replace(session, rev=expected_rev + 1)
        return self.session


class Iterations:
    def __init__(self, *numbers: int) -> None:
        self.numbers = numbers

    def list_for_session(self, session_id, limit=50):
        return [
            AgentIteration(
                session_id=session_id,
                number=number,
                status=AgentIterationStatus.SUCCEEDED,
                started_at=NOW,
            )
            for number in self.numbers
        ]


class Ledger:
    def __init__(self) -> None:
        self.entries: list[AgentBudgetEntry] = []

    def append(self, entry):
        self.entries.append(entry)
        return entry


class Settings(AssistantOptimizerSettingsPort):
    def get(self):
        return AssistantOptimizerSettings(
            optimizer_session_budget_ceiling_tokens=1_000,
            optimizer_session_budget_ceiling_usd=10.0,
            optimizer_session_budget_ceiling_seconds=1_000,
        )

    def update(self, *args, **kwargs):
        raise NotImplementedError


class Hypotheses:
    def __init__(self) -> None:
        self.items: list[AgentHypothesis] = []

    def create(self, item):
        self.items.append(item)
        return item


class Insights:
    def __init__(self) -> None:
        self.items: list[AgentInsight] = []

    def create(self, item):
        self.items.append(item)
        return item


class Links:
    def __init__(self) -> None:
        self.items: list[AgentLink] = []

    def create_once(self, link):
        self.items.append(link)
        return link


class Masker(PersonalDataMasker):
    def mask(self, text):
        found = {"email": 1} if "@" in text else {}
        return MaskedPersonalData(text=text.replace("@", "[x]"), counts=found)


class Events:
    def __init__(self) -> None:
        self.items: list[AgentEvent] = []

    def append(self, event):
        self.items.append(event)
        return event


def _blocked(code: str, **changes) -> AgentSession:
    return replace(
        AgentSession(
            session_id="s1",
            mode="optimization",
            status=AgentSessionStatus.WAITING_USER,
            owner_id="cm-1",
            created_at=NOW,
            updated_at=NOW,
            budget_limits={"tokens": 100, "usd_micros": 100, "seconds": 100},
            block={"code": code},
            rev=4,
        ),
        **changes,
    )


def _use_case(session: AgentSession, iterations=(1, 2, 3)):
    parts = {
        "sessions": Sessions(session),
        "ledger": Ledger(),
        "hypotheses": Hypotheses(),
        "insights": Insights(),
        "links": Links(),
        "events": Events(),
    }
    use_case = ResolveAgentBlockUseCase(
        sessions=parts["sessions"],
        iterations=Iterations(*iterations),
        ledger=parts["ledger"],
        settings=Settings(),
        hypotheses=parts["hypotheses"],
        insights=parts["insights"],
        links=parts["links"],
        masker=Masker(),
        timeline=AgentTimeline(
            events=parts["events"], clock=FixedClock(), ids=SequenceIds()
        ),
        clock=FixedClock(),
        ids=SequenceIds(),
    )
    return use_case, parts


def test_budget_grant_raises_limits_resumes_and_leaves_ledger_and_event() -> None:
    use_case, parts = _use_case(_blocked("BUDGET_EXHAUSTED"))

    saved = use_case.execute(
        ResolveAgentBlockInput(
            "s1", "cm-1", "budget", additions={"tokens": 50, "seconds": 20}
        )
    )

    assert saved.status == AgentSessionStatus.ACTIVE
    assert saved.block == {}
    assert saved.budget_limits == {"tokens": 150, "usd_micros": 100, "seconds": 120}
    assert saved.budget_renewals == 1
    assert [(e.resource, e.entry_type) for e in parts["ledger"].entries] == [
        ("seconds", "RENEW"),
        ("tokens", "RENEW"),
    ]
    assert parts["events"].items[0].kind.value == "user_action"
    assert parts["events"].items[0].actor_id == "cm-1"


def test_budget_grant_cannot_exceed_the_global_ceiling() -> None:
    use_case, _ = _use_case(_blocked("BUDGET_EXHAUSTED"))

    with pytest.raises(AgentBlockPolicyError) as error:
        use_case.execute(
            ResolveAgentBlockInput("s1", "cm-1", "budget", additions={"tokens": 5_000})
        )

    assert error.value.code == "BUDGET_CEILING_EXCEEDED"


def test_candidate_grant_extends_allowance_and_resets_stagnation() -> None:
    use_case, _ = _use_case(_blocked("STAGNATION"))

    saved = use_case.execute(
        ResolveAgentBlockInput("s1", "cm-1", "candidates", allowance=5)
    )

    assert saved.candidate_allowance == 5
    assert saved.stagnation_reset_after == 3
    assert saved.status == AgentSessionStatus.ACTIVE


@pytest.mark.parametrize("allowance", [0, -1, 21, None])
def test_candidate_grant_is_bounded(allowance) -> None:
    use_case, _ = _use_case(_blocked("CANDIDATE_LIMIT_REACHED"))

    with pytest.raises(AgentBlockPolicyError) as error:
        use_case.execute(
            ResolveAgentBlockInput("s1", "cm-1", "candidates", allowance=allowance)
        )

    assert error.value.code == "INVALID_ALLOWANCE"


def test_context_grant_creates_directive_hypothesis_and_trace_link() -> None:
    use_case, parts = _use_case(_blocked("CONTEXT_MISSING"))

    saved = use_case.execute(
        ResolveAgentBlockInput(
            "s1", "cm-1", "context", note="Priorizar falsos positivos nocturnos"
        )
    )

    insight = parts["insights"].items[0]
    hypothesis = parts["hypotheses"].items[0]
    assert insight.kind.value == "directive"
    assert hypothesis.status is AgentHypothesisStatus.ACTIVE
    assert hypothesis.source_insight_id == insight.insight_id
    assert hypothesis.priority == 100
    assert parts["links"].items[0].target_id == hypothesis.hypothesis_id
    assert saved.status == AgentSessionStatus.ACTIVE
    assert saved.stagnation_reset_after == 3


def test_context_with_personal_data_is_refused() -> None:
    use_case, parts = _use_case(_blocked("CONTEXT_MISSING"))

    with pytest.raises(AgentBlockPolicyError) as error:
        use_case.execute(
            ResolveAgentBlockInput(
                "s1", "cm-1", "context", note="ana@banco.com revisar"
            )
        )

    assert error.value.code == "PERSONAL_DATA_BLOCKED"
    assert parts["insights"].items == []


def test_a_grant_that_does_not_match_the_block_is_refused() -> None:
    use_case, _ = _use_case(_blocked("BUDGET_EXHAUSTED"))

    with pytest.raises(AgentBlockPolicyError) as error:
        use_case.execute(
            ResolveAgentBlockInput("s1", "cm-1", "candidates", allowance=3)
        )

    assert error.value.code == "GRANT_NOT_APPLICABLE"


def test_only_the_owner_can_resolve_and_only_a_blocked_session() -> None:
    use_case, _ = _use_case(_blocked("BUDGET_EXHAUSTED"))
    with pytest.raises(AgentBlockNotFoundError):
        use_case.execute(
            ResolveAgentBlockInput("s1", "intruder", "budget", additions={"tokens": 1})
        )

    running, _ = _use_case(
        _blocked("BUDGET_EXHAUSTED", status=AgentSessionStatus.ACTIVE, block={})
    )
    with pytest.raises(AgentBlockPolicyError) as error:
        running.execute(
            ResolveAgentBlockInput("s1", "cm-1", "budget", additions={"tokens": 1})
        )
    assert error.value.code == "SESSION_NOT_BLOCKED"
