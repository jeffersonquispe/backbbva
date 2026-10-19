from dataclasses import replace

import pytest

from src.application.errors import ValidationError
from src.application.ports.assistant_optimizer_settings_changes_port import (
    AssistantOptimizerSettingsChange,
    AssistantOptimizerSettingsChangesPort,
)
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettings,
    AssistantOptimizerSettingsPort,
)
from src.application.ports.audit_port import AuditEntry, AuditPort
from src.application.use_cases.assistant_optimizer_settings import (
    GetAssistantOptimizerSettingsUseCase,
    ListAssistantOptimizerSettingsChangesUseCase,
    UpdateAssistantOptimizerSettingsUseCase,
)


class InMemorySettingsPort(AssistantOptimizerSettingsPort):
    def __init__(self) -> None:
        self.settings = AssistantOptimizerSettings()

    def get(self) -> AssistantOptimizerSettings:
        return self.settings

    def update(self, settings: AssistantOptimizerSettings) -> AssistantOptimizerSettings:
        self.settings = settings
        return settings


class InMemoryChangesPort(AssistantOptimizerSettingsChangesPort):
    def __init__(self) -> None:
        self.changes: list[AssistantOptimizerSettingsChange] = []

    def append(self, change: AssistantOptimizerSettingsChange) -> None:
        self.changes.append(change)

    def list(self, limit: int = 50) -> list[AssistantOptimizerSettingsChange]:
        return list(reversed(self.changes))[:limit]


class InMemoryAuditPort(AuditPort):
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def write(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


def _use_case(settings, changes, audit):
    return UpdateAssistantOptimizerSettingsUseCase(settings, changes, audit)


def test_get_returns_current_singleton_with_maturity_fields_at_contract_defaults() -> None:
    repository = InMemorySettingsPort()
    assert GetAssistantOptimizerSettingsUseCase(repository).execute() == repository.get()


def test_update_records_diff_and_audits_authenticated_author() -> None:
    settings = InMemorySettingsPort()
    changes = InMemoryChangesPort()
    audit = InMemoryAuditPort()
    updated = replace(settings.get(), assistant_max_message_chars=4_000)

    result = _use_case(settings, changes, audit).execute(updated, "manager@example.com")

    assert result.assistant_max_message_chars == 4_000
    assert [(change.path, change.previous, change.new) for change in changes.changes[0].changes] == [
        ("assistant_max_message_chars", 8_000, 4_000)
    ]
    assert changes.changes[0].changed_by == "manager@example.com"
    assert audit.entries[0].action == "assistant_optimizer_settings.update"
    assert audit.entries[0].actor_id == "manager@example.com"


def test_update_rejects_out_of_range_values_without_writing() -> None:
    settings = InMemorySettingsPort()
    changes = InMemoryChangesPort()
    audit = InMemoryAuditPort()

    with pytest.raises(ValidationError, match="assistant_max_message_chars"):
        _use_case(settings, changes, audit).execute(
            replace(settings.get(), assistant_max_message_chars=8_001),
            "manager@example.com",
        )

    assert settings.get().assistant_max_message_chars == 8_000
    assert changes.changes == []
    assert audit.entries == []


def test_update_rejects_incoherent_sampling_partitions() -> None:
    settings = InMemorySettingsPort()

    with pytest.raises(ValidationError, match="deben sumar 1"):
        _use_case(settings, InMemoryChangesPort(), InMemoryAuditPort()).execute(
            replace(settings.get(), sampler_train_proportion=0.7),
            "manager@example.com",
        )


def test_update_does_not_persist_maturity_fields_owned_by_operational_settings() -> None:
    settings = InMemorySettingsPort()
    changes = InMemoryChangesPort()
    result = _use_case(settings, changes, InMemoryAuditPort()).execute(
        replace(settings.get(), maturing_days=99, stable_months=88),
        "manager@example.com",
    )
    assert result.maturing_days == AssistantOptimizerSettings().maturing_days
    assert result.stable_months == AssistantOptimizerSettings().stable_months
    assert changes.changes == []


def test_list_changes_limits_results() -> None:
    changes = InMemoryChangesPort()
    settings = InMemorySettingsPort()
    audit = InMemoryAuditPort()
    use_case = _use_case(settings, changes, audit)
    for count in range(3):
        use_case.execute(
            replace(settings.get(), assistant_max_message_chars=7_000 + count),
            "manager@example.com",
        )
    assert len(ListAssistantOptimizerSettingsChangesUseCase(changes).execute(2)) == 2
