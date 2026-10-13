from __future__ import annotations

import json

from src.application.dtos.research_dtos import (
    ResearchFinding,
    ResearchRequest,
    ResearchResult,
    ResearchSource,
    ResearchStatus,
)
from src.application.use_cases.research.research_tool import BoundedResearchTool


class RecordingResearchAgent:
    def __init__(self) -> None:
        self.requests: list[ResearchRequest] = []

    def research(self, request: ResearchRequest) -> ResearchResult:
        self.requests.append(request)
        return ResearchResult(
            ResearchSource.VECTOR_STORE,
            ResearchStatus.EXECUTED,
            [ResearchFinding("vector_store_match", "mo-1", "vishing bancario")],
        )


def test_agent_insights_reach_the_backend_and_findings_come_back() -> None:
    agent = RecordingResearchAgent()
    tool = BoundedResearchTool(agent, ResearchSource.VECTOR_STORE, max_interactions=2)

    observation = json.loads(tool("¿hay casos de vishing con nuevo beneficiario?"))

    assert agent.requests[0].question == "¿hay casos de vishing con nuevo beneficiario?"
    assert observation["findings"][0]["value"] == "mo-1"
    assert observation["remaining_interactions"] == 1


def test_interaction_budget_is_enforced_and_every_exchange_is_logged() -> None:
    agent = RecordingResearchAgent()
    tool = BoundedResearchTool(agent, ResearchSource.VECTOR_STORE, max_interactions=1)

    tool("primera pregunta")
    refused = tool("segunda pregunta")

    assert len(agent.requests) == 1
    assert "Límite de interacciones" in refused
    assert [
        (item["turn"], item["insights"], item["status"]) for item in tool.interactions
    ] == [
        (1, "primera pregunta", "executed"),
        (2, "segunda pregunta", "refused"),
    ]


class FailingResearchAgent:
    def __init__(self) -> None:
        self.calls = 0

    def research(self, request: ResearchRequest) -> ResearchResult:
        self.calls += 1
        return ResearchResult(
            ResearchSource.VECTOR_STORE, ResearchStatus.FAILED, error="timeout"
        )


def test_failed_calls_do_not_spend_the_interaction_budget() -> None:
    tool = BoundedResearchTool(
        FailingResearchAgent(), ResearchSource.VECTOR_STORE, max_interactions=1
    )

    observation = json.loads(tool("pregunta"))

    assert observation["status"] == "failed"
    assert observation["remaining_interactions"] == 1


def test_tool_becomes_unavailable_after_max_failures() -> None:
    agent = FailingResearchAgent()
    tool = BoundedResearchTool(
        agent, ResearchSource.VECTOR_STORE, max_interactions=5, max_failures=2
    )

    tool("uno")
    tool("dos")
    refused = tool("tres")

    assert agent.calls == 2
    assert "no está disponible" in refused
    assert [item["status"] for item in tool.interactions] == [
        "failed",
        "failed",
        "refused",
    ]
    assert tool.interactions[-1]["error"] == "research tool unavailable"
