from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class AgentPrompt:
    name: str
    version: int
    content: str
    content_hash: str
    status: str
    created_at: datetime


@dataclass(frozen=True)
class ActiveAgentPrompt:
    name: str
    version: int
    activated_at: datetime
    activated_by: str


class AgentPromptRepository(Protocol):
    def create_version(self, prompt: AgentPrompt) -> AgentPrompt: ...

    def get_version(self, name: str, version: int) -> AgentPrompt | None: ...

    def get_active(self, name: str) -> ActiveAgentPrompt | None: ...

    def activate(
        self, pointer: ActiveAgentPrompt, expected_version: int | None
    ) -> None: ...
