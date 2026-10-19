from datetime import UTC, datetime
from decimal import Decimal

from scripts import db_backup
from src.application.ports.assistant_optimizer_settings_changes_port import (
    AssistantOptimizerSettingChange,
    AssistantOptimizerSettingsChange,
)
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettings,
)
from src.infrastructure.persistence.database.dynamodb.repositories.assistant_optimizer_settings_repository import (
    CHANGES_TABLE_NAME,
    SETTINGS_TABLE_NAME,
    DynamoAssistantOptimizerSettingsRepository,
    _change_from_item,
    _change_to_item,
    _from_item,
    _to_item,
)
from src.infrastructure.persistence.database.dynamodb.schemas import (
    ASSISTANT_OPTIMIZER_SETTINGS_CHANGES_TABLE,
    ASSISTANT_OPTIMIZER_SETTINGS_TABLE,
)


class InMemoryTable:
    def __init__(self) -> None:
        self.item = None
        self.items = []

    def get_item(self, Key):
        return {"Item": self.item} if self.item else {}

    def put_item(self, Item):
        self.item = Item
        self.items.append(Item)

    def query(self, **kwargs):
        return {"Items": list(reversed(self.items))}


class InMemoryDynamoResource:
    def __init__(self) -> None:
        self.tables = {
            SETTINGS_TABLE_NAME: InMemoryTable(),
            CHANGES_TABLE_NAME: InMemoryTable(),
        }

    def Table(self, name):
        return self.tables[name]


def test_settings_item_omits_non_persisted_maturity_values_and_round_trips(monkeypatch) -> None:
    settings = AssistantOptimizerSettings(
        optimizer_session_budget_ceiling_usd=17.25,
        sampler_strata=("channel", "amount"),
        maturing_days=99,
    )
    item = _to_item(settings)

    assert item["optimizer_session_budget_ceiling_usd"] == Decimal("17.25")
    assert item["sampler_strata"] == ["channel", "amount"]
    assert "maturing_days" not in item
    restored = _from_item(item)
    assert restored.optimizer_session_budget_ceiling_usd == 17.25
    assert restored.sampler_strata == ("channel", "amount")
    assert restored.maturing_days == AssistantOptimizerSettings().maturing_days


def test_old_settings_items_read_contract_defaults() -> None:
    restored = _from_item({"record_id": "current"})
    assert restored.optimizer_session_budget_ceiling_usd == 50.0
    assert restored.optimizer_session_budget_ceiling_seconds == 43_200
    assert restored.optimizer_stop_on_critical_failure is True


def test_change_item_round_trip() -> None:
    change = AssistantOptimizerSettingsChange(
        id="change-1",
        changed_by="manager@example.com",
        changed_at=datetime(2026, 10, 18, tzinfo=UTC),
        changes=[AssistantOptimizerSettingChange("optimizer_enabled", False, True)],
    )
    restored = _change_from_item(_change_to_item(change))
    assert restored == change


def test_repository_reads_updates_and_lists_history(monkeypatch) -> None:
    resource = InMemoryDynamoResource()
    monkeypatch.setattr(
        "src.infrastructure.persistence.database.dynamodb.repositories.assistant_optimizer_settings_repository.get_dynamodb_resource",
        lambda: resource,
    )
    repository = DynamoAssistantOptimizerSettingsRepository()
    changed = AssistantOptimizerSettings(assistant_enabled=False)
    repository.update(changed)
    repository.append(
        AssistantOptimizerSettingsChange(
            "change-1",
            "manager@example.com",
            datetime(2026, 10, 18, tzinfo=UTC),
            [AssistantOptimizerSettingChange("assistant_enabled", True, False)],
        )
    )
    assert repository.get().assistant_enabled is False
    assert len(repository.list()) == 1
    assert repository.list()[0].id == "change-1"


def test_table_schemas_are_registered_for_dynamic_provisioning() -> None:
    assert ASSISTANT_OPTIMIZER_SETTINGS_TABLE["TableName"] == SETTINGS_TABLE_NAME
    assert ASSISTANT_OPTIMIZER_SETTINGS_CHANGES_TABLE["TableName"] == CHANGES_TABLE_NAME


def test_settings_tables_are_in_the_backup_catalog() -> None:
    assert SETTINGS_TABLE_NAME in db_backup._configured_table_names()
    assert CHANGES_TABLE_NAME in db_backup._configured_table_names()


def test_manager_provisions_settings_tables(monkeypatch) -> None:
    from src.infrastructure.persistence.database.dynamodb import manager

    created = []
    monkeypatch.setattr(manager, "create_table", lambda schema: created.append(schema["TableName"]))
    monkeypatch.setattr(manager, "enable_ttl", lambda *_args: None)
    monkeypatch.setattr(manager, "ensure_global_secondary_indexes", lambda *_args: None)

    manager.ensure_all_tables()

    assert SETTINGS_TABLE_NAME in created
    assert CHANGES_TABLE_NAME in created
