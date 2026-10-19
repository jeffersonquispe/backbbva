from datetime import UTC, datetime

from src.domain.configurations.entities import FlagType, ResolutionTag
from src.domain.fraud_knowledge.library_entities import (
    FALLBACK_RESOLUTION_TAGS,
    PRIMARY_RESOLUTION_TAGS,
    FlagLibraryEntry,
    ModusOperandiPlaybook,
)


def test_modus_operandi_playbook_defaults_are_independent() -> None:
    first = ModusOperandiPlaybook()
    second = ModusOperandiPlaybook()

    first.resolution.strategy = "review"
    first.if_no_voicebot.strategy = "block"

    assert second.resolution.strategy == ""
    assert second.if_no_voicebot.strategy == ""
    assert second.resolution.resolution_tag is ResolutionTag.SCALE_TO_ANALYST


def test_flag_links_and_playbook_resolution_rules_are_domain_owned() -> None:
    now = datetime.now(UTC)
    first = FlagLibraryEntry(
        id="flag-1",
        flag_type=FlagType.RED,
        name="New device",
        description="",
        created_at=now,
        updated_at=now,
    )
    second = FlagLibraryEntry(
        id="flag-2",
        flag_type=first.flag_type,
        name="Unusual amount",
        description="",
        created_at=now,
        updated_at=now,
    )

    first.modus_operandi_library_ids.append("mo-1")

    assert second.modus_operandi_library_ids == []
    assert ResolutionTag.HANDLE_BY_ARIA in PRIMARY_RESOLUTION_TAGS
    assert ResolutionTag.HANDLE_BY_ARIA not in FALLBACK_RESOLUTION_TAGS
