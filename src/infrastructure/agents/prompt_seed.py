from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from src.application.ports.agent_prompt_port import ActiveAgentPrompt, AgentPrompt
from src.infrastructure.agents.factories import get_agent_prompt_repository

PROMPT_FILES = {
    "orchestrator.system": "orchestrator.system.txt",
    "subagent.stub.generator": "subagent.stub.generator.txt",
    "agent.chat.system": "agent.chat.system.txt",
}
PROMPT_DIRECTORY = Path(__file__).with_name("prompts")


def seed_default_agent_prompts() -> None:
    repository = get_agent_prompt_repository()
    now = datetime.now(UTC)
    for name, filename in PROMPT_FILES.items():
        if repository.get_active(name) is not None:
            continue
        content = (PROMPT_DIRECTORY / filename).read_text(encoding="utf-8")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        prompt = repository.get_version(name, 1)
        if prompt is None:
            prompt = AgentPrompt(
                name=name,
                version=1,
                content=content,
                content_hash=digest,
                status="ACTIVE",
                created_at=now,
            )
            repository.create_version(prompt)
        repository.activate(
            ActiveAgentPrompt(
                name=name,
                version=prompt.version,
                activated_at=now,
                activated_by="system-seed",
            ),
            expected_version=None,
        )
