from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from src.domain.agents.experiment import (
    AgentExperiment,
    AgentExperimentKind,
    AgentExperimentStatus,
    ComponentVersionReference,
)
from src.infrastructure.persistence.database.dynamodb.repositories.agent_repositories import (
    _encode,
    _experiment,
)


def test_agent_experiment_persistence_round_trip_keeps_exact_component_pins():
    experiment = AgentExperiment(
        session_id="session-1",
        experiment_id="experiment-1",
        iteration_number=4,
        kind=AgentExperimentKind.COMBINATION,
        status=AgentExperimentStatus.SUCCEEDED,
        components=(
            ComponentVersionReference(
                component="model",
                entity_id="model-uuid",
                version="artifact-v2",
                content_sha256="a" * 64,
            ),
            ComponentVersionReference(
                component="vector_store",
                entity_id="vector-store-7",
                version="generation-3",
                content_sha256="b" * 64,
            ),
        ),
        baseline_components=(
            ComponentVersionReference(
                component="model",
                entity_id="model-baseline",
                version="artifact-v1",
                content_sha256="c" * 64,
            ),
            ComponentVersionReference(
                component="vector_store",
                entity_id="vector-store-baseline",
                version="generation-2",
                content_sha256="d" * 64,
            ),
        ),
        objective_id="fraud",
        objective_version=8,
        created_at=datetime(2026, 10, 20, tzinfo=UTC),
        snapshot_id="snapshot-immutable-1",
        snapshot_sha256="e" * 64,
        completed_at=datetime(2026, 10, 20, 0, 1, tzinfo=UTC),
        global_evaluation={
            "status": "PASSED",
            "global": {"eligible_count": 120, "precision": 0.95},
            "segments": {"channel_digital": {"support": 45}},
        },
    )

    saved = _experiment(_encode(asdict(experiment)))

    assert saved == experiment
    assert saved.snapshot_id == "snapshot-immutable-1"
    assert saved.snapshot_sha256 == "e" * 64
