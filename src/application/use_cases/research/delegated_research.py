from __future__ import annotations

import contextvars
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any

from src.application.dtos.research_dtos import (
    ResearchFinding,
    ResearchRequest,
    ResearchResult,
    ResearchSource,
    ResearchStatus,
)
from src.application.ports.configuration_port import VectorStoreResearchConfig
from src.application.ports.monitoring_port import (
    MonitoringPort,
    ResearchCallOutcome,
)
from src.application.ports.research_port import (
    ResearchAgent,
    VectorStoreRetriever,
)


class VectorStoreResearchAgent:
    """Bounded semantic retrieval; the retriever owns store/version scoping."""

    def __init__(
        self, retriever: VectorStoreRetriever, config: VectorStoreResearchConfig
    ) -> None:
        self._retriever = retriever
        self._config = config

    def research(self, request: ResearchRequest) -> ResearchResult:
        if request.source != ResearchSource.VECTOR_STORE:
            return ResearchResult(
                ResearchSource.VECTOR_STORE,
                ResearchStatus.SKIPPED,
                error="wrong research source",
            )
        if not self._config.enabled or not self._config.vector_store_instance_id:
            return ResearchResult(
                ResearchSource.VECTOR_STORE,
                ResearchStatus.SKIPPED,
                error="vector store research is disabled or unconfigured",
            )
        try:
            findings: list[ResearchFinding] = []
            trace: list[dict[str, Any]] = []
            for asset_type in self._config.allowed_asset_types:
                hits = self._retriever.search(
                    request.question,
                    asset_type=asset_type,
                    top_k=self._config.max_documents_per_query,
                )
                kept = [
                    hit
                    for hit in hits
                    if float(hit.get("score", 0)) >= self._config.similarity_threshold
                ]
                trace.append({"asset_type": asset_type, "hits": len(kept)})
                for hit in kept:
                    if len(findings) >= self._config.max_result_items:
                        break
                    findings.append(
                        ResearchFinding(
                            metric="vector_store_match",
                            value=hit.get("id"),
                            evidence=str(hit.get("text", ""))[:1_000],
                            metadata={
                                "asset_type": asset_type,
                                "score": hit.get("score"),
                            },
                        )
                    )
                if len(findings) >= self._config.max_result_items:
                    break
            return ResearchResult(
                ResearchSource.VECTOR_STORE, ResearchStatus.EXECUTED, findings, trace
            )
        except Exception as exc:  # noqa: BLE001 - convert retriever failures to result
            return ResearchResult(
                ResearchSource.VECTOR_STORE, ResearchStatus.FAILED, error=str(exc)
            )


class TimeBoundedResearchAgent:
    """Caps one research call at ``timeout_seconds`` (``<= 0`` = no cap).

    A call that overruns comes back as ``FAILED`` so the caller carries on
    with the evidence it already has. Python can't kill a thread, so the
    overrunning call keeps going in the background until it returns; its
    result is discarded.
    """

    def __init__(
        self,
        agent: ResearchAgent,
        source: ResearchSource,
        timeout_seconds: float,
        monitoring: MonitoringPort | None = None,
    ) -> None:
        self._agent = agent
        self._source = source
        self._timeout_seconds = timeout_seconds
        # T3 aria.research.calls: every call (both sources go through this
        # wrapper) is counted as ok / failed / timeout. SKIPPED is not a
        # call to the backend and is not counted.
        self._monitoring = monitoring

    def research(self, request: ResearchRequest) -> ResearchResult:
        try:
            result, timed_out = self._research(request)
        except Exception:
            self._record(ResearchCallOutcome.FAILED)
            raise
        if timed_out:
            self._record(ResearchCallOutcome.TIMEOUT)
        elif result.status == ResearchStatus.EXECUTED:
            self._record(ResearchCallOutcome.OK)
        elif result.status == ResearchStatus.FAILED:
            self._record(ResearchCallOutcome.FAILED)
        return result

    def _research(self, request: ResearchRequest) -> tuple[ResearchResult, bool]:
        """(result, whether the call overran timeout_seconds)."""
        if self._timeout_seconds <= 0:
            return self._agent.research(request), False
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="research-tool")
        # copy_context: the thread keeps the caller's OpenTelemetry span.
        future = executor.submit(
            contextvars.copy_context().run, self._agent.research, request
        )
        try:
            return future.result(timeout=self._timeout_seconds), False
        except FutureTimeoutError:
            return ResearchResult(
                self._source,
                ResearchStatus.FAILED,
                error=f"timeout: la investigación no respondió en {self._timeout_seconds:g} s",
            ), True
        finally:
            executor.shutdown(wait=False)

    def _record(self, outcome: ResearchCallOutcome) -> None:
        if self._monitoring is not None:
            self._monitoring.record_research_call(str(self._source), outcome)


class ResearchDelegationCoordinator:
    """Executes enabled research in order only while the caller is inconclusive.

    ``is_inconclusive`` and ``accept`` keep final decision logic in the stage
    use case/workflow, while this class centrally enforces the delegation gate.
    """

    def __init__(self, agents: dict[ResearchSource, ResearchAgent]) -> None:
        self._agents = agents

    def delegate(
        self,
        requests: list[ResearchRequest],
        *,
        is_inconclusive: Callable[[], bool],
        accept: Callable[[ResearchResult], None],
    ) -> list[ResearchResult]:
        results: list[ResearchResult] = []
        for request in requests:
            if not is_inconclusive():
                break
            agent = self._agents.get(request.source)
            if agent is None:
                result = ResearchResult(
                    request.source,
                    ResearchStatus.SKIPPED,
                    error="research agent is unavailable",
                )
            else:
                result = agent.research(request)
            results.append(result)
            accept(result)
        return results
