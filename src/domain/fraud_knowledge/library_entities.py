from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.domain.configurations.entities import (
    FlagType,
    ResolutionTag,
    ShortageBehavior,
)

FALLBACK_RESOLUTION_TAGS = frozenset(
    {
        ResolutionTag.SCALE_TO_ANALYST,
        ResolutionTag.SEND_TO_VOICEBOT,
        ResolutionTag.BLOCK_SOFT,
        ResolutionTag.BLOCK_HARD,
    }
)
PRIMARY_RESOLUTION_TAGS = frozenset(
    {
        ResolutionTag.SCALE_TO_ANALYST,
        ResolutionTag.SEND_TO_VOICEBOT,
        ResolutionTag.HANDLE_BY_ARIA,
    }
)


def _primary_resolution() -> ShortageBehavior:
    return ShortageBehavior(resolution_tag=ResolutionTag.SCALE_TO_ANALYST)


@dataclass
class TaxonomyLibraryEntry:
    id: str
    code: str
    name: str
    description: str
    created_at: datetime
    updated_at: datetime
    variables: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    active: bool = True
    embedding: list[float] | None = None


@dataclass
class ModusOperandiPlaybook:
    """Routing strategy and shortage behavior for a modus operandi."""

    strategy: str = ""
    resolution: ShortageBehavior = field(default_factory=_primary_resolution)
    if_no_voicebot: ShortageBehavior = field(default_factory=ShortageBehavior)
    if_no_analyst: ShortageBehavior = field(default_factory=ShortageBehavior)


@dataclass
class ModusOperandiLibraryEntry:
    id: str
    title: str
    narrative: str
    taxonomy_library_id: str
    created_at: datetime
    updated_at: datetime
    evolved_variables: list[str] = field(default_factory=list)
    active: bool = True
    embedding: list[float] | None = None
    playbook: ModusOperandiPlaybook | None = None


@dataclass
class SimilarCaseLibraryEntry:
    id: str
    text: str
    modus_operandi_library_id: str
    taxonomy_library_id: str
    created_at: datetime
    updated_at: datetime
    active: bool = True
    embedding: list[float] | None = None


@dataclass
class FlagLibraryEntry:
    id: str
    flag_type: FlagType
    name: str
    description: str
    created_at: datetime
    updated_at: datetime
    evolved_variables: list[str] = field(default_factory=list)
    modus_operandi_library_ids: list[str] = field(default_factory=list)
    active: bool = True
    embedding: list[float] | None = None
