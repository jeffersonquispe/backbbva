"""
Manager for OpenSearch chunk persistence: child and parent collections.

- Child collection: OpenSearch index for chunks (macro, troubleshooting, action steps).
- Parent collection: DynamoDB table for parent workflow documents.

Use ensure_opensearch_tables to create or verify
that the backing stores exist before running ingest or search.
"""

from __future__ import annotations

import logging
from typing import Optional

import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth
from src.infrastructure.core.config import genai_config
from .settings import OpenSearchSettings, get_opensearch_settings
from .schemas import get_lupita_chunk_index_schema
from .pipelines import ensure_search_pipelines

log = logging.getLogger(__name__)


def _parse_endpoint(endpoint: str) -> tuple[str, int, bool]:
    """Return (host, port, use_ssl) from an endpoint URL."""
    use_ssl = endpoint.startswith("https://")
    rest = endpoint.replace("https://", "").replace("http://", "").rstrip("/")
    if "/" in rest:
        rest = rest.split("/")[0]
    if ":" in rest:
        host, port_str = rest.rsplit(":", 1)
        port = int(port_str)
    else:
        host = rest
        port = 9200
    return host, port, use_ssl


def _opensearch_client(settings: Optional[OpenSearchSettings] = None) -> OpenSearch:
    """Build a low-level OpenSearch client from settings (for index management)."""
    s = settings or get_opensearch_settings()
    host, port, use_ssl_detected = _parse_endpoint(s.endpoint)

    if s.environment == "local":
        auth = (s.user, s.password)
    else:
        credentials = boto3.Session().get_credentials()
        auth = AWS4Auth(
            credentials.access_key,
            credentials.secret_key,
            s.region,
            s.service,
            session_token=credentials.token,
        )

    return OpenSearch(
        hosts=[{"host": host, "port": port}],
        http_auth=auth,
        use_ssl=use_ssl_detected,
        verify_certs=False,
        ssl_assert_hostname=False,
        ssl_show_warn=False,
        connection_class=RequestsHttpConnection,
        timeout=s.timeout,
    )


def ensure_opensearch_tables(
    settings: Optional[OpenSearchSettings] = None,
    chunk_index_name: Optional[str] = None,
) -> None:
    """Ensure OpenSearch chunk index exists. Idempotent."""

    s = settings or get_opensearch_settings()
    client = _opensearch_client(s)
    chunk_idx = chunk_index_name or s.index_name
    try:
        if not client.indices.exists(index=chunk_idx):
            client.indices.create(index=chunk_idx, body=get_lupita_chunk_index_schema())
            log.info(f"Created OpenSearch chunk index: {chunk_idx}")
        else:
            log.debug(f"OpenSearch chunk index already exists: {chunk_idx}")
    except Exception as e:
        if "resource_already_exists_exception" in str(e):
            log.debug(f"OpenSearch chunk index already exists: {chunk_idx}")
        else:
            log.exception(f"Error ensuring chunk index {chunk_idx}")
            raise

    # Ensure hybrid search pipelines (keyword + vector weight combinations)
    try:
        ensure_search_pipelines(client)
    except Exception as e:
        log.exception("Error ensuring search pipelines {e}")
        raise

