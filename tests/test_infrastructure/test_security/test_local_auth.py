from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.application.ports.local_auth_port import LocalRole
from src.application.use_cases.auth.local_auth import (
    AuthenticateLocalUserUseCase,
    ChangeLocalUserPasswordUseCase,
    GetCurrentLocalUserUseCase,
    InvalidCredentialsError,
    ListLocalUsersUseCase,
    LocalUserNotFoundError,
    LogoutLocalUserUseCase,
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

    def update(self, user):
        return self.create(user)

    def list(self):
        return list(self.by_id.values())


def test_local_login_returns_signed_token_and_fixed_permissions():
    users = InMemoryUsers()
    hasher = PasswordHasher()
    registered = RegisterLocalUserUseCase(users, hasher).execute(
        email="manager@aria.local",
        name="Manager",
        password="safe-password",
        role=LocalRole.MANAGER,
    )
    service = JwtService(secret="test-secret", ttl_seconds=60)
    result = AuthenticateLocalUserUseCase(users, hasher, service).execute(
        email=registered.email,
        password="safe-password",
    )

    assert service.decode(result.access_token)["sub"] == str(registered.id)
    assert permissions_for(registered.role) == [
        "alert_schema",
        "configuration",
        "dashboard",
        "fraud_archive",
        "fraud_history",
        "fraud_review",
        "in_progress",
        "legal_hold",
        "library",
        "monitor",
    ]


def test_channel_manager_holds_every_frontend_permission_but_fraud_review():
    assert len(permissions_for(LocalRole.CHANNEL_MANAGER)) == 8
    assert "fraud_review" not in permissions_for(LocalRole.CHANNEL_MANAGER)
    assert permissions_for(LocalRole.FRAUD_ANALYST) == ["in_progress"]


def test_only_fraud_reviewer_and_manager_may_correct_fraud_labels():
    assert {
        role for role in LocalRole if "fraud_review" in permissions_for(role)
    } == {LocalRole.FRAUD_REVIEWER, LocalRole.MANAGER}
    assert permissions_for(LocalRole.FRAUD_REVIEWER) == [
        "fraud_archive",
        "fraud_history",
        "fraud_review",
    ]


def test_cold_archive_is_read_by_manager_and_reviewer_but_only_manager_holds():
    assert {
        role for role in LocalRole if "fraud_archive" in permissions_for(role)
    } == {LocalRole.FRAUD_REVIEWER, LocalRole.MANAGER}
    assert {role for role in LocalRole if "legal_hold" in permissions_for(role)} == {
        LocalRole.MANAGER
    }


class InMemoryRevokedTokens:
    def __init__(self):
        self.revoked = {}

    def revoke(self, token_id, expires_at):
        self.revoked[token_id] = expires_at

    def is_revoked(self, token_id):
        return token_id in self.revoked


def test_logout_revokes_the_token_so_it_no_longer_resolves_a_user():
    users = InMemoryUsers()
    hasher = PasswordHasher()
    registered = RegisterLocalUserUseCase(users, hasher).execute(
        email="ana@aria.local",
        name="Ana",
        password="safe-password",
        role=LocalRole.FRAUD_ANALYST,
    )
    service = JwtService(secret="test-secret", ttl_seconds=60)
    first = service.decode(
        AuthenticateLocalUserUseCase(users, hasher, service)
        .execute(email=registered.email, password="safe-password")
        .access_token
    )
    second = service.decode(
        AuthenticateLocalUserUseCase(users, hasher, service)
        .execute(email=registered.email, password="safe-password")
        .access_token
    )
    revoked = InMemoryRevokedTokens()
    current = GetCurrentLocalUserUseCase(users, revoked)

    LogoutLocalUserUseCase(revoked).execute(
        token_id=first["jti"],
        expires_at=datetime.fromtimestamp(first["exp"], UTC),
    )

    assert current.execute(registered.id, token_id=first["jti"]) is None
    # Logout ends that session only - another login (other tab/device) stays valid.
    assert current.execute(registered.id, token_id=second["jti"]) == registered
    assert revoked.revoked[first["jti"]] == datetime.fromtimestamp(first["exp"], UTC)


def test_logout_of_a_legacy_token_without_jti_is_a_no_op():
    revoked = InMemoryRevokedTokens()

    LogoutLocalUserUseCase(revoked).execute(token_id=None, expires_at=datetime.now(UTC))

    assert revoked.revoked == {}


def test_list_local_users_is_sorted_by_email():
    users = InMemoryUsers()
    register = RegisterLocalUserUseCase(users, PasswordHasher())
    for email in ("zoe@aria.local", "ana@aria.local"):
        register.execute(
            email=email, name="X", password="safe-password", role=LocalRole.OPS_ANALYST
        )

    assert [user.email for user in ListLocalUsersUseCase(users).execute()] == [
        "ana@aria.local",
        "zoe@aria.local",
    ]


def test_change_password_replaces_the_old_one():
    users = InMemoryUsers()
    hasher = PasswordHasher()
    registered = RegisterLocalUserUseCase(users, hasher).execute(
        email="ana@aria.local",
        name="Ana",
        password="old-password",
        role=LocalRole.FRAUD_ANALYST,
    )
    login = AuthenticateLocalUserUseCase(
        users, hasher, JwtService(secret="test-secret", ttl_seconds=60)
    )

    updated = ChangeLocalUserPasswordUseCase(users, hasher).execute(
        user_id=registered.id, password="new-password"
    )

    assert updated.id == registered.id and updated.updated_at >= registered.updated_at
    assert (
        login.execute(email="ana@aria.local", password="new-password").user.id
        == registered.id
    )
    with pytest.raises(InvalidCredentialsError):
        login.execute(email="ana@aria.local", password="old-password")


def test_change_password_of_an_unknown_user_fails():
    with pytest.raises(LocalUserNotFoundError):
        ChangeLocalUserPasswordUseCase(InMemoryUsers(), PasswordHasher()).execute(
            user_id=uuid4(), password="new-password"
        )
