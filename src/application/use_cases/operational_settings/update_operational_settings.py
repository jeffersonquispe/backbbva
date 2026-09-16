from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from src.application.dtos.operational_settings_dtos import (
    UpdateOperationalSettingsInput,
)
from src.application.ports.operational_settings_port import (
    OperationalSettings,
    OperationalSettingsChange,
    OperationalSettingsRepository,
    SettingChange,
)


class UpdateOperationalSettingsUseCase:
    def __init__(self, repository: OperationalSettingsRepository) -> None:
        self._repository = repository

    def execute(self, input: UpdateOperationalSettingsInput) -> OperationalSettings:
        current = self._repository.get()
        changes = _diff(asdict(current), asdict(input.settings))
        change = OperationalSettingsChange(
            id=str(uuid.uuid4()),
            changed_by=input.changed_by,
            changed_at=datetime.now(timezone.utc),
            changes=changes,
        )
        return self._repository.update(input.settings, change)


def _diff(previous: Any, proposed: Any, path: str = "") -> list[SettingChange]:
    # Adapted from PreviewConfigurationUseCase._diff
    # (use_cases/configurations/test_configuration.py) - same recursive
    # dict-diff shape. Kept local rather than shared: both sides always
    # have the exact same keys here (both built via asdict() of the same
    # OperationalSettings dataclass), so the missing-key branches that
    # version diffs across differently-shaped ConfigurationRecords need
    # don't apply.
    if isinstance(previous, dict) and isinstance(proposed, dict):
        changes: list[SettingChange] = []
        for key in sorted(previous.keys() | proposed.keys()):
            child_path = f"{path}.{key}" if path else str(key)
            changes.extend(_diff(previous.get(key), proposed.get(key), child_path))
        return changes
    if previous != proposed:
        return [SettingChange(path, previous, proposed)]
    return []
