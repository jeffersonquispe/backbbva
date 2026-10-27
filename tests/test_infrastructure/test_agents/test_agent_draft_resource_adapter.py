from datetime import UTC, datetime

from src.application.ports.channel_library_port import ChannelLibraryEntry
from src.domain.configurations.entities import TagCategory
from src.domain.tag_catalog.entities import TagEntry
from src.infrastructure.agents.agent_draft_resource_adapter import (
    AgentDraftResourceAdapter,
)


class _Channels:
    def list(self, *, active_only: bool = False):
        now = datetime.now(UTC)
        return [ChannelLibraryEntry("ch-1", "mobile", "Mobile", "", now, now)]


class _Tags:
    def list_by_category(self, category, *, active_only: bool = False):
        now = datetime.now(UTC)
        if category == TagCategory.EVENT_TYPE:
            return [TagEntry("tag-1", category, "transfer", now, now)]
        return []


class _Datasets:
    def execute(self):
        return [type("Dataset", (), {"name": "existing", "row_count": 0})()]


class _Unused:
    def execute(self, *args, **kwargs):
        raise AssertionError("verification does not apply mutations")


def _adapter():
    return AgentDraftResourceAdapter(
        channels=_Channels(),
        tags=_Tags(),
        datasets=_Datasets(),
        create_channel=_Unused(),
        create_tag=_Unused(),
        create_dataset=_Unused(),
    )


def test_resource_context_fetches_existing_channels_catalogs_and_datasets():
    adapter = _adapter()
    assert adapter.context("channel")["existing_channels"][0]["code"] == "mobile"
    assert adapter.context("catalog_entry")["categories"] == [
        "integration_point",
        "triggered_rule",
        "event_type",
    ]
    assert adapter.context("catalog_entry")["existing_entries"]["event_type"] == [
        "transfer"
    ]
    assert adapter.context("dataset_empty")["existing_datasets"] == ["existing"]


def test_resource_validation_rejects_duplicates_and_invalid_fields():
    adapter = _adapter()
    channel_checks = adapter.verify(
        "channel", {"code": "MOBILE", "name": "Mobile", "description": "channel"}
    )
    assert channel_checks[1] == ("duplicates", "FAIL", "DUPLICATE_RESOURCE")

    tag_checks = adapter.verify(
        "catalog_entry", {"category": "event_type", "value": "TRANSFER"}
    )
    assert tag_checks[1] == ("duplicates", "FAIL", "DUPLICATE_RESOURCE")

    dataset_checks = adapter.verify(
        "dataset_empty", {"name": "new", "fields": ["id", "ID"]}
    )
    assert dataset_checks[0] == ("schema", "FAIL", "DRAFT_SCHEMA_INVALID")
