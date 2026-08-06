"""
OpenSearch index schemas for chunk persistence.

Defines the index mapping for the chunk vector index, including
metadata, chunk_type, document_id, version, and content fields.
"""

from __future__ import annotations

# Default index name; can be overridden by config (e.g. genai_config.OPENSEARCH_INDEX)
CHUNK_INDEX_NAME = "lupita-vector-index"

# OpenSearch index mapping for chunks - simplified to match actual usage
# Fields actually used: source, doc_title, description, contactos
# Fields added by ParentDocumentRetriever: parent_id, chunk_index
# Hybrid search: vector_field (semantic) + text (lexical/BM25); use a hybrid query
# and optional search pipeline for score fusion (see OpenSearch hybrid search docs).
def get_lupita_chunk_index_schema() -> dict:
    return {
        "settings": {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 1,
                "knn": True,  # Required for semantic (vector) search
                "knn.algo_param.ef_search": 512,
            }
        },
        "mappings": {
            "properties": {
                # Main content: BM25 target for hybrid search (Spanish analyzer)
                "text": {
                    "type": "text",
                    "norms": True,
                    "analyzer": "spanish",
                    "search_analyzer": "spanish",
                },
                "vector_field": {
                    "type": "knn_vector",
                    "dimension": 3072, # Must match your embedding model
                    "method": {
                        "engine": "nmslib",
                        "space_type": "l2",
                        "name": "hnsw",
                        "parameters": {"ef_construction": 512, "m": 16}
                    }
                },
                "metadata": {
                    "properties": {
                        # Fields LangChain's ParentDocumentRetriever needs
                        "doc_id": {"type": "keyword"},
                        "parent_id": {"type": "keyword"},
                        "chunk_index": {"type": "integer"},
                        "source": {
                            "type": "text",
                            "analyzer": "spanish",
                            "search_analyzer": "spanish",
                            "fields": {"keyword": {"type": "keyword"}},
                        },
                        "doc_title": {
                            "type": "text",
                            "analyzer": "spanish",
                            "search_analyzer": "spanish",
                            "fields": {"keyword": {"type": "keyword"}},
                        },
                        "description": {
                            "type": "text",
                            "analyzer": "spanish",
                            "search_analyzer": "spanish",
                        },
                        "contactos": {"type": "keyword"},
                        # Semantic chunk fields
                        "chunk_type": {"type": "keyword"},
                        "document_id": {"type": "keyword"},
                        "workflow_title": {
                            "type": "text",
                            "analyzer": "spanish",
                            "fields": {"keyword": {"type": "keyword"}},
                        },
                        "workflow_hash": {"type": "keyword"},
                        "snippet_type": {"type": "keyword"},
                        "step_index": {"type": "integer"},
                        "step_count": {"type": "integer"},
                        "block_index": {"type": "integer"},
                        # Image references — list of ImageRef objects uploaded during assessment.
                        # Stored as nested so each element can be queried independently
                        # (e.g. filter by page or bucket_key without cross-element false positives).
                        # At retrieval time, read _source.metadata.image_refs directly — no
                        # JSON parsing needed.  Empty list when the chunk has no associated images.
                        "image_refs": {
                            "type": "nested",
                            "properties": {
                                "bucket_key":     {"type": "keyword"},
                                "bucket":         {"type": "keyword"},
                                "content_type":   {"type": "keyword"},
                                "page":           {"type": "integer"},
                                "insert_idx":     {"type": "integer"},
                                "context_before": {
                                    "type": "text",
                                    "analyzer": "spanish",
                                    "index": False,
                                },
                                "context_after": {
                                    "type": "text",
                                    "analyzer": "spanish",
                                    "index": False,
                                },
                            },
                        },
                    }
                }
            }
        }
    }

#text -> text2vect [text-embedding-3-large] -> list[int][1536] 
def get_faq_index_schema(index_name: str, vector_dimension: int = 1536) -> dict:
    """
    Retorna la configuración (settings y mappings) para el índice de FAQs.
    
    Args:
        index_name (str): Nombre del índice.
        vector_dimension (int): Dimensión del vector
    """
    return {
        "settings": {
            "index": {
                "knn": True,
                "knn.algo_param.ef_search": 100,
                # Configuraciones de shards y replicas
                "number_of_shards": 1, 
                "number_of_replicas": 1
            }
        },
        "mappings": {
            # True = acepta campos nuevos dinámicamente
            "dynamic": True,
            "properties": {
                # Definición del vector
                "vector_field": {
                    "type": "knn_vector",
                    "dimension": vector_dimension,
                    "method": {
                        "engine": "nmslib",
                        "space_type": "l2",
                        "name": "hnsw",
                        "parameters": {
                            "ef_construction": 512,
                            "m": 16
                        }
                    }
                },
                # Definición explícita de campos importantes
                "text": {"type": "text"},
                "created_at": {"type": "date"},
                "source": {"type": "keyword"}
            }
        }
    }