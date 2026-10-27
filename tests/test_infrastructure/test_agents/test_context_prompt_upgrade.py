from datetime import UTC, datetime
from hashlib import sha256

import pytest

from src.application.ports.agent_prompt_port import ActiveAgentPrompt, AgentPrompt
from src.infrastructure.agents import context_prompt_upgrade as upgrade

NOW = datetime(2026, 10, 27, tzinfo=UTC)


class PromptRepository:
    def __init__(self, content):
        prompt = AgentPrompt(
            "agent.chat.system",
            1,
            content,
            sha256(content.encode()).hexdigest(),
            "ACTIVE",
            NOW,
        )
        self.versions = {1: prompt}
        self.active = ActiveAgentPrompt(prompt.name, 1, NOW, "old")

    def get_active(self, name):
        return self.active

    def get_version(self, name, version):
        return self.versions.get(version)

    def create_version(self, prompt):
        assert prompt.version not in self.versions
        self.versions[prompt.version] = prompt
        return prompt

    def activate(self, pointer, expected_version):
        assert self.active.version == expected_version
        self.active = pointer


@pytest.fixture
def templates(tmp_path, monkeypatch):
    monkeypatch.setattr(upgrade, "PROMPT_DIR", tmp_path)
    monkeypatch.setattr(
        upgrade, "LEGACY_HASHES", {"agent.chat.system": {sha256(b"old").hexdigest()}}
    )
    (tmp_path / "agent.chat.system.txt").write_text("new")


def test_dry_run_and_upgrade_preserve_old_version_and_are_idempotent(templates):
    repository = PromptRepository("old")

    def latest(name):
        return max(repository.versions)

    assert (
        upgrade.upgrade_context_prompts(repository, latest)[0].outcome
        == "would_upgrade"
    )
    assert repository.active.version == 1
    assert (
        upgrade.upgrade_context_prompts(repository, latest, apply=True)[0].outcome
        == "upgraded"
    )
    assert repository.active.version == 2
    assert repository.versions[1].content == "old"
    assert repository.versions[2].content == "new"
    assert (
        upgrade.upgrade_context_prompts(repository, latest, apply=True)[0].outcome
        == "up_to_date"
    )
    assert len(repository.versions) == 2


def test_customized_active_prompt_is_never_overwritten(templates):
    repository = PromptRepository("custom")
    result = upgrade.upgrade_context_prompts(repository, lambda name: 1, apply=True)[0]
    assert result.outcome == "custom_prompt"
    assert repository.active.version == 1
    assert len(repository.versions) == 1


def test_corrupt_content_hash_is_never_overwritten(templates):
    repository = PromptRepository("old")
    repository.versions[1] = AgentPrompt(
        "agent.chat.system", 1, "changed", "invalid", "ACTIVE", NOW
    )
    result = upgrade.upgrade_context_prompts(repository, lambda name: 1, apply=True)[0]
    assert result.outcome == "invalid_hash"
    assert repository.active.version == 1
