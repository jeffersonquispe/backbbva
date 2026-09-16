from __future__ import annotations

from dataclasses import dataclass

from src.application.ports.operational_settings_port import OperationalSettings


@dataclass
class UpdateOperationalSettingsInput:
    settings: OperationalSettings
    # Free-text identifier captured for traceability only - this codebase
    # has no auth/permission system wired anywhere (see AUDIT_FINDINGS.md),
    # so this is not an enforced/verified identity.
    changed_by: str | None = None
