from __future__ import annotations

from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettings,
    AssistantOptimizerSettingsPort,
)
from src.application.use_cases.agent.get_optimizer_launch_limits import (
    GetOptimizerLaunchLimitsUseCase,
)


class InMemorySettings(AssistantOptimizerSettingsPort):
    def __init__(self, settings: AssistantOptimizerSettings) -> None:
        self._settings = settings

    def get(self) -> AssistantOptimizerSettings:
        return self._settings

    def update(
        self, settings: AssistantOptimizerSettings
    ) -> AssistantOptimizerSettings:
        self._settings = settings
        return settings


def test_launch_limits_mirror_what_session_creation_enforces() -> None:
    limits = GetOptimizerLaunchLimitsUseCase(
        settings=InMemorySettings(
            AssistantOptimizerSettings(
                optimizer_enabled=True,
                optimizer_max_concurrent_sessions=3,
                optimizer_session_budget_ceiling_tokens=200_000,
                optimizer_session_budget_ceiling_usd=12.5,
                optimizer_session_budget_ceiling_seconds=3_600,
            )
        )
    ).execute()

    assert limits.enabled is True
    assert limits.max_concurrent_sessions == 3
    assert limits.budget_ceiling == {
        "tokens": 200_000,
        "usd_micros": 12_500_000,
        "seconds": 3_600,
    }


def test_launch_limits_report_a_disabled_optimizer() -> None:
    limits = GetOptimizerLaunchLimitsUseCase(
        settings=InMemorySettings(AssistantOptimizerSettings(optimizer_enabled=False))
    ).execute()

    assert limits.enabled is False
