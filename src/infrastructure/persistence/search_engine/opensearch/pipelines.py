"""
OpenSearch search pipelines for hybrid search (keyword + vector).

Defines four pipelines with different weightings for the normalization-processor.
Clause order in the hybrid query: [0] = match on "text", [1] = k-NN on "vector_field".
So weights are [keyword_weight, vector_weight].
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Pipeline name -> (keyword_weight, vector_weight); weights must sum to 1.0
HYBRID_PIPELINES: dict[str, tuple[float, float]] = {
    "conceptual-pipeline": (0.2, 0.8),  # Teoría y Preguntas Abiertas
    "precision-pipeline": (0.8, 0.2),   # Definiciones y Siglas
    "procedural-pipeline": (0.5, 0.5),   # Pasos y Guías   
}

VALID_QUERY_TYPES = frozenset(HYBRID_PIPELINES.keys())

# Chunk types to restrict search to for each pipeline.
# precision → raw text slices only (exact term/acronym recall).
# all others → structural semantic chunks (overview, workflow, step-level context).
PIPELINE_CHUNK_TYPES: dict[str, list[str]] = {
    "precision-pipeline": ["snippet"],
    "conceptual-pipeline": ["macro", "parent_workflow", "action_step", "snippet"],
    "procedural-pipeline": ["macro", "parent_workflow", "action_step", "snippet"],
}


def chunk_types_for_pipeline(pipeline_name: str | None) -> list[str] | None:
    """
    Return the chunk_type whitelist for a given pipeline, or None to search all types.
    """
    if not pipeline_name:
        return None
    return PIPELINE_CHUNK_TYPES.get(pipeline_name)


def pipeline_name_from_query_type(
    query_type: str | None
) -> str:
    """
    Resolve hybrid search pipeline from LLM query_type with fallbac.
    Used by LangGraph to choose the same pipeline for find_sources and fetch_parents.
    """
    if query_type and query_type.strip().lower() in ("conceptual", "precision", "procedural"):
        return f"{query_type.strip().lower()}-pipeline"


def _pipeline_body(keyword_weight: float, vector_weight: float) -> dict[str, Any]:
    """Build search pipeline body with normalization-processor and weights."""
    return {
        "description": "Hybrid search score combination (keyword + vector)",
        "phase_results_processors": [
            {
                "normalization-processor": {
                    "normalization": {"technique": "min_max"},
                    "combination": {
                        "technique": "arithmetic_mean",
                        "parameters": {
                            "weights": [keyword_weight, vector_weight]
                        }
                    }
                }
            }
        ]
    }


def ensure_search_pipelines(client: Any) -> None:
    """
    Create or overwrite all hybrid search pipelines on the given OpenSearch client.
    Idempotent - safe to call multiple times.

    Args:
        client: OpenSearch client (from opensearchpy) with transport supporting
                perform_request(method, url, body=...).
    """
    log.info(f"Ensuring search pipelines:")
    for name, (kw, vw) in HYBRID_PIPELINES.items():
        try:
            body = _pipeline_body(kw, vw)
            # OpenSearch REST: PUT /_search/pipeline/{id}
            client.transport.perform_request(
                method="PUT",
                url=f"/_search/pipeline/{name}",
                body=body,
            )
            log.info(f"Created/updated search pipeline: {name} (keyword={kw}, vector={vw})")
        except Exception as e:
            log.exception(f"Error ensuring search pipeline {name}")
            raise
