from __future__ import annotations

import logging

from src.infrastructure.core.config import genai_config
from src.infrastructure.persistence.vector_store.opensearch.client import (
    get_opensearch_client,
)
from src.infrastructure.persistence.vector_store.opensearch.index import (
    ensure_index,
    ensure_search_pipelines,
)

log = logging.getLogger(__name__)


def ensure_fraud_knowledge_index() -> None:
    if not genai_config.OPENSEARCH_ENDPOINT:
        return

    try:
        client = get_opensearch_client()
        ensure_index(client)
        ensure_search_pipelines(client)
    except Exception:
        log.exception("OpenSearch index initialization failed")
        raise
