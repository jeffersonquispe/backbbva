from __future__ import annotations

from src.application.ports.local_auth_port import LocalRole
from src.application.use_cases.auth.local_auth import (
    AuthenticateLocalUserUseCase,
    RegisterLocalUserUseCase,
    permissions_for,
)
from src.infrastructure.security.local_auth import JwtService, PasswordHasher


class InMemoryUsers:
    def __init__(self):
        self.by_email = {}
        self.by_id = {}

    def get_by_email(self, email):
        return self.by_email.get(email)

    def get_by_id(self, user_id):
        return self.by_id.get(user_id)

    def create(self, user):
        self.by_email[user.email] = user
        self.by_id[user.id] = user
        return user


def test_local_login_returns_signed_token_and_fixed_permissions():
    users = InMemoryUsers()
    hasher = PasswordHasher()
    registered = RegisterLocalUserUseCase(users, hasher).execute(
        email="manager@aria.local", name="Manager", password="safe-password", role=LocalRole.MANAGER,
    )
    service = JwtService(secret="test-secret", ttl_seconds=60)
    result = AuthenticateLocalUserUseCase(users, hasher, service).execute(
        email=registered.email, password="safe-password",
    )

    assert service.decode(result.access_token)["sub"] == str(registered.id)
    assert permissions_for(registered.role) == [
        "configuration", "dashboard", "fraud_history", "in_progress", "monitor",
    ]


def test_channel_manager_is_the_only_role_with_every_frontend_permission():
    assert len(permissions_for(LocalRole.CHANNEL_MANAGER)) == 8
    assert permissions_for(LocalRole.FRAUD_ANALYST) == ["in_progress"]
