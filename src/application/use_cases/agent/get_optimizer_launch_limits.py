"""What a Channel Manager needs to know before launching an optimizer session."""

from __future__ import annotations

from dataclasses import dataclass

from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettingsPort,
)


@dataclass(frozen=True)
class OptimizerLaunchLimits:
    enabled: bool
    max_concurrent_sessions: int
    # Same keys and units as `AgentSession.budget_limits` (usd in micros).
    budget_ceiling: dict[str, int]


class GetOptimizerLaunchLimitsUseCase:
    def __init__(self, *, settings: AssistantOptimizerSettingsPort) -> None:
        self._settings = settings

    def execute(self) -> OptimizerLaunchLimits:
        settings = self._settings.get()
        return OptimizerLaunchLimits(
            enabled=settings.optimizer_enabled,
            max_concurrent_sessions=settings.optimizer_max_concurrent_sessions,
            budget_ceiling={
                "tokens": settings.optimizer_session_budget_ceiling_tokens,
                "usd_micros": int(
                    settings.optimizer_session_budget_ceiling_usd * 1_000_000
                ),
                "seconds": settings.optimizer_session_budget_ceiling_seconds,
            },
        )
