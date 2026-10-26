#!/usr/bin/env python3
"""Compare BM25 and embedding retrieval on the graph's golden questions."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.application.use_cases.agent.retrieve_project_context import (  # noqa: E402
    SEMANTIC_CANDIDATES,
    RetrieveProjectContextInput,
    RetrieveProjectContextUseCase,
)
from src.infrastructure.agents.embedding_project_graph_search import (  # noqa: E402
    EmbeddingProjectGraphSemanticSearch,
)
from src.infrastructure.agents.json_project_graph_repository import (  # noqa: E402
    DEFAULT_GRAPH_PATH,
    JsonProjectGraphRepository,
)

GOLDEN_PATH = ROOT / "tests/test_infrastructure/test_agents/project_graph_golden.json"
AT = 10


def ranked_metrics(ranks: list[list[str]], expected: list[set[str]]) -> tuple[float, float]:
    hits = [bool(set(items[:AT]) & wanted) for items, wanted in zip(ranks, expected, strict=True)]
    reciprocal = []
    for items, wanted in zip(ranks, expected, strict=True):
        position = next((i for i, node_id in enumerate(items[:AT], 1) if node_id in wanted), None)
        reciprocal.append(1 / position if position else 0.0)
    return sum(hits) / max(len(hits), 1), sum(reciprocal) / max(len(reciprocal), 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bm25-only",
        action="store_true",
        help="report the BM25 baseline without calling the embedding service",
    )
    args = parser.parse_args()
    repository = JsonProjectGraphRepository(DEFAULT_GRAPH_PATH)
    cases = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    expected = [set(case["expect"]) for case in cases]

    bm25 = RetrieveProjectContextUseCase(graph=repository)
    bm25_ranks: list[list[str]] = []
    for case in cases:
        bm25_ranks.append(list(bm25.execute(RetrieveProjectContextInput(
            query=case["query"], page_path=case["page"], role=case["role"], max_nodes=AT
        )).node_ids))

    print(f"Golden queries: {len(cases)} | metric cutoff: {AT}")
    bm25_recall, bm25_mrr = ranked_metrics(bm25_ranks, expected)
    print(f"BM25       recall@{AT}={bm25_recall:.3f} MRR@{AT}={bm25_mrr:.3f}")
    if args.bm25_only:
        return 0

    model = os.environ.get("EMBEDDING_MODEL", "")
    if not model:
        print("Embeddings unavailable: set EMBEDDING_MODEL to run the comparison.", file=sys.stderr)
        return 2

    from src.infrastructure.agents.factories import genai_config  # noqa: PLC0415
    from src.infrastructure.embedding.langchain import (  # noqa: PLC0415
        get_embedding_unit_of_work_factory,
    )
    from src.infrastructure.monitoring.opentelemetry import (
        get_monitoring,  # noqa: PLC0415
    )

    model = genai_config.EMBEDDING_MODEL
    semantic = EmbeddingProjectGraphSemanticSearch(
        graph=repository,
        embeddings=get_embedding_unit_of_work_factory(),
        monitoring=get_monitoring(),
        model=model,
    )
    started = time.perf_counter()
    semantic.warm()
    index_seconds = time.perf_counter() - started
    semantic_ranks = [semantic.rank(case["query"], SEMANTIC_CANDIDATES) for case in cases]
    semantic_recall, semantic_mrr = ranked_metrics(semantic_ranks, expected)

    hybrid = RetrieveProjectContextUseCase(graph=repository, semantic=semantic)
    hybrid_ranks = [
        list(hybrid.execute(RetrieveProjectContextInput(
            query=case["query"], page_path=case["page"], role=case["role"], max_nodes=AT
        )).node_ids)
        for case in cases
    ]
    hybrid_recall, hybrid_mrr = ranked_metrics(hybrid_ranks, expected)
    print(f"Embeddings index build: {index_seconds:.1f}s (model={model})")
    print(f"Embeddings recall@{AT}={semantic_recall:.3f} MRR@{AT}={semantic_mrr:.3f}")
    print(f"Hybrid     recall@{AT}={hybrid_recall:.3f} MRR@{AT}={hybrid_mrr:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
