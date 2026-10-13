from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from src.application.errors import ConflictError, ForbiddenError, NotFoundError
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.local_auth_port import (
    ROLE_PERMISSIONS,
    LocalRole,
    LocalUser,
    LocalUserRepository,
)
from src.application.ports.revoked_token_port import RevokedTokenRepository
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)


class InvalidCredentialsError(ForbiddenError):
    pass


class DuplicateEmailError(ConflictError):
    pass


class LocalUserNotFoundError(NotFoundError):
    pass


@dataclass(frozen=True)
class AuthenticatedUser:
    user: LocalUser
    access_token: str
    expires_in: int


class RegisterLocalUserUseCase:
    def __init__(
        self,
        users: LocalUserRepository,
        password_hasher,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._users = users
        self._password_hasher = password_hasher
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(
        self, *, email: str, name: str, password: str, role: LocalRole
    ) -> LocalUser:
        email = email.strip().lower()
        if self._users.get_by_email(email):
            raise DuplicateEmailError("A user with this email already exists")
        now = self._clock.now()
        return self._users.create(
            LocalUser(
                id=self._id_generator.new_id(),
                email=email,
                name=name.strip(),
                password_hash=self._password_hasher.hash(password),
                role=role,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )


class ListLocalUsersUseCase:
    def __init__(self, users: LocalUserRepository) -> None:
        self._users = users

    def execute(self) -> list[LocalUser]:
        return sorted(self._users.list(), key=lambda user: user.email)


class ChangeLocalUserPasswordUseCase:
    def __init__(
        self, users: LocalUserRepository, password_hasher, clock: Clock | None = None
    ) -> None:
        self._users = users
        self._password_hasher = password_hasher
        self._clock = resolve_clock(clock)

    def execute(self, *, user_id: UUID, password: str) -> LocalUser:
        user = self._users.get_by_id(user_id)
        if not user:
            raise LocalUserNotFoundError("User not found")
        return self._users.update(
            replace(
                user,
                password_hash=self._password_hasher.hash(password),
                updated_at=self._clock.now(),
            )
        )


class AuthenticateLocalUserUseCase:
    def __init__(
        self, users: LocalUserRepository, password_hasher, token_service
    ) -> None:
        self._users = users
        self._password_hasher = password_hasher
        self._token_service = token_service

    def execute(self, *, email: str, password: str) -> AuthenticatedUser:
        user = self._users.get_by_email(email.strip().lower())
        if (
            not user
            or not user.is_active
            or not self._password_hasher.verify(password, user.password_hash)
        ):
            raise InvalidCredentialsError("Invalid email or password")
        token, expires_in = self._token_service.issue(user)
        return AuthenticatedUser(user=user, access_token=token, expires_in=expires_in)


class GetCurrentLocalUserUseCase:
    def __init__(
        self,
        users: LocalUserRepository,
        revoked_tokens: RevokedTokenRepository | None = None,
    ) -> None:
        self._users = users
        self._revoked_tokens = revoked_tokens

    def execute(self, user_id, token_id: str | None = None) -> LocalUser | None:
        """Resolve the user behind a request. With ``token_id`` (the access
        token's jti), a token ended by logout resolves to no user."""
        if (
            token_id
            and self._revoked_tokens is not None
            and self._revoked_tokens.is_revoked(token_id)
        ):
            return None
        return self._users.get_by_id(user_id)


class LogoutLocalUserUseCase:
    def __init__(self, revoked_tokens: RevokedTokenRepository) -> None:
        self._revoked_tokens = revoked_tokens

    def execute(self, *, token_id: str | None, expires_at: datetime) -> None:
        # Tokens issued before jti existed can't be denylisted; they simply
        # run out at their exp (AUTH_JWT_TTL_SECONDS).
        if token_id:
            self._revoked_tokens.revoke(token_id, expires_at)


def permissions_for(role: LocalRole) -> list[str]:
    return sorted(ROLE_PERMISSIONS[role])
