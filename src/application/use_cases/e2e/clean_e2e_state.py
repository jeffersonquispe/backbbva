from __future__ import annotations

from src.application.ports.e2e_state_cleaner_port import (
    E2EStateCleaner,
    E2EStateCleanResult,
)


class CleanE2EStateUseCase:
    """Reset application data between real E2E runs. Whether the operation is
    allowed in the current environment is an entrypoint decision."""

    def __init__(self, cleaner: E2EStateCleaner) -> None:
        self._cleaner = cleaner

    def execute(self) -> E2EStateCleanResult:
        return self._cleaner.clean()
