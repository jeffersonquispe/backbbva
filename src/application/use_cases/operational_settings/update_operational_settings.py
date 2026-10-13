from __future__ import annotations

import dataclasses
from dataclasses import asdict
from typing import Any

from src.application.dtos.operational_settings_dtos import (
    UpdateOperationalSettingsInput,
)
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.operational_settings_port import (
    OperationalSettings,
    OperationalSettingsChange,
    OperationalSettingsRepository,
    SettingChange,
)
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)
from src.domain.alerts.amount_tiers import validate_amount_tiers


class UpdateOperationalSettingsUseCase:
    def __init__(
        self,
        repository: OperationalSettingsRepository,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._repository = repository
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(self, input: UpdateOperationalSettingsInput) -> OperationalSettings:
        current = self._repository.get()
        proposed = input.settings
        if input.preserve_amount_tiers:
            proposed = dataclasses.replace(proposed, amount_tiers=current.amount_tiers)
        # Raises InvalidAmountTiersError (-> 422 at the router).
        validate_amount_tiers(proposed.amount_tiers)
        changes = _diff(asdict(current), asdict(proposed))
        change = OperationalSettingsChange(
            id=str(self._id_generator.new_id()),
            changed_by=input.changed_by,
            changed_at=self._clock.now(),
            changes=changes,
        )
        return self._repository.update(proposed, change)


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
