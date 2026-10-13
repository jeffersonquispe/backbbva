from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.use_cases.auth.local_auth import (
    ChangeLocalUserPasswordUseCase,
    GetCurrentLocalUserUseCase,
    ListLocalUsersUseCase,
    LogoutLocalUserUseCase,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.entrypoint.api.factories.local_auth_factory import (
    get_change_local_user_password_use_case,
    get_current_local_user_use_case,
    get_jwt_service,
    get_list_local_users_use_case,
    get_logout_local_user_use_case,
)
from src.infrastructure.entrypoint.api.routers.auth_router import router as auth_router
from src.infrastructure.security.local_auth import JwtService, PasswordHasher


class InMemoryUsers:
    def __init__(self, user: LocalUser):
        self.user = user

    def get_by_id(self, user_id):
        return self.user if user_id == self.user.id else None

    def update(self, user):
        self.user = user
        return user

    def list(self):
        return [self.user]


class InMemoryRevokedTokens:
    def __init__(self):
        self.revoked: dict = {}

    def revoke(self, token_id, expires_at):
        self.revoked[token_id] = expires_at

    def is_revoked(self, token_id):
        return token_id in self.revoked


def _user() -> LocalUser:
    now = datetime.now(UTC)
    return LocalUser(
        id=uuid4(), email="ana@aria.local", name="Ana", password_hash="x",
        role=LocalRole.FRAUD_ANALYST, is_active=True, created_at=now, updated_at=now,
    )


def _client(user: LocalUser, revoked: InMemoryRevokedTokens, jwt: JwtService) -> TestClient:
    app = FastAPI()
    app.include_router(auth_router)
    app.dependency_overrides[get_jwt_service] = lambda: jwt
    app.dependency_overrides[get_current_local_user_use_case] = (
        lambda: GetCurrentLocalUserUseCase(InMemoryUsers(user), revoked)
    )
    app.dependency_overrides[get_logout_local_user_use_case] = lambda: LogoutLocalUserUseCase(revoked)
    return TestClient(app)


def test_logout_ends_the_session_for_that_token_only() -> None:
    user = _user()
    revoked = InMemoryRevokedTokens()
    jwt = JwtService(secret="test-secret", ttl_seconds=60)
    client = _client(user, revoked, jwt)
    token, _ = jwt.issue(user)
    other_token, _ = jwt.issue(user)
    auth = {"Authorization": f"Bearer {token}"}

    assert client.get("/auth/me", headers=auth).status_code == 200
    assert client.post("/auth/logout", headers=auth).status_code == 204

    assert client.get("/auth/me", headers=auth).status_code == 401
    assert client.post("/auth/logout", headers=auth).status_code == 401
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {other_token}"}).status_code == 200
    assert list(revoked.revoked) == [jwt.decode(token)["jti"]]


def test_logout_requires_a_bearer_token() -> None:
    client = _client(_user(), InMemoryRevokedTokens(), JwtService(secret="test-secret", ttl_seconds=60))

    assert client.post("/auth/logout").status_code == 401


def _admin_client(users: InMemoryUsers, monkeypatch) -> TestClient:
    monkeypatch.setattr(genai_config, "AUTH_BOOTSTRAP_TOKEN", "boot")
    app = FastAPI()
    app.include_router(auth_router)
    app.dependency_overrides[get_list_local_users_use_case] = lambda: ListLocalUsersUseCase(users)
    app.dependency_overrides[get_change_local_user_password_use_case] = (
        lambda: ChangeLocalUserPasswordUseCase(users, PasswordHasher())
    )
    return TestClient(app)


def test_user_admin_endpoints_require_the_bootstrap_token(monkeypatch) -> None:
    user = _user()
    client = _admin_client(InMemoryUsers(user), monkeypatch)

    assert client.get("/auth/users").status_code == 403
    assert client.get("/auth/users", headers={"X-Bootstrap-Token": "wrong"}).status_code == 403
    assert client.put(f"/auth/users/{user.id}/password", json={"password": "new-password"}).status_code == 403


def test_list_users_and_change_password_with_the_bootstrap_token(monkeypatch) -> None:
    user = _user()
    users = InMemoryUsers(user)
    client = _admin_client(users, monkeypatch)
    headers = {"X-Bootstrap-Token": "boot"}

    listed = client.get("/auth/users", headers=headers)
    assert listed.status_code == 200
    assert [(u["email"], u["role"], u["is_active"]) for u in listed.json()] == [("ana@aria.local", "fraud_analyst", True)]
    assert "password_hash" not in listed.json()[0]

    changed = client.put(f"/auth/users/{user.id}/password", headers=headers, json={"password": "new-password"})
    assert changed.status_code == 200
    assert PasswordHasher().verify("new-password", users.user.password_hash)

    assert client.put(f"/auth/users/{uuid4()}/password", headers=headers, json={"password": "new-password"}).status_code == 404
    assert client.put(f"/auth/users/{user.id}/password", headers=headers, json={"password": "short"}).status_code == 422
