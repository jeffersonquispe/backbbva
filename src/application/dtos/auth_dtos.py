from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID


@dataclass
class OAuthCallbackInput:
    code: str
    redirect_uri: str


@dataclass
class AuthSessionOutput:
    session_token: str
    user_id: str          # UUID as str
    email: str
    name: str
    organization_id: str  # UUID as str


@dataclass
class LogoutInput:
    session_token: str


@dataclass
class GetCurrentUserInput:
    session_token: str


@dataclass
class UserOutput:
    id: UUID
    email: str
    name: str
    given_name: Optional[str]
    avatar_url: Optional[str]
    auth_provider: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
