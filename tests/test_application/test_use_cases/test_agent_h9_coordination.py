from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from src.application.ports.agent_budget_ledger_port import AgentBudgetEntry
from src.application.ports.agent_session_port import AgentSession, AgentSessionStatus
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettings,
)
from src.application.use_cases.agent.manage_agent_entity_claims import (
    AgentEntityClaimUseCase,
)
from src.application.use_cases.agent.renew_agent_budget import (
    AgentBudgetRenewalError,
    RenewAgentBudgetUseCase,
)

NOW = datetime(2026, 10, 20, tzinfo=UTC)


class FixedClock:
    def now(self):
        return NOW


class InMemorySessions:
    def __init__(self, session):
        self.session = session

    def get(self, session_id):
        return self.session if session_id == self.session.session_id else None

    def update(self, session, expected_rev):
        assert expected_rev == self.session.rev
        self.session = replace(session, rev=expected_rev + 1)
        return self.session


class InMemoryClaims:
    def __init__(self):
        self.items = {}

    def claim(self, claim):
        self.items[(claim.entity_key, claim.session_id)] = claim
        return claim

    def list_by_entity(self, entity_key, limit=50):
        return [value for value in self.items.values() if value.entity_key == entity_key][:limit]

    def list_by_session(self, session_id, limit=100):
        return [value for value in self.items.values() if value.session_id == session_id][:limit]

    def release_session(self, session_id):
        keys = [key for key in self.items if key[1] == session_id]
        for key in keys:
            del self.items[key]
        return len(keys)


class InMemoryLedger:
    def __init__(self):
        self.items: list[AgentBudgetEntry] = []

    def append(self, entry):
        self.items.append(entry)
        return entry


class MutableSettings:
    def __init__(self, settings):
        self.settings = settings

    def get(self):
        return self.settings


class SequenceIds:
    def __init__(self):
        self.value = 0

    def new_id(self):
        self.value += 1
        return str(self.value)


def test_claims_are_heartbeated_and_only_active_sessions_are_reported():
    session = AgentSession(
        session_id="s1",
        mode="optimization",
        status=AgentSessionStatus.ACTIVE,
        owner_id="manager",
        created_at=NOW,
        updated_at=NOW,
        scope={"areas": ["model", "library", "model"]},
    )
    sessions, claims = InMemorySessions(session), InMemoryClaims()
    use_case = AgentEntityClaimUseCase(
        sessions=sessions, claims=claims, clock=FixedClock()
    )

    created = use_case.heartbeat("s1")
    assert [item.entity_key for item in created] == ["scope#library", "scope#model"]
    assert use_case.list_active("scope#model") == [created[1]]

    sessions.session = replace(sessions.session, status=AgentSessionStatus.PAUSED)
    assert use_case.list_active("scope#model") == []
    assert claims.items[("scope#model", "s1")].expires_at == NOW + timedelta(seconds=120)


def test_budget_renewal_is_audited_in_ledger_and_limited_by_live_settings():
    session = AgentSession(
        session_id="s1",
        mode="optimization",
        status=AgentSessionStatus.PAUSED,
        owner_id="manager",
        created_at=NOW,
        updated_at=NOW,
        budget_limits={"tokens": 100},
    )
    sessions, ledger = InMemorySessions(session), InMemoryLedger()
    use_case = RenewAgentBudgetUseCase(
        sessions=sessions,
        ledger=ledger,
        settings=MutableSettings(AssistantOptimizerSettings(optimizer_max_budget_renewals=1)),
        clock=FixedClock(),
        ids=SequenceIds(),
    )

    renewed = use_case.execute("s1", "channel-manager", {"tokens": 50, "seconds": 30})
    assert renewed.budget_limits == {"tokens": 150, "seconds": 30}
    assert renewed.budget_renewals == 1
    assert {(item.resource, item.amount, item.entry_type) for item in ledger.items} == {
        ("tokens", 50, "RENEW"),
        ("seconds", 30, "RENEW"),
    }
    with pytest.raises(AgentBudgetRenewalError, match="limit reached"):
        use_case.execute("s1", "channel-manager", {"tokens": 50})
