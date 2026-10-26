from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.ports.agent_session_port import AgentSession, AgentSessionStatus
from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.use_cases.agent.get_agent_session_overview import (
    AgentHealth,
    AgentSessionOverview,
    AgentVerdict,
)
from src.application.use_cases.agent.resolve_agent_block import (
    AgentBlockPolicyError,
)
from src.domain.agents.event import AgentEvent, AgentEventKind, AgentEventOutcome
from src.domain.agents.finding import (
    OptimizerInsight,
    OptimizerInsightKind,
    OptimizerInsightStatus,
)
from src.infrastructure.entrypoint.api.routers import agent_router
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user

NOW = datetime(2026, 10, 26, tzinfo=UTC)
USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def _user(role: LocalRole) -> LocalUser:
    return LocalUser(
        id=USER_ID,
        email="cm@example.com",
        name="CM",
        password_hash="",
        role=role,
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _session() -> AgentSession:
    return AgentSession(
        session_id="session-1",
        mode="optimization",
        status=AgentSessionStatus.WAITING_USER,
        owner_id=str(USER_ID),
        created_at=NOW,
        updated_at=NOW,
        budget_limits={"tokens": 50},
        block={"code": "BUDGET_EXHAUSTED", "since": NOW.isoformat()},
    )


class Sessions:
    def get(self, session_id):
        return _session() if session_id == "session-1" else None


class Events:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def list_for_session(self, session_id, *, after_seq=0, limit=100):
        self.calls.append((after_seq, limit))
        return [
            AgentEvent(
                session_id=session_id,
                seq=after_seq + 1,
                event_id="e",
                occurred_at=NOW,
                kind=AgentEventKind.BLOCKED,
                outcome=AgentEventOutcome.BLOCKED,
                summary="Presupuesto agotado",
                reason_code="BUDGET_EXHAUSTED",
                refs={"iteration": "2"},
            )
        ]


def _client(monkeypatch, role=LocalRole.CHANNEL_MANAGER) -> TestClient:
    monkeypatch.setattr(
        agent_router, "get_agent_session_repository", lambda: Sessions()
    )
    app = FastAPI()
    app.include_router(agent_router.router)
    app.dependency_overrides[get_current_user] = lambda: _user(role)
    return TestClient(app)


def test_overview_returns_the_verdict_with_the_requested_approval(monkeypatch) -> None:
    class UseCase:
        def execute(self, session_id, owner_id):
            return AgentSessionOverview(
                session_id=session_id,
                status="WAITING_USER",
                verdict=AgentVerdict(
                    "blocked",
                    "Presupuesto agotado",
                    "La sesión consumió el presupuesto autorizado.",
                    "Aprueba más presupuesto para que continúe.",
                    "BUDGET_EXHAUSTED",
                    "budget",
                ),
                health=AgentHealth("NONE", False),
                iterations={"SUCCEEDED": 2},
                block={"code": "BUDGET_EXHAUSTED"},
            )

    monkeypatch.setattr(agent_router, "get_agent_session_overview_use_case", UseCase)

    response = _client(monkeypatch).get("/agent/sessions/session-1/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["verdict"]["state"] == "blocked"
    assert body["verdict"]["approval"] == "budget"
    assert body["health"] == {
        "lease": "NONE",
        "stalled": False,
        "last_event_at": None,
        "seconds_since_last_event": None,
    }
    assert body["iterations"] == {"SUCCEEDED": 2}


def test_events_page_exposes_only_safe_fields(monkeypatch) -> None:
    events = Events()
    monkeypatch.setattr(agent_router, "get_agent_event_repository", lambda: events)

    response = _client(monkeypatch).get(
        "/agent/sessions/session-1/events?after_seq=4&limit=10"
    )

    assert response.status_code == 200
    body = response.json()
    assert events.calls == [(4, 10)]
    assert body["last_seq"] == 5
    item = body["items"][0]
    assert set(item) == {
        "seq",
        "event_id",
        "occurred_at",
        "kind",
        "outcome",
        "summary",
        "reason_code",
        "refs",
        "duration_ms",
        "cost_micros",
        "actor_id",
    }
    assert item["refs"] == {"iteration": "2"}


def test_events_reject_bad_paging_and_foreign_sessions(monkeypatch) -> None:
    monkeypatch.setattr(agent_router, "get_agent_event_repository", lambda: Events())
    client = _client(monkeypatch)

    assert client.get("/agent/sessions/session-1/events?limit=500").status_code == 422
    assert client.get("/agent/sessions/other/events").status_code == 404


def test_only_the_channel_manager_can_resolve_a_block(monkeypatch) -> None:
    response = _client(monkeypatch, LocalRole.MANAGER).post(
        "/agent/sessions/session-1/block/resolve",
        json={"kind": "budget", "additions": {"tokens": 10}},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {"code": "ROLE_NOT_ALLOWED"}


def test_resolving_a_block_resumes_and_enqueues_the_session(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class UseCase:
        def execute(self, request):
            seen["request"] = request
            return replace(_session(), status=AgentSessionStatus.ACTIVE, block={})

    queued: list[str] = []
    monkeypatch.setattr(agent_router, "get_resolve_agent_block_use_case", UseCase)
    monkeypatch.setattr(agent_router, "enqueue_agent_session_tick", queued.append)

    response = _client(monkeypatch).post(
        "/agent/sessions/session-1/block/resolve",
        json={"kind": "candidates", "allowance": 5},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ACTIVE"
    assert response.json()["block"] == {}
    assert seen["request"].allowance == 5
    assert queued == ["session-1"]


def test_policy_refusals_surface_a_safe_code(monkeypatch) -> None:
    class UseCase:
        def execute(self, request):
            raise AgentBlockPolicyError("BUDGET_CEILING_EXCEEDED")

    monkeypatch.setattr(agent_router, "get_resolve_agent_block_use_case", UseCase)

    response = _client(monkeypatch).post(
        "/agent/sessions/session-1/block/resolve",
        json={"kind": "budget", "additions": {"tokens": 10_000}},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "BUDGET_CEILING_EXCEEDED"}


def test_request_bounds_are_validated(monkeypatch) -> None:
    response = _client(monkeypatch).post(
        "/agent/sessions/session-1/block/resolve",
        json={"kind": "candidates", "allowance": 99},
    )

    assert response.status_code == 422


def test_memory_lists_supported_learnings_by_area(monkeypatch) -> None:
    class Insights:
        def list_by_scope(self, scope_key, status, limit=50):
            assert (scope_key, status) == (
                "area:model",
                OptimizerInsightStatus.SUPPORTED,
            )
            return [
                OptimizerInsight(
                    insight_id="i1",
                    statement="XGBoost mejora el recall",
                    kind=OptimizerInsightKind.PATTERN,
                    scope_key=scope_key,
                    status=status,
                    sample_count=120,
                    created_at=NOW,
                    last_evaluated_at=NOW,
                    review_after=NOW,
                    evidence_summary={"candidate_recall": 0.7},
                )
            ]

    monkeypatch.setattr(
        agent_router, "get_optimizer_insight_repository", lambda: Insights()
    )

    response = _client(monkeypatch).get("/agent/memory?area=model")

    assert response.status_code == 200
    assert response.json()[0]["sample_count"] == 120
    assert response.json()[0]["evidence_summary"] == {"candidate_recall": 0.7}


def test_failure_catalog_exposes_copy_and_required_approval(monkeypatch) -> None:
    response = _client(monkeypatch).get("/agent/failure-catalog")

    assert response.status_code == 200
    by_code = {item["code"]: item for item in response.json()}
    assert by_code["BUDGET_EXHAUSTED"]["approval"] == "budget"
    assert by_code["WORKER_LEASE_EXPIRED"]["retryable"] is True
    assert all(item["title"] and item["action"] for item in by_code.values())
