from __future__ import annotations

import time

from src.application.ports.agent_subagent_port import (
    AgentSubagentInput,
    AgentSubagentOutput,
)


class StubAgentSubagent:
    """Deterministic specialist used to exercise the orchestration contract."""

    def __init__(
        self,
        delay_seconds: float = 0.0,
        name: str = "stub",
        verified: bool = True,
    ) -> None:
        self._delay_seconds = max(0.0, min(delay_seconds, 30.0))
        self._name = name
        self._verified = verified

    @property
    def name(self) -> str:
        return self._name

    def execute(self, request: AgentSubagentInput) -> AgentSubagentOutput:
        if request.cancelled:
            return AgentSubagentOutput(
                subagent=self.name,
                verification_status="CANCELLED",
                error_code="RUN_CANCELLED",
            )
        if self._delay_seconds:
            time.sleep(self._delay_seconds)
        return AgentSubagentOutput(
            subagent=self.name,
            contribution={"hypothesis": request.hypothesis, "scope": request.scope},
            verification_status="PASSED" if self._verified else "PENDING_VERIFICATION",
            safe_metrics={"steps": 1},
        )
