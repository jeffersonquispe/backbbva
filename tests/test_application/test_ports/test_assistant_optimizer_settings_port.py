from dataclasses import replace

from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettings,
    AssistantOptimizerSettingsPort,
)


class InMemoryAssistantOptimizerSettingsPort(AssistantOptimizerSettingsPort):
    def __init__(self, settings: AssistantOptimizerSettings | None = None) -> None:
        self.settings = settings or AssistantOptimizerSettings()

    def get(self) -> AssistantOptimizerSettings:
        return self.settings

    def update(
        self, settings: AssistantOptimizerSettings
    ) -> AssistantOptimizerSettings:
        self.settings = settings
        return self.settings


def test_in_memory_settings_port_reads_and_updates_settings() -> None:
    port = InMemoryAssistantOptimizerSettingsPort()
    assert port.get().optimizer_enabled is False
    assert port.get().optimizer_session_budget_ceiling_usd == 50.0
    assert port.get().optimizer_session_budget_ceiling_seconds == 43_200

    updated = replace(port.get(), assistant_max_message_chars=4_000)

    assert port.update(updated) == updated
    assert port.get().assistant_max_message_chars == 4_000
