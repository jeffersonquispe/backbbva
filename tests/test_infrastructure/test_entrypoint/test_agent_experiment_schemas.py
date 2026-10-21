from datetime import UTC, datetime

from src.domain.agents.experiment import (
    AgentExperiment,
    AgentExperimentKind,
    AgentExperimentStatus,
    ComponentVersionReference,
)
from src.infrastructure.entrypoint.api.schemas.agent import AgentExperimentResponse


def test_agent_experiment_response_exposes_pinned_versions_and_safe_evaluation():
    experiment = AgentExperiment(
        session_id="session-1",
        experiment_id="experiment-1",
        iteration_number=2,
        kind=AgentExperimentKind.ISOLATED,
        status=AgentExperimentStatus.REJECTED_GLOBAL_CONSTRAINT,
        components=(
            ComponentVersionReference(
                component="configuration",
                entity_id="config-1",
                version="12",
                content_sha256="c" * 64,
            ),
        ),
        baseline_components=(
            ComponentVersionReference(
                component="configuration",
                entity_id="config-1",
                version="11",
                content_sha256="d" * 64,
            ),
        ),
        objective_id="fraud",
        objective_version=3,
        created_at=datetime(2026, 10, 20, tzinfo=UTC),
        completed_at=datetime(2026, 10, 20, 0, 1, tzinfo=UTC),
        global_evaluation={
            "status": "REJECTED_GLOBAL_CONSTRAINT",
            "minimum_protected_segment_size": 30,
            "baseline_global": {"recall": 0.9},
            "global": {"support": None, "precision": None},
            "segments": {},
            "constraints": [
                {
                    "constraint_id": "segment_support:channel_digital",
                    "status": "FAILED",
                    "aggregate": None,
                    "minimum_sample_size": 30,
                }
            ],
        },
    )

    response = AgentExperimentResponse.model_validate(experiment)

    assert response.components[0].version == "12"
    assert response.components[0].content_sha256 == "c" * 64
    assert response.baseline_components[0].version == "11"
    assert response.status == "REJECTED_GLOBAL_CONSTRAINT"
    assert response.global_evaluation["segments"] == {}
