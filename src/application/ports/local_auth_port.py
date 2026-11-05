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
    FRAUD_REVIEWER = "fraud_reviewer"


# fraud_archive: read an alert older than the hot window back from the cold
# archive (GET /fraud-history/archive/{id}). legal_hold: place/release holds
# that keep alerts out of (or protect them in) that archive; manager only until
# a compliance role exists - granting it there is one line below.
ROLE_PERMISSIONS: dict[LocalRole, frozenset[str]] = {
    # fraud_review: correct an alert's fraud_label (POST /alerts/{id}/fraud-review
    # and the bulk CSV) - the ground truth that trains models and scores the
    # optimizer. Held by the fraud team's fraud_reviewer, with manager as
    # backup; never by channel_manager (launches the optimizer, so it would
    # grade its own results) nor fraud_analyst (sets the mark it would grade).
    LocalRole.MANAGER: frozenset(
        {
            "dashboard",
            "in_progress",
            "fraud_history",
            "fraud_review",
            "fraud_archive",
            "legal_hold",
            "monitor",
            "configuration",
            "library",
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
    LocalRole.FRAUD_REVIEWER: frozenset(
        {"fraud_history", "fraud_review", "fraud_archive"}
    ),
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
