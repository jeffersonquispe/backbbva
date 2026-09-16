from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from src.application.ports.local_auth_port import (
    ROLE_PERMISSIONS,
    LocalRole,
    LocalUser,
    LocalUserRepository,
)


class InvalidCredentialsError(Exception):
    pass


class DuplicateEmailError(Exception):
    pass


@dataclass(frozen=True)
class AuthenticatedUser:
    user: LocalUser
    access_token: str
    expires_in: int


class RegisterLocalUserUseCase:
    def __init__(self, users: LocalUserRepository, password_hasher) -> None:
        self._users = users
        self._password_hasher = password_hasher

    def execute(self, *, email: str, name: str, password: str, role: LocalRole) -> LocalUser:
        email = email.strip().lower()
        if self._users.get_by_email(email):
            raise DuplicateEmailError("A user with this email already exists")
        now = datetime.now(timezone.utc)
        return self._users.create(LocalUser(
            id=uuid4(), email=email, name=name.strip(),
            password_hash=self._password_hasher.hash(password), role=role,
            is_active=True, created_at=now, updated_at=now,
        ))


class AuthenticateLocalUserUseCase:
    def __init__(self, users: LocalUserRepository, password_hasher, token_service) -> None:
        self._users = users
        self._password_hasher = password_hasher
        self._token_service = token_service

    def execute(self, *, email: str, password: str) -> AuthenticatedUser:
        user = self._users.get_by_email(email.strip().lower())
        if not user or not user.is_active or not self._password_hasher.verify(password, user.password_hash):
            raise InvalidCredentialsError("Invalid email or password")
        token, expires_in = self._token_service.issue(user)
        return AuthenticatedUser(user=user, access_token=token, expires_in=expires_in)


class GetCurrentLocalUserUseCase:
    def __init__(self, users: LocalUserRepository) -> None:
        self._users = users

    def execute(self, user_id) -> LocalUser | None:
        return self._users.get_by_id(user_id)


def permissions_for(role: LocalRole) -> list[str]:
    return sorted(ROLE_PERMISSIONS[role])
