"""Compare Spanish analyzers on actual Library search documents and 30 curated queries.

Uses the Library documents' stored embeddings and one batch of real embeddings
for the queries. Both analyzers search identical vectors with the same hybrid
weights. Only disposable owned indices are changed; production is never reindexed.
"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("GENAI_ENVIRONMENT", "local")
os.environ.setdefault("API_V0_STR", "/api/v0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opensearchpy import OpenSearch, helpers

from src.infrastructure.core.config import genai_config
from src.infrastructure.embedding.langchain import get_embedding_unit_of_work_factory
from src.infrastructure.monitoring.opentelemetry import get_monitoring
from src.infrastructure.persistence.vector_store.opensearch.index import _INDEX_BODY

GOLDEN = {
    "Robo físico": ["hurto de celular", "robo tarjeta coaccion", "robo fisico", "hurto tarjeta", "coacción cliente"],
    "Estafa": ["ingenieria social", "cliente engaño operación", "estafas transferencias", "autorizar operación engaño", "estafa canales digitales"],
    "Suplantación": ["suplantacion identidad", "tercero identidad cliente", "identidades suplantadas", "suplantación alertas", "persona suplantada"],
    "Malware": ["malware rat", "acceso remoto celular", "control remoto dispositivo", "RAT emulador", "malware bancario"],
    "Cambiazo": ["cambiazo tarjetas", "cambio tarjeta cajero", "tarjeta comercio cambio", "tarjetas intercambiadas", "cambiazo de tarjeta"],
    "Revisión": ["pharming robo celular", "alerta confianza baja", "adversarial objeta clasificación", "revision fraude pipeline", "revisión casos no automatizados"],
}


def main():
    client = OpenSearch(os.getenv("OPENSEARCH_URL", "http://localhost:9200"), timeout=120)
    response = client.search(index="fraud_knowledge", body={"size": 1000, "query": {"match_all": {}}})
    sources = {hit["_source"]["text"]: hit["_source"] for hit in response["hits"]["hits"]}
    corpus = list(sources.values())
    queries = [(label, query) for label, values in GOLDEN.items() for query in values]
    for label in GOLDEN:
        if not any(doc["text"].startswith(label) for doc in corpus):
            raise RuntimeError(f"Library golden category is absent: {label}")
    cache = Path("/tmp/aria-vector-spanish-query-vectors.json")
    texts = [query for _, query in queries]
    if cache.exists() and json.loads(cache.read_text()).get("queries") == texts:
        vectors = json.loads(cache.read_text())["vectors"]
    else:
        uow = get_embedding_unit_of_work_factory().create(model=genai_config.EMBEDDING_MODEL,
            monitoring=get_monitoring(), operation_name="vector_store_spanish_benchmark")
        vectors = uow.embed(texts).vectors
        cache.write_text(json.dumps({"queries": texts, "vectors": vectors}))
    dimensions = len(corpus[0]["text_embedded"])
    if any(len(v) != dimensions for v in vectors):
        raise RuntimeError("Query and stored embedding dimensions differ")
    owned = []
    results = {"server_version": client.info()["version"]["number"], "corpus_documents": len(corpus),
        "queries": 30, "dimensions": dimensions, "query_source": "curated queries against six real local Library categories, not production traffic",
        "embedding_model": genai_config.EMBEDDING_MODEL, "analyzers": {}}
    try:
        for variant in ("spanish", "folded_protected_spanish"):
            index = f"aria-spanish-bench-{uuid4().hex}"
            owned.append(index)
            body = copy.deepcopy(_INDEX_BODY)
            body["settings"].update(number_of_shards=1, number_of_replicas=0)
            body["mappings"]["properties"]["text_embedded"]["dimension"] = dimensions
            if variant != "spanish":
                body["settings"]["analysis"] = {"filter": {
                    "es_stop": {"type": "stop", "stopwords": "_spanish_"},
                    "es_keywords": {"type": "keyword_marker", "keywords": ["sim", "swap", "pse", "nequi", "vishing", "rat", "pharming", "biocatch"]},
                    "es_light": {"type": "stemmer", "language": "light_spanish"}},
                    "analyzer": {variant: {"type": "custom", "tokenizer": "standard", "filter": ["lowercase", "asciifolding", "es_stop", "es_keywords", "es_light"]}}}
                body["mappings"]["properties"]["text"]["analyzer"] = variant
            client.indices.create(index=index, body=body)
            helpers.bulk(client, [{"_index": index, "_id": str(i), "_source": doc} for i, doc in enumerate(corpus)], refresh=True)
            tokens = client.indices.analyze(index=index, body={"analyzer": variant, "text": "Transferencias, suplantación y suplantacion: SIM swap, PSE, Nequi, RAT y vishing."})
            by_kind = {"bm25": [], "hybrid": []}
            details = []
            for (label, query), vector in zip(queries, vectors, strict=True):
                for kind in by_kind:
                    q = {"match": {"text": query}} if kind == "bm25" else {"hybrid": {"queries": [
                        {"match": {"text": query}}, {"knn": {"text_embedded": {"vector": vector, "k": 5}}}]}}
                    kwargs = {} if kind == "bm25" else {"params": {"search_pipeline": "fraud_knowledge_hybrid_50_50"}}
                    hits = client.search(index=index, body={"size": 5, "query": q, "_source": ["text"]}, **kwargs)["hits"]["hits"]
                    rank = next((i+1 for i, hit in enumerate(hits) if hit["_source"]["text"].startswith(label)), None)
                    by_kind[kind].append(1/rank if rank else 0)
                    details.append({"query": query, "expected_category": label, "kind": kind, "rank": rank})
            results["analyzers"][variant] = {"tokens": [t["token"] for t in tokens["tokens"]],
                **{kind: {"mrr_at_5": round(sum(scores)/len(scores), 6), "hit_at_5": sum(s>0 for s in scores)/len(scores)} for kind, scores in by_kind.items()},
                "ranks": details}
        Path("/tmp/aria-vector-spanish-benchmark.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(json.dumps({k: {metric: value for metric, value in v.items() if metric != "ranks"} for k, v in results["analyzers"].items()}, ensure_ascii=False, indent=2))
    finally:
        for index in owned:
            client.indices.delete(index=index, ignore=[404])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
