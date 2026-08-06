from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Optional, Protocol
from uuid import UUID


class OrganizationRole(StrEnum):
    ADMIN = "admin"


@dataclass
class OAuthTokens:
    access_token: str
    id_token: str
    refresh_token: Optional[str]
    expires_in: int


@dataclass
class UserIdentityInfo:
    sub: str
    email: str
    name: str
    given_name: Optional[str]
    picture: Optional[str]
    provider: str


@dataclass
class UserRecord:
    id: UUID
    cognito_sub: str
    email: str
    name: str
    given_name: Optional[str]
    avatar_url: Optional[str]
    auth_provider: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by: Optional[UUID] = None
    updated_by: Optional[UUID] = None


@dataclass
class OrganizationRecord:
    id: UUID
    name: str
    active: bool
    created_at: datetime
    updated_at: datetime
    created_by: Optional[UUID] = None
    updated_by: Optional[UUID] = None


@dataclass
class UserOrganizationRecord:
    id: UUID
    user_id: UUID
    organization_id: UUID
    organization_name: str
    role: OrganizationRole
    created_at: datetime
    updated_at: datetime
    created_by: Optional[UUID] = None
    updated_by: Optional[UUID] = None


@dataclass
class SessionRecord:
    id: UUID
    user_id: UUID
    session_token: str
    expires_at: datetime
    created_at: datetime
    updated_at: datetime

    def is_expired(self) -> bool:
        return self.expires_at <= datetime.utcnow()


class IdentityPort(Protocol):
    def exchange_code_for_tokens(self, code: str, redirect_uri: str) -> OAuthTokens: ...

    def decode_id_token(self, id_token: str) -> UserIdentityInfo: ...

    def create_organization_groups(self, organization_id: str) -> list[str]: ...


class AuthStoragePort(Protocol):
    def create_directory(self, path: str) -> None: ...


class UserRepository(Protocol):
    def get_by_id(self, user_id: UUID) -> Optional[UserRecord]: ...

    def get_by_cognito_sub(self, cognito_sub: str) -> Optional[UserRecord]: ...

    def create(self, user: UserRecord) -> UserRecord: ...


class OrganizationRepository(Protocol):
    def get_by_id(self, organization_id: UUID) -> Optional[OrganizationRecord]: ...

    def create(self, organization: OrganizationRecord) -> OrganizationRecord: ...


class UserOrganizationRepository(Protocol):
    def list_by_user(self, user_id: UUID) -> list[UserOrganizationRecord]: ...

    def create(self, user_organization: UserOrganizationRecord) -> UserOrganizationRecord: ...


class SessionRepository(Protocol):
    def get_by_token(self, session_token: str) -> Optional[SessionRecord]: ...

    def create(self, session: SessionRecord) -> SessionRecord: ...

    def delete_by_token(self, session_token: str) -> None: ...
