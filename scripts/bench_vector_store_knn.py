"""Reproducible kNN/hybrid benchmark on an owned, disposable OpenSearch index.

No embedding-model calls. Reports semantic ANN recall against exact server-side
kNN separately from hybrid latency (lexical blending changes relevance ranks).
The default matrix is bounded by --max-vector-bytes for a shared local host;
skipped scenarios are explicit in the JSON, never extrapolated measurements.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import uuid4

os.environ.setdefault("GENAI_ENVIRONMENT", "test")
os.environ.setdefault("API_V0_STR", "/api/v0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from opensearchpy import OpenSearch, helpers

from src.infrastructure.persistence.vector_store.opensearch.index import (
    _INDEX_BODY,
    _SEARCH_PIPELINE_WEIGHTS,
)


def percentiles(values):
    return {f"p{p}_ms": round(float(np.percentile(values, p)), 3) for p in (50, 95, 99)}


def filters(instance="i0", generation=1):
    return [
        {"term": {"vector_store_id": instance}},
        {"term": {"vector_store_version": generation}},
        {"term": {"type": "taxonomia"}},
    ]


def ann_query(vector):
    return {
        "knn": {
            "text_embedded": {
                "vector": vector,
                "k": 5,
                "filter": {"bool": {"filter": filters()}},
            }
        }
    }


def timed_search(client, index, query, **kwargs):
    started = time.perf_counter()
    response = client.search(
        index=index, body={"size": 5, "query": query, "_source": False}, **kwargs
    )
    elapsed = 1000 * (time.perf_counter() - started)
    ids = [hit["_id"] for hit in response["hits"]["hits"]]
    if any(not key.startswith("i0g1d") for key in ids):
        raise AssertionError("generation filter leaked another generation")
    return elapsed, ids


def ingest(
    client,
    index,
    instances,
    generations,
    per_generation,
    dimensions,
    seed,
    *,
    extra=False,
    started=None,
):
    rng = np.random.default_rng(seed)

    def documents():
        for instance in range(instances):
            for generation in range(1, generations + 1):
                number = generation + 1000 if extra else generation
                for offset in range(0, per_generation, 64):
                    count = min(64, per_generation - offset)
                    vectors = rng.normal(size=(count, dimensions)).astype(np.float32)
                    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
                    for position, vector in enumerate(vectors):
                        yield {
                            "_index": index,
                            "_id": f"i{instance}g{number}d{offset+position}",
                            "_source": {
                                "type": "taxonomia",
                                "text": "Fraude en transferencia, suplantación de identidad y cambio de dispositivo.",
                                "text_embedded": vector.tolist(),
                                "vector_store_id": f"i{instance}",
                                "vector_store_version": number,
                            },
                        }
                    if started is not None:
                        started.set()

    helpers.bulk(client, documents(), chunk_size=64, request_timeout=120)


def scenario(
    client, pipeline, dimensions, instances, generations, documents, samples, seed
):
    index = f"aria-knn-bench-{uuid4().hex}"
    body = copy.deepcopy(_INDEX_BODY)
    body["settings"].update(number_of_shards=1, number_of_replicas=0)
    body["mappings"]["properties"]["text_embedded"]["dimension"] = dimensions
    try:
        client.indices.create(index=index, body=body)
        build_started = time.perf_counter()
        ingest(client, index, instances, generations, documents, dimensions, seed)
        client.indices.refresh(index=index)
        build_seconds = time.perf_counter() - build_started
        rng = np.random.default_rng(seed + 1)
        vectors = rng.normal(size=(samples, dimensions)).astype(np.float32)
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        ann_times, hybrid_times, recalls = [], [], []
        for vector in vectors:
            value = vector.tolist()
            exact = {
                "script_score": {
                    "query": {"bool": {"filter": filters()}},
                    "script": {
                        "lang": "knn",
                        "source": "knn_score",
                        "params": {
                            "field": "text_embedded",
                            "query_value": value,
                            "space_type": "cosinesimil",
                        },
                    },
                }
            }
            _, truth = timed_search(client, index, exact)
            elapsed, ids = timed_search(client, index, ann_query(value))
            ann_times.append(elapsed)
            recalls.append(len(set(ids) & set(truth)) / min(5, documents))
            hybrid = {
                "hybrid": {
                    "queries": [
                        {
                            "bool": {
                                "must": [
                                    {
                                        "match": {
                                            "text": "fraude transferencia dispositivo"
                                        }
                                    }
                                ],
                                "filter": filters(),
                            }
                        },
                        ann_query(value),
                    ]
                }
            }
            elapsed, _ = timed_search(
                client, index, hybrid, params={"search_pipeline": pipeline}
            )
            hybrid_times.append(elapsed)
        started = Event()
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                ingest,
                client,
                index,
                1,
                1,
                documents,
                dimensions,
                seed + 2,
                extra=True,
                started=started,
            )
            if not started.wait(timeout=30):
                future.result(timeout=1)
                raise RuntimeError("concurrent build did not start")
            concurrent, overlaps = [], 0
            for vector in vectors:
                overlaps += int(not future.done())
                elapsed, _ = timed_search(
                    client,
                    index,
                    {
                        "hybrid": {
                            "queries": [
                                {
                                    "bool": {
                                        "must": [
                                            {"match": {"text": "fraude transferencia"}}
                                        ],
                                        "filter": filters(),
                                    }
                                },
                                ann_query(vector.tolist()),
                            ]
                        }
                    },
                    params={"search_pipeline": pipeline},
                )
                concurrent.append(elapsed)
            future.result(timeout=120)
        stats = client.indices.stats(index=index, metric="store")
        knn = client.transport.perform_request("GET", "/_plugins/_knn/stats")
        return {
            "instances": instances,
            "generations": generations,
            "documents_per_generation": documents,
            "documents_total": instances * generations * documents,
            "dimensions": dimensions,
            "samples": samples,
            "seed": seed,
            "build_seconds": round(build_seconds, 3),
            "ann": percentiles(ann_times),
            "hybrid": percentiles(hybrid_times),
            "hybrid_during_build": percentiles(concurrent),
            "queries_overlapping_build": overlaps,
            "ann_recall_at_5": round(float(np.mean(recalls)), 6),
            "index_store_bytes": stats["_all"]["total"]["store"]["size_in_bytes"],
            "cluster_knn_graph_memory_kb": sum(
                node.get("graph_memory_usage", 0)
                for node in knn.get("nodes", {}).values()
            ),
        }
    finally:
        try:
            client.indices.delete(index=index, ignore=[404])
        except Exception as error:  # noqa: BLE001 - report, keep the original error
            print(f"Cleanup required for owned index {index}: {error}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instances", default="5,20")
    parser.add_argument("--generations", default="1,5,20,50")
    parser.add_argument("--documents-per-generation", default="200,1000")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--seed", type=int, default=30)
    parser.add_argument("--max-vector-bytes", type=int, default=128_000_000)
    parser.add_argument("--output", default="/tmp/aria-vector-knn-benchmark.json")
    args = parser.parse_args()
    client = OpenSearch(
        os.getenv("OPENSEARCH_URL", "http://localhost:9200"), timeout=120
    )
    mapping = client.indices.get_mapping(index="fraud_knowledge")
    dimensions = next(iter(mapping.values()))["mappings"]["properties"][
        "text_embedded"
    ]["dimension"]
    prefix = f"aria-knn-bench-{uuid4().hex}"
    pipelines = []
    results = {
        "server_version": client.info()["version"]["number"],
        "dimensions": dimensions,
        "index_settings": "production mapping, 1 shard, 0 replicas",
        "max_vector_bytes": args.max_vector_bytes,
        "measurements": [],
        "skipped": [],
    }
    try:
        for source, weights in _SEARCH_PIPELINE_WEIGHTS.items():
            name = f"{prefix}-{source}"
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
            pipelines.append(name)
        for instances in map(int, args.instances.split(",")):
            for documents in map(int, args.documents_per_generation.split(",")):
                for generations in map(int, args.generations.split(",")):
                    vector_bytes = instances * generations * documents * dimensions * 4
                    if vector_bytes > args.max_vector_bytes:
                        results["skipped"].append(
                            {
                                "instances": instances,
                                "generations": generations,
                                "documents_per_generation": documents,
                                "raw_vector_bytes": vector_bytes,
                                "reason": "configured shared-host memory bound",
                            }
                        )
                    else:
                        result = scenario(
                            client,
                            pipelines[1],
                            dimensions,
                            instances,
                            generations,
                            documents,
                            args.samples,
                            args.seed,
                        )
                        results["measurements"].append(result)
                        print(json.dumps(result), flush=True)
                    Path(args.output).write_text(json.dumps(results, indent=2))
    except Exception as error:
        results["error"] = str(error)
        Path(args.output).write_text(json.dumps(results, indent=2))
        raise
    finally:
        for pipeline in pipelines:
            try:
                client.transport.perform_request("DELETE", f"/_search/pipeline/{pipeline}")
            except Exception as error:  # noqa: BLE001 - report, keep the original error
                print(f"Cleanup required for owned pipeline {pipeline}: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
