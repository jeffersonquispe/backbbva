from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class LocalRole(StrEnum):
    MANAGER = "manager"
    CHANNEL_MANAGER = "channel_manager"
    RELEASE_MANAGER = "release_manager"
    DATA_ANALYST = "data_analyst"
    FRAUD_ANALYST = "fraud_analyst"
    OPS_ANALYST = "ops_analyst"


ROLE_PERMISSIONS: dict[LocalRole, frozenset[str]] = {
    # fraud_review: correct an alert's fraud_label (POST /alerts/{id}/fraud-review
    # and the bulk CSV) - a bank business record: manager, plus
    # channel_manager, which by design holds every frontend permission.
    LocalRole.MANAGER: frozenset(
        {
            "dashboard",
            "in_progress",
            "fraud_history",
            "fraud_review",
            "monitor",
            "configuration",
            "alert_schema",
        }
    ),
    LocalRole.RELEASE_MANAGER: frozenset(
        {
            "dashboard",
            "in_progress",
            "fraud_history",
            "monitor",
            "configuration",
            "testing",
            "alert_schema",
        }
    ),
    LocalRole.CHANNEL_MANAGER: frozenset(
        {
            "dashboard",
            "in_progress",
            "fraud_history",
            "fraud_review",
            "monitor",
            "configuration",
            "testing",
            "library",
            "models",
        }
    ),
    LocalRole.DATA_ANALYST: frozenset({"monitor", "library", "testing", "models"}),
    LocalRole.FRAUD_ANALYST: frozenset({"in_progress"}),
    LocalRole.OPS_ANALYST: frozenset({"dashboard", "in_progress", "monitor"}),
}


@dataclass(frozen=True)
class LocalUser:
    id: UUID
    email: str
    name: str
    password_hash: str
    role: LocalRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LocalUserRepository(Protocol):
    def get_by_email(self, email: str) -> LocalUser | None: ...
    def get_by_id(self, user_id: UUID) -> LocalUser | None: ...
    def create(self, user: LocalUser) -> LocalUser: ...
    def update(self, user: LocalUser) -> LocalUser: ...
    def list(self) -> list[LocalUser]: ...
