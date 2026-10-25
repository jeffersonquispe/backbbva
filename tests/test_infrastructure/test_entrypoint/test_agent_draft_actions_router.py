from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.infrastructure.entrypoint.api.routers import (
    agent_draft_actions_router,
    agent_flag_draft_router,
    agent_modus_operandi_draft_router,
    agent_similar_case_draft_router,
    agent_taxonomy_draft_router,
    agent_watchlist_draft_router,
)
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user

NOW = datetime(2026, 10, 25, tzinfo=UTC)


def _client(role: LocalRole) -> TestClient:
    app = FastAPI()
    app.include_router(agent_draft_actions_router.router)
    user = LocalUser(
        id=uuid4(),
        email="user@aria.test",
        name="Test user",
        password_hash="",
        role=role,
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_draft_actions_are_filtered_by_authenticated_role() -> None:
    manager = _client(LocalRole.MANAGER).get("/agent/draft-actions").json()
    channel_manager = (
        _client(LocalRole.CHANNEL_MANAGER).get("/agent/draft-actions").json()
    )

    assert {action["action_id"] for action in manager} == {
        "taxonomy",
        "modus_operandi",
        "flag",
        "similar_case",
        "watchlist",
    }
    assert channel_manager == manager
    assert all(
        action["required_permissions"] == ["configuration", "library"]
        for action in manager
    )


def test_roles_without_both_agent_and_library_permissions_get_no_draft_actions() -> (
    None
):
    for role in (
        LocalRole.RELEASE_MANAGER,
        LocalRole.DATA_ANALYST,
        LocalRole.FRAUD_ANALYST,
        LocalRole.OPS_ANALYST,
    ):
        response = _client(role).get(
            "/agent/draft-actions", params={"role": "channel_manager"}
        )
        assert response.status_code == 200
        assert response.json() == []


def test_action_contract_declares_read_context_and_validated_fields() -> None:
    actions = _client(LocalRole.MANAGER).get("/agent/draft-actions").json()
    by_id = {action["action_id"]: action for action in actions}

    assert by_id["similar_case"]["context"] == [
        "similar_case_schema",
        "modus_operandi_entries",
        "taxonomies",
    ]
    assert by_id["watchlist"]["fields"] == ["name", "description", "list_type"]
    assert by_id["watchlist"]["operations"] == ["create", "update"]


def test_unlisted_roles_cannot_call_any_draft_generation_endpoint() -> None:
    draft_routers = (
        (agent_taxonomy_draft_router.router, "taxonomy-drafts"),
        (agent_modus_operandi_draft_router.router, "modus-operandi-drafts"),
        (agent_flag_draft_router.router, "flag-drafts"),
        (agent_similar_case_draft_router.router, "similar-case-drafts"),
        (agent_watchlist_draft_router.router, "watchlist-drafts"),
    )
    for role in (LocalRole.RELEASE_MANAGER, LocalRole.DATA_ANALYST):
        app = FastAPI()
        for router, _ in draft_routers:
            app.include_router(router)
        user = LocalUser(
            id=uuid4(),
            email="user@aria.test",
            name="Test user",
            password_hash="",
            role=role,
            is_active=True,
            created_at=NOW,
            updated_at=NOW,
        )
        app.dependency_overrides[get_current_user] = lambda user=user: user
        client = TestClient(app)
        for _, endpoint in draft_routers:
            response = client.post(
                f"/agent/sessions/not-a-real-session/{endpoint}",
                json={
                    "client_message_id": "role-spoof-test",
                    "operation": "create",
                    "role": "channel_manager",
                },
            )
            assert response.status_code == 403
