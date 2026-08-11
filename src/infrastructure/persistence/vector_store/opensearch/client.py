from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse

import boto3
from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection

from src.infrastructure.core.config import genai_config


@lru_cache
def get_opensearch_client() -> OpenSearch:
    parsed = urlparse(genai_config.OPENSEARCH_ENDPOINT)
    use_ssl = parsed.scheme == "https"
    host = {
        "host": parsed.hostname,
        "port": parsed.port or (443 if use_ssl else 80),
    }

    if genai_config.OPENSEARCH_AUTH_MODE == "basic":
        http_auth = (
            genai_config.OPENSEARCH_USERNAME,
            genai_config.OPENSEARCH_PASSWORD,
        )
    elif genai_config.OPENSEARCH_AUTH_MODE == "aws_sigv4":
        credentials = boto3.Session().get_credentials()
        http_auth = AWSV4SignerAuth(credentials, genai_config.OPENSEARCH_REGION, "es")
    else:
        raise ValueError(
            "unknown OPENSEARCH_AUTH_MODE: " f"{genai_config.OPENSEARCH_AUTH_MODE!r}"
        )

    return OpenSearch(
        hosts=[host],
        http_auth=http_auth,
        use_ssl=use_ssl,
        verify_certs=genai_config.OPENSEARCH_VERIFY_CERTS,
        connection_class=RequestsHttpConnection,
    )
