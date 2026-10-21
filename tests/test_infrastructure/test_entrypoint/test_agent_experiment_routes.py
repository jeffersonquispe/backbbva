from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.domain.agents.experiment import (
    AgentExperiment,
    AgentExperimentKind,
    AgentExperimentStatus,
    ComponentVersionReference,
)
from src.infrastructure.entrypoint.api.routers import agent_router


class InMemoryAgentExperimentRepository:
    def __init__(self, experiment):
        self.experiment = experiment

    def list_for_session(self, session_id, limit=50):
        return [self.experiment][:limit]

    def get(self, session_id, experiment_id):
        if (session_id, experiment_id) == (
            self.experiment.session_id,
            self.experiment.experiment_id,
        ):
            return self.experiment
        return None


def _experiment():
    return AgentExperiment(
        session_id="session-1",
        experiment_id="experiment-1",
        iteration_number=3,
        kind=AgentExperimentKind.ISOLATED,
        status=AgentExperimentStatus.SUCCEEDED,
        components=(
            ComponentVersionReference(
                component="model",
                entity_id="model-1",
                version="artifact-2",
                content_sha256="a" * 64,
            ),
        ),
        objective_id="fraud",
        objective_version=4,
        created_at=datetime(2026, 10, 20, tzinfo=UTC),
        baseline_components=(
            ComponentVersionReference(
                component="model",
                entity_id="model-0",
                version="artifact-1",
                content_sha256="b" * 64,
            ),
        ),
    )


def test_list_experiments_checks_session_and_returns_persisted_pins(monkeypatch):
    experiment = _experiment()
    repository = InMemoryAgentExperimentRepository(experiment)
    ownership_checks = []
    monkeypatch.setattr(
        agent_router,
        "_owned_session",
        lambda session_id, owner_id: ownership_checks.append((session_id, owner_id)),
    )
    monkeypatch.setattr(
        agent_router, "get_agent_experiment_repository", lambda: repository
    )

    result = agent_router.list_session_experiments(
        "session-1", SimpleNamespace(id=uuid4()), limit=20
    )

    assert result == [experiment]
    assert ownership_checks[0][0] == "session-1"
    assert len(result[0].components) == 1
    assert len(result[0].baseline_components) == 1


def test_get_experiment_uses_safe_not_found_code(monkeypatch):
    repository = InMemoryAgentExperimentRepository(_experiment())
    monkeypatch.setattr(agent_router, "_owned_session", lambda *args: None)
    monkeypatch.setattr(
        agent_router, "get_agent_experiment_repository", lambda: repository
    )

    with pytest.raises(HTTPException) as captured:
        agent_router.get_session_experiment(
            "session-1", "missing", SimpleNamespace(id=uuid4())
        )

    assert captured.value.status_code == 404
    assert captured.value.detail == {"code": "EXPERIMENT_NOT_FOUND"}
