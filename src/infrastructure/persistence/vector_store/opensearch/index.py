from __future__ import annotations

from opensearchpy import OpenSearch
from opensearchpy.exceptions import RequestError

from src.infrastructure.core.config import genai_config

FRAUD_KNOWLEDGE_INDEX = genai_config.OPENSEARCH_INDEX

_INDEX_BODY = {
    "settings": {"index.knn": True},
    "mappings": {
        "properties": {
            "type": {"type": "keyword"},
            "id": {"type": "keyword"},
            "text": {"type": "text", "analyzer": "spanish"},
            "text_embedded": {
                "type": "knn_vector",
                "dimension": genai_config.EMBEDDING_DIMENSIONS,
                "method": {
                    "name": "hnsw",
                    "engine": "faiss",
                    "space_type": "cosinesimil",
                    "parameters": {"ef_construction": 128, "m": 24},
                },
            },
            "segmento": {"type": "keyword"},
            "configuration": {"type": "keyword"},
            "version": {"type": "integer"},
            "activate": {"type": "boolean"},
            "taxonomia_id": {"type": "keyword"},
            "taxonomia": {"type": "text", "analyzer": "spanish"},
            "modus_operandi_id": {"type": "keyword"},
            "modus_operandi_ids": {"type": "keyword"},
            "similar_cases": {"type": "keyword"},
            "flags": {"type": "keyword"},
        }
    },
}

# search_pipeline id -> [keyword_weight, embedding_weight], matching the
# hybrid query clause order [match(text), knn(text_embedded)].
_SEARCH_PIPELINE_WEIGHTS = {
    "fraud_knowledge_hybrid_80_20": [0.2, 0.8],
    "fraud_knowledge_hybrid_50_50": [0.5, 0.5],
    "fraud_knowledge_hybrid_20_80": [0.8, 0.2],
}


def ensure_index(client: OpenSearch) -> None:
    try:
        client.indices.create(index=FRAUD_KNOWLEDGE_INDEX, body=_INDEX_BODY)
    except RequestError as e:
        if e.error != "resource_already_exists_exception":
            raise


def ensure_search_pipelines(client: OpenSearch) -> None:
    for name, weights in _SEARCH_PIPELINE_WEIGHTS.items():
        client.transport.perform_request(
            "PUT",
            f"/_search/pipeline/{name}",
            body={
                "phase_results_processors": [
                    {
                        "normalization-processor": {
                            "normalization": {"technique": "min_max"},
                            "combination": {
                                "technique": "arithmetic_mean",
                                "parameters": {"weights": weights},
                            },
                        }
                    }
                ]
            },
        )
