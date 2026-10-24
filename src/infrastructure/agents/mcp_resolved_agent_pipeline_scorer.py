from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.application.ports.agent_experiment_component_port import ResolvedAgentComponent
from src.application.ports.agent_pipeline_scorer_port import (
    AgentPipelineScore,
    AgentPipelineScorer,
)
from src.domain.datasets.mature_sample_entities import DatasetSnapshot
from src.infrastructure.core.config import genai_config


class MCPResolvedAgentPipelineScorer(AgentPipelineScorer):
    """Score an immutable model/configuration/knowledge component stack."""

    def predict_positive(
        self,
        components: tuple[ResolvedAgentComponent, ...],
        rows: list[dict[str, Any]],
        *,
        snapshot: DatasetSnapshot,
    ) -> AgentPipelineScore:
        del snapshot  # H12's pinned scoring contract is snapshot-row based.
        by_type = {item.reference.component: item for item in components}
        if set(by_type) != {"model", "configuration", "library", "vector_store"}:
            raise ValueError("COMPLETE_COMPONENT_STACK_REQUIRED")
        model_content = by_type["model"].content
        body = {
            "model_id": model_content.get("model_id"),
            "artifact_sha256": model_content.get("artifact_sha256"),
            "configuration": by_type["configuration"].content,
            "library": by_type["library"].content,
            "vector_store": by_type["vector_store"].content,
            "rows": rows,
            "knowledge_decision_policy": "evidence_only_v1",
        }
        request = Request(
            f"{genai_config.MCP_BASE_URL.rstrip('/')}/internal/score-pinned-pipeline",
            data=json.dumps(body, default=str).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=genai_config.MCP_TIMEOUT_SECONDS) as response:
                result = json.loads(response.read())
        except HTTPError as error:
            raise RuntimeError("PINNED_PIPELINE_SCORING_FAILED") from error
        except (URLError, TimeoutError, OSError) as error:
            raise RuntimeError("PINNED_PIPELINE_SCORING_UNAVAILABLE") from error
        predictions = (
            result.get("predicted_positive") if isinstance(result, dict) else None
        )
        evidence_count = (
            result.get("knowledge_evidence_assets")
            if isinstance(result, dict)
            else None
        )
        if (
            not isinstance(predictions, list)
            or len(predictions) != len(rows)
            or not all(isinstance(value, bool) for value in predictions)
            or result.get("knowledge_decision_policy") != "evidence_only_v1"
            or not isinstance(evidence_count, int)
            or isinstance(evidence_count, bool)
            or evidence_count < 0
        ):
            raise RuntimeError("PINNED_PIPELINE_SCORING_INVALID")
        return AgentPipelineScore(
            predictions=predictions,
            knowledge_evidence_asset_count=evidence_count,
        )
