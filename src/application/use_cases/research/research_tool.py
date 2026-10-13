"""A bounded research backend exposed to a ReAct agent as a callable tool.

The primary agent decides when to call it and what to ask ("insights"),
as many times as it needs - up to `max_interactions` answered calls, after
which the tool answers with a budget-exhausted observation instead of
running. Failed calls (errors, timeouts) don't spend that budget, but after
`max_failures` of them the tool is treated as unavailable for the rest
of the step, so a down backend can't be retried forever. Every exchange is
recorded in `interactions` (the audit list surfaced on the step's output),
including refused calls.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from src.application.dtos.research_dtos import (
    ResearchRequest,
    ResearchSource,
    ResearchStatus,
)
from src.application.ports.research_port import ResearchAgent

DEFAULT_MAX_FAILURES = 2


class BoundedResearchTool:
    def __init__(
        self,
        agent: ResearchAgent,
        source: ResearchSource,
        max_interactions: int,
        max_failures: int = DEFAULT_MAX_FAILURES,
    ) -> None:
        self._agent = agent
        self._source = source
        self._max_interactions = max(0, max_interactions)
        self._max_failures = max(0, max_failures)
        self.interactions: list[dict[str, Any]] = []

    def _count(self, status: ResearchStatus) -> int:
        return sum(1 for item in self.interactions if item["status"] == str(status))

    @property
    def remaining(self) -> int:
        return max(0, self._max_interactions - self._count(ResearchStatus.EXECUTED))

    def __call__(self, insights: str) -> str:
        turn = len(self.interactions) + 1
        if self.remaining == 0:
            return self._refuse(
                turn, insights, "interaction budget exhausted",
                "Límite de interacciones con la herramienta alcanzado "
                f"({self._max_interactions}). Concluye con la evidencia disponible.",
            )
        if self._count(ResearchStatus.FAILED) >= self._max_failures:
            return self._refuse(
                turn, insights, "research tool unavailable",
                f"La herramienta falló {self._max_failures} veces y no está "
                "disponible en este paso. Concluye con la evidencia disponible.",
            )
        result = self._agent.research(ResearchRequest(self._source, insights))
        findings = [asdict(finding) for finding in result.findings]
        self.interactions.append({
            "turn": turn, "insights": insights, "status": str(result.status),
            "findings": findings, "error": result.error,
        })
        return json.dumps(
            {
                "status": str(result.status),
                "findings": findings,
                "error": result.error,
                "remaining_interactions": self.remaining,
            },
            default=str,
            ensure_ascii=False,
        )

    def _refuse(self, turn: int, insights: str, error: str, observation: str) -> str:
        self.interactions.append({
            "turn": turn, "insights": insights, "status": "refused",
            "findings": [], "error": error,
        })
        return observation
