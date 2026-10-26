from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class AgentExperimentKind(StrEnum):
    ISOLATED = "ISOLATED"
    COMBINATION = "COMBINATION"


class AgentExperimentStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    REJECTED_GLOBAL_CONSTRAINT = "REJECTED_GLOBAL_CONSTRAINT"
    FAILED = "FAILED"


@dataclass(frozen=True, order=True)
class ComponentVersionReference:
    """Immutable pin for one candidate component revision."""

    component: str
    entity_id: str
    version: str
    content_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "component", self.component.lower())

    @classmethod
    def pin(
        cls, component: str, entity_id: str, version: str, content: Any
    ) -> ComponentVersionReference:
        normalized_component = component.lower()
        canonical_content = content
        if (
            normalized_component == "model"
            and isinstance(content, dict)
            and isinstance(content.get("model_id"), str)
            and isinstance(content.get("artifact_sha256"), str)
        ):
            # The immutable artifact digest represents the serialized bundle;
            # do not stringify/copy potentially large model bytes just to pin it.
            canonical_content = {
                "model_id": content["model_id"],
                "artifact_sha256": content["artifact_sha256"],
            }
        canonical = json.dumps(
            canonical_content,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
        return cls(
            component=normalized_component,
            entity_id=entity_id,
            version=version,
            content_sha256=hashlib.sha256(canonical).hexdigest(),
        )


@dataclass(frozen=True)
class AgentExperiment:
    session_id: str
    experiment_id: str
    iteration_number: int
    kind: AgentExperimentKind
    status: AgentExperimentStatus
    components: tuple[ComponentVersionReference, ...]
    objective_id: str
    objective_version: int
    created_at: datetime
    baseline_components: tuple[ComponentVersionReference, ...] = ()
    snapshot_id: str | None = None
    snapshot_sha256: str | None = None
    completed_at: datetime | None = None
    global_evaluation: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    # Candidate (hypothesis) of the optimization run this experiment tests.
    candidate_id: str | None = None
