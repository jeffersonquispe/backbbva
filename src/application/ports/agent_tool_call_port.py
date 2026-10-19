from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class AgentToolCall:
    call_id: str
    run_id: str
    tool_name: str
    status: str
    prompt_ref: dict[str, str]
    safe_input_summary: dict[str, Any]
    safe_result_summary: dict[str, Any] | None
    created_at: datetime


class AgentToolCallRepository(Protocol):
    def create(self, call: AgentToolCall) -> AgentToolCall: ...

    def list_for_run(self, run_id: str, limit: int = 100) -> list[AgentToolCall]: ...
