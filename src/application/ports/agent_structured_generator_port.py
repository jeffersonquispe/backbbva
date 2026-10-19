from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AgentStructuredGenerationInput:
    system_prompt: str
    persisted_context: str
    masked_user_message: str


class AgentStructuredGenerator(Protocol):
    """Generates a structured agent payload without chat response wrapping."""

    def generate(self, request: AgentStructuredGenerationInput) -> str: ...
