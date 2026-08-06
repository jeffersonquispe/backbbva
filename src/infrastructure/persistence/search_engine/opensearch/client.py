from __future__ import annotations

import logging
from typing import Any, Protocol

import boto3
from langchain_community.vectorstores.opensearch_vector_search import (
    OpenSearchVectorSearch,
)
from opensearchpy import RequestsHttpConnection
from requests_aws4auth import AWS4Auth

from src.infrastructure.core.config import genai_config

log = logging.getLogger(__name__)

# Field name used for embeddings in the index; excluded from search _source to reduce payload.
VECTOR_FIELD_NAME = "vector_field"


class EmbeddingFunctionProvider(Protocol):
    def get(self) -> Any:
        """Return the embedding callable expected by LangChain."""


class _SourceExcludeClientWrapper:
    """
    Wraps an OpenSearch client so search() requests exclude large fields from _source.
    Used to avoid returning embedding vectors in search results (saves bandwidth and memory).
    """

    def __init__(self, client: Any, exclude_fields: list[str] | None = None):
        self._client = client
        self._exclude = exclude_fields or [VECTOR_FIELD_NAME]

    def search(self, index: str | None = None, body: dict | None = None, **kwargs: Any) -> Any:
        body = dict(body) if body else {}
        if "_source" not in body:
            body["_source"] = {"exclude": self._exclude}
        else:
            existing = body["_source"]
            if isinstance(existing, dict) and "exclude" in existing:
                body["_source"] = {
                    **existing,
                    "exclude": list(set(existing["exclude"]) | set(self._exclude)),
                }
            else:
                body["_source"] = {"exclude": self._exclude}
        index = kwargs.pop("index", index)
        return self._client.search(index=index, body=body, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def build_vectorstore(embeddings: EmbeddingFunctionProvider) -> OpenSearchVectorSearch:
    """
    Create an OpenSearchVectorSearch instance using project configuration.

    This is a thin, reusable factory independent from business logic.
    """
    service = genai_config.OPENSEARCH_SERVICE
    region = genai_config.OPENSEARCH_REGION
    index_name = genai_config.OPENSEARCH_INDEX
    endpoint = genai_config.OPENSEARCH_ENDPOINT
    if genai_config.GENAI_ENVIRONMENT == "local":
        log.debug("OpenSearch: using local credentials")
        user = genai_config.OPENSEARCH_USER
        password = genai_config.OPENSEARCH_PASSWORD
        auth = (user, password)
    else:
        log.debug("OpenSearch: using AWS OpenSearch credentials")
        credentials = boto3.Session().get_credentials()
        auth = AWS4Auth(
            credentials.access_key,
            credentials.secret_key,
            region,
            service,
            session_token=credentials.token,
        )

    use_ssl = endpoint.strip().lower().startswith("https://")

    vectorstore = OpenSearchVectorSearch(
        index_name=index_name,
        embedding_function=embeddings.get(),
        opensearch_url=endpoint,
        http_auth=auth,
        connection_class=RequestsHttpConnection,
        use_ssl=use_ssl,
        verify_certs=False,
        ssl_assert_hostname=False,
        ssl_show_warn=False,
        timeout=genai_config.OPENSEARCH_TIMEOUT,
        search_type="script_scoring",
        space_type="l2",
        bulk_size=3000,
    )
    vectorstore.client = _SourceExcludeClientWrapper(
        vectorstore.client, exclude_fields=[VECTOR_FIELD_NAME]
    )
    return vectorstore
