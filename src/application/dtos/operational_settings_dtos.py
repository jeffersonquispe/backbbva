from __future__ import annotations

from dataclasses import dataclass

from src.application.ports.operational_settings_port import OperationalSettings


@dataclass
class UpdateOperationalSettingsInput:
    settings: OperationalSettings
    # Free-text identifier captured for traceability only - this codebase
    # has no auth/permission system wired anywhere,
    # so this is not an enforced/verified identity.
    changed_by: str | None = None
    # True when the caller didn't send amount_tiers at all (e.g. a client
    # that predates them) - the current tiers are kept instead of being
    # wiped by the empty default.
    preserve_amount_tiers: bool = False
