"""Explicit, guarded upgrade of the three default agent context prompts.

Existing custom prompts are never overwritten: an active hash must match a
known pre-upgrade default. Sessions already pinned to an older version keep it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.application.ports.agent_prompt_port import (
    ActiveAgentPrompt,
    AgentPrompt,
    AgentPromptRepository,
)

PROMPT_DIR = Path(__file__).with_name("prompts")
LEGACY_HASHES = {
    "agent.chat.system": {
        "fa987ae848cb946655a469582bab949b476342b2a669a634e6c919a817d4552a",
        "be8e418a929ee5c6680c7722e646713d1921eddde9ce4773c140db09f9067c6e",
    },
    "agent.specialist.configuration": {
        "b26036fbbfb8243ed941cb161613d971b78701c9c9809b9e8a6e93afd34417b3",
        "55f4ff139bd1a68c06f2a52dd3defdb593fbae0ad1080813d7e96f121bb87c86",
    },
    "agent.specialist.vector_store": {
        "e79bd4785033f53e71e72f562b6c869af0dbe36b98f7fc5cdc568917df20c43d",
        "6a86e3fd1102bac97a5a93bf71c8c832b96a4f96068119c40025c5e0bf0646ed",
    },
}


@dataclass(frozen=True)
class PromptUpgradeResult:
    name: str
    outcome: str
    previous_version: int | None
    version: int | None


def upgrade_context_prompts(
    repository: AgentPromptRepository,
    latest_version: Callable[[str], int],
    *,
    apply: bool = False,
) -> list[PromptUpgradeResult]:
    results = []
    for name, legacy_hashes in LEGACY_HASHES.items():
        active = repository.get_active(name)
        if active is None:
            results.append(PromptUpgradeResult(name, "missing_active", None, None))
            continue
        previous = repository.get_version(name, active.version)
        if previous is None:
            results.append(
                PromptUpgradeResult(name, "missing_version", active.version, None)
            )
            continue
        actual_hash = hashlib.sha256(previous.content.encode("utf-8")).hexdigest()
        if actual_hash != previous.content_hash:
            results.append(
                PromptUpgradeResult(name, "invalid_hash", active.version, None)
            )
            continue
        content = (PROMPT_DIR / f"{name}.txt").read_text(encoding="utf-8")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if actual_hash == digest:
            results.append(
                PromptUpgradeResult(name, "up_to_date", active.version, active.version)
            )
            continue
        if actual_hash not in legacy_hashes:
            results.append(
                PromptUpgradeResult(name, "custom_prompt", active.version, None)
            )
            continue
        if not apply:
            results.append(
                PromptUpgradeResult(name, "would_upgrade", active.version, None)
            )
            continue
        version = latest_version(name) + 1
        now = datetime.now(UTC)
        repository.create_version(
            AgentPrompt(name, version, content, digest, "ACTIVE", now)
        )
        repository.activate(
            ActiveAgentPrompt(name, version, now, "context-prompt-upgrade"),
            expected_version=active.version,
        )
        results.append(PromptUpgradeResult(name, "upgraded", active.version, version))
    return results
