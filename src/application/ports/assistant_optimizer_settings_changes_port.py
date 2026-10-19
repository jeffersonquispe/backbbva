from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AssistantOptimizerSettingChange:
    path: str
    previous: Any
    new: Any


@dataclass(frozen=True)
class AssistantOptimizerSettingsChange:
    id: str
    changed_by: str
    changed_at: datetime
    changes: list[AssistantOptimizerSettingChange]


class AssistantOptimizerSettingsChangesPort(ABC):
    """Append and list the audit history for assistant optimizer settings."""

    @abstractmethod
    def append(self, change: AssistantOptimizerSettingsChange) -> None:
        raise NotImplementedError

    @abstractmethod
    def list(self, limit: int = 50) -> list[AssistantOptimizerSettingsChange]:
        raise NotImplementedError
