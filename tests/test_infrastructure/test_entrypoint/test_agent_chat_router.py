from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.ports.agent_chat_dispatcher_port import AgentChatDispatcher
from src.application.ports.agent_message_port import AgentMessage
from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.use_cases.agent.chat_with_agent import (
    AgentChatNotFoundError,
    AgentChatTurn,
    ChatWithAgentInput,
)
from src.infrastructure.entrypoint.api.routers import agent_router
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user

NOW = datetime(2026, 1, 1, tzinfo=UTC)
CLIENT_ID = "00000000-0000-0000-0000-000000000009"


def _message(role: str, client_message_id: str, seq: int, **extra) -> AgentMessage:
    return AgentMessage(
        session_id="session-1",
        client_message_id=client_message_id,
        message_id=f"m{seq}",
        seq=seq,
        role=role,
        content="hola" if role == "user" else "",
        author_id="owner",
        created_at=NOW,
        **extra,
    )


class RecordingChat:
    def __init__(self, turn: AgentChatTurn | None) -> None:
        self.turn = turn
        self.requests: list[ChatWithAgentInput] = []

    def accept(self, request: ChatWithAgentInput) -> AgentChatTurn:
        self.requests.append(request)
        if self.turn is None:
            raise AgentChatNotFoundError("session not found")
        return self.turn


class RecordingDispatcher(AgentChatDispatcher):
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict] = []
        self.fail = fail

    def dispatch(self, **kwargs) -> None:
        if self.fail:
            raise ConnectionError("broker down with secret-host")
        self.calls.append(kwargs)


def _client(monkeypatch, chat: RecordingChat, dispatcher: RecordingDispatcher):
    user = LocalUser(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        email="manager@example.com",
        name="Manager",
        password_hash="",
        role=LocalRole.MANAGER,
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )
    monkeypatch.setattr(agent_router, "get_chat_with_agent_use_case", lambda: chat)
    monkeypatch.setattr(agent_router, "get_agent_chat_dispatcher", lambda: dispatcher)
    app = FastAPI()
    app.include_router(agent_router.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


BODY = {"client_message_id": CLIENT_ID, "content": "hola", "page_path": "/biblioteca"}


def test_send_message_returns_202_and_queues_the_reply(monkeypatch) -> None:
    chat = RecordingChat(AgentChatTurn(_message("user", CLIENT_ID, 1), None))
    dispatcher = RecordingDispatcher()

    response = _client(monkeypatch, chat, dispatcher).post(
        "/agent/sessions/session-1/messages", json=BODY
    )

    assert response.status_code == 202
    assert response.json()["assistant_message"] is None
    assert response.json()["user_message"]["client_message_id"] == CLIENT_ID
    assert dispatcher.calls == [
        {
            "session_id": "session-1",
            "owner_id": "00000000-0000-0000-0000-000000000001",
            "client_message_id": CLIENT_ID,
            "page_path": "/biblioteca",
            "role": "manager",
        }
    ]


def test_retry_after_the_reply_exists_does_not_queue_again(monkeypatch) -> None:
    answered = _message("agent", f"{CLIENT_ID}:assistant", 2)
    chat = RecordingChat(AgentChatTurn(_message("user", CLIENT_ID, 1), answered))
    dispatcher = RecordingDispatcher()

    response = _client(monkeypatch, chat, dispatcher).post(
        "/agent/sessions/session-1/messages", json=BODY
    )

    assert response.status_code == 202
    assert response.json()["assistant_message"]["message_id"] == "m2"
    assert dispatcher.calls == []


def test_a_failed_turn_exposes_only_the_safe_error_code(monkeypatch) -> None:
    failed = _message(
        "agent", f"{CLIENT_ID}:assistant", 2, error_code="CHAT_UNAVAILABLE"
    )
    chat = RecordingChat(AgentChatTurn(_message("user", CLIENT_ID, 1), failed))

    response = _client(monkeypatch, chat, RecordingDispatcher()).post(
        "/agent/sessions/session-1/messages", json=BODY
    )

    assert response.json()["assistant_message"]["error_code"] == "CHAT_UNAVAILABLE"
    assert response.json()["assistant_message"]["content"] == ""


def test_unknown_session_is_404_and_nothing_is_queued(monkeypatch) -> None:
    dispatcher = RecordingDispatcher()

    response = _client(monkeypatch, RecordingChat(None), dispatcher).post(
        "/agent/sessions/session-1/messages", json=BODY
    )

    assert response.status_code == 404
    assert dispatcher.calls == []


def test_broker_failure_is_a_generic_503_without_internal_details(monkeypatch) -> None:
    chat = RecordingChat(AgentChatTurn(_message("user", CLIENT_ID, 1), None))

    response = _client(monkeypatch, chat, RecordingDispatcher(fail=True)).post(
        "/agent/sessions/session-1/messages", json=BODY
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {"code": "CHAT_UNAVAILABLE"}
