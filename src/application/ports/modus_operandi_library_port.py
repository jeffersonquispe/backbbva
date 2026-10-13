from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from src.domain.configurations.entities import (
    ResolutionTag,
    ShortageBehavior,
)

# Tags a playbook may fall back to when its resource is short. handle_by_aria
# is excluded: a fallback is applied by the executor without an LLM, so it
# must name a concrete action (another resource or a block).
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


def _primary_default() -> ShortageBehavior:
    return ShortageBehavior(resolution_tag=ResolutionTag.SCALE_TO_ANALYST)


@dataclass
class ModusOperandiPlaybook:
    """How the analyst agent should resolve an alert that matches this
    modus operandi - strategy text, the preferred resolution method, and
    what to fall back to when a resource is short. Lives on the global
    library entry (not in a versioned configuration), so the strategy can
    differ per modus operandi and be edited live.

    The analyst LLM receives all of it together with the live resource
    availability and decides. The executor then re-checks availability
    when it actually reserves the resource and, if it is gone, follows
    if_no_voicebot / if_no_analyst deterministically (no LLM)."""

    strategy: str = ""
    resolution: ShortageBehavior = field(default_factory=_primary_default)
    if_no_voicebot: ShortageBehavior = field(default_factory=ShortageBehavior)
    if_no_analyst: ShortageBehavior = field(default_factory=ShortageBehavior)


@dataclass
class ModusOperandiLibraryEntry:
    # Global, config-independent reference data - see taxonomy_library_port.py
    # for the snapshot-copy rationale. taxonomy_library_id points at a
    # TaxonomyLibraryEntry, not at any segment's local taxonomy.
    id: str
    title: str
    narrative: str
    taxonomy_library_id: str
    created_at: datetime
    updated_at: datetime
    evolved_variables: list[str] = field(default_factory=list)
    active: bool = True
    # Cached embedding of this entry's text representation (title +
    # narrative) - see taxonomy_library_port.py's `embedding` field for the
    # recycle-on-promote rationale.
    embedding: list[float] | None = None
    # None = no playbook written yet: an alert matching this modus operandi
    # is handled with the no-playbook default (escalate to an analyst,
    # block soft if none is available).
    playbook: ModusOperandiPlaybook | None = None


class ModusOperandiLibraryRepository(Protocol):
    def create(self, entry: ModusOperandiLibraryEntry) -> ModusOperandiLibraryEntry: ...

    def get(self, entry_id: str) -> ModusOperandiLibraryEntry | None: ...

    def list(self, *, active_only: bool = False) -> list[ModusOperandiLibraryEntry]: ...

    def update(
        self,
        entry_id: str,
        *,
        title: str | None = None,
        narrative: str | None = None,
        taxonomy_library_id: str | None = None,
        evolved_variables: list[str] | None = None,
        active: bool | None = None,
        embedding: list[float] | None = None,
        playbook: ModusOperandiPlaybook | None = None,
    ) -> ModusOperandiLibraryEntry | None: ...

    def delete(self, entry_id: str) -> None: ...
