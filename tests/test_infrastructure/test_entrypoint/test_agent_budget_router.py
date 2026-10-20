from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.ports.agent_budget_ledger_port import AgentBudgetEntry
from src.application.ports.agent_iteration_port import (
    AgentIteration,
    AgentIterationStatus,
)
from src.application.ports.agent_run_port import AgentRun, AgentRunStatus
from src.application.ports.agent_session_port import AgentSession, AgentSessionStatus
from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.infrastructure.entrypoint.api.routers import agent_router
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user


class InMemorySessions:
    def __init__(self, session: AgentSession) -> None:
        self.session = session

    def get(self, session_id: str):
        return self.session if session_id == self.session.session_id else None


class InMemoryLedger:
    def list_for_session(self, session_id: str, limit: int = 100):
        return [
            AgentBudgetEntry(
                session_id=session_id,
                entry_id="spend-1",
                entry_type="SPEND",
                resource="tokens",
                amount=7,
                actor="agent",
                reason="iteration",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            AgentBudgetEntry(
                session_id=session_id,
                entry_id="renewal-1",
                entry_type="RENEWAL",
                resource="tokens",
                amount=100,
                actor="manager",
                reason="approved renewal",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        ]


class InMemoryIterations:
    def list_for_session(self, session_id: str):
        return [
            AgentIteration(
                session_id=session_id,
                number=1,
                status=AgentIterationStatus.SUCCEEDED,
                started_at=datetime(2026, 1, 1, tzinfo=UTC),
                run_ids=("run-1",),
                decision={"hypothesis": "Hipótesis", "action": "continue", "reason": "evidence"},
            )
        ]


class InMemoryRuns:
    def get(self, run_id: str):
        if run_id != "run-1":
            return None
        return AgentRun(
            run_id=run_id,
            session_id="session-1",
            iteration_number=1,
            subagent="data_profiler",
            status=AgentRunStatus.SUCCEEDED,
            prompt_ref={},
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_session_budget_returns_only_aggregated_spend(monkeypatch) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    user = LocalUser(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        email="manager@example.com",
        name="Manager",
        password_hash="",
        role=LocalRole.MANAGER,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    session = AgentSession(
        session_id="session-1",
        mode="optimization",
        status=AgentSessionStatus.ACTIVE,
        owner_id=str(user.id),
        created_at=now,
        updated_at=now,
        budget_limits={"tokens": 50},
    )
    monkeypatch.setattr(agent_router, "get_agent_session_repository", lambda: InMemorySessions(session))
    monkeypatch.setattr(
        agent_router,
        "get_agent_budget_ledger_repository",
        lambda: InMemoryLedger(),
    )
    app = FastAPI()
    app.include_router(agent_router.router)
    app.dependency_overrides[get_current_user] = lambda: user

    response = TestClient(app).get("/agent/sessions/session-1/budget")

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "session-1",
        "spent": {"tokens": 7},
        "limits": {"tokens": 50},
    }


def test_session_iterations_include_run_specialists(monkeypatch) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    user = LocalUser(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        email="manager@example.com",
        name="Manager",
        password_hash="",
        role=LocalRole.MANAGER,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    session = AgentSession(
        session_id="session-1",
        mode="optimization",
        status=AgentSessionStatus.ACTIVE,
        owner_id=str(user.id),
        created_at=now,
        updated_at=now,
    )
    monkeypatch.setattr(agent_router, "get_agent_session_repository", lambda: InMemorySessions(session))
    monkeypatch.setattr(agent_router, "get_agent_iteration_repository", lambda: InMemoryIterations())
    monkeypatch.setattr(agent_router, "get_agent_run_repository", lambda: InMemoryRuns())
    app = FastAPI()
    app.include_router(agent_router.router)
    app.dependency_overrides[get_current_user] = lambda: user

    response = TestClient(app).get("/agent/sessions/session-1/iterations")

    assert response.status_code == 200
    assert response.json()[0]["specialists"] == ["data_profiler"]
