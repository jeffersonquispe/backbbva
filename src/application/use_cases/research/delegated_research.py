from __future__ import annotations

import contextvars
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import asdict, is_dataclass
from typing import Any

import pandas as pd

from src.application.dtos.research_dtos import (
    HistoryOperation,
    ResearchFinding,
    ResearchRequest,
    ResearchResult,
    ResearchSource,
    ResearchStatus,
)
from src.application.ports.configuration_port import (
    HistoryPandasResearchConfig,
    VectorStoreResearchConfig,
)
from src.application.ports.monitoring_port import (
    MonitoringPort,
    ResearchCallOutcome,
)
from src.application.ports.research_port import (
    HistoryResearchPlanner,
    ResearchAgent,
    VectorStoreRetriever,
)


class HistoryPandasResearchAgent:
    """Runs a deliberately small, declarative subset of dataframe analysis.

    This is intentionally not a Python sandbox.  The planner can choose a
    question and a sequence of known operations, while this executor owns the
    data boundary, allowed columns and response shape.
    """

    _FILTER_OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte", "in"}
    _AGGREGATES = {"count", "sum", "mean", "median", "min", "max", "nunique"}

    def __init__(
        self,
        planner: HistoryResearchPlanner,
        config: HistoryPandasResearchConfig,
        history_provider: Callable[[ResearchRequest], Iterable[dict[str, Any]]] | None = None,
    ) -> None:
        self._planner = planner
        self._config = config
        self._history_provider = history_provider

    def research(
        self,
        request: ResearchRequest,
        history: Iterable[dict[str, Any]] | None = None,
    ) -> ResearchResult:
        if request.source != ResearchSource.HISTORY_PANDAS:
            return self._skipped("wrong research source")
        if not self._config.enabled:
            return self._skipped("history research is disabled")
        try:
            if history is None:
                if self._history_provider is None:
                    raise ValueError("history data was not supplied")
                history = self._history_provider(request)
            rows = [
                asdict(row) if is_dataclass(row) else row
                for row in list(history)[: self._config.max_history_rows]
            ]
            frame = pd.DataFrame(rows)
            if self._config.allowed_columns:
                permitted = [c for c in self._config.allowed_columns if c in frame.columns]
                frame = frame.loc[:, permitted]
            operations = self._planner.plan(request)
            if len(operations) > self._config.max_analysis_operations:
                raise ValueError("history analysis operation budget exceeded")

            findings: list[ResearchFinding] = []
            trace: list[dict[str, Any]] = [{"rows_considered": len(frame)}]
            working = frame.copy(deep=True)
            for operation in operations:
                if operation.name not in self._config.allowed_operations:
                    raise ValueError(f"operation is not allowed: {operation.name}")
                missing = [
                    column for column in (operation.column, operation.group_by)
                    if column and column not in working.columns
                ]
                if missing:
                    # Column outside the configured selection (or absent
                    # from this history): skip just this operation rather
                    # than failing the whole investigation.
                    trace.append({"operation": asdict(operation), "skipped": f"columns not available: {missing}"})
                    continue
                working, finding = self._execute(working, operation)
                trace.append({"operation": asdict(operation)})
                if finding is not None:
                    findings.append(finding)
            return ResearchResult(
                source=ResearchSource.HISTORY_PANDAS,
                status=ResearchStatus.EXECUTED,
                findings=findings,
                trace=trace,
            )
        except Exception as exc:  # failure must not fail the alert workflow
            return ResearchResult(
                source=ResearchSource.HISTORY_PANDAS,
                status=ResearchStatus.FAILED,
                error=str(exc),
            )

    def _execute(
        self, frame: pd.DataFrame, op: HistoryOperation
    ) -> tuple[pd.DataFrame, ResearchFinding | None]:
        self._column_allowed(op.column)
        self._column_allowed(op.group_by)
        if op.name == "filter":
            if not op.column or op.operator not in self._FILTER_OPERATORS:
                raise ValueError("invalid filter")
            series = frame[op.column]
            checks = {
                "eq": series == op.value, "ne": series != op.value,
                "gt": series > op.value, "gte": series >= op.value,
                "lt": series < op.value, "lte": series <= op.value,
                "in": series.isin(op.value if isinstance(op.value, list) else [op.value]),
            }
            filtered = frame.loc[checks[op.operator]].copy()
            return filtered, ResearchFinding(
                metric="filtered_rows", value=len(filtered),
                evidence=f"{len(filtered)} rows match {op.column} {op.operator}",
            )
        if op.name == "aggregate":
            if not op.column or op.aggregate not in self._AGGREGATES:
                raise ValueError("invalid aggregate")
            if op.aggregate == "count":
                value: Any = int(frame[op.column].count())
            elif op.aggregate == "nunique":
                value = int(frame[op.column].nunique(dropna=True))
            else:
                value = getattr(pd.to_numeric(frame[op.column], errors="coerce"), op.aggregate)()
                value = None if pd.isna(value) else float(value)
            return frame, ResearchFinding(
                metric=f"{op.aggregate}_{op.column}", value=value,
                evidence=f"{op.aggregate} calculated over {len(frame)} history rows",
            )
        if op.name == "distribution":
            if not op.column:
                raise ValueError("distribution requires a column")
            counts = frame[op.column].value_counts(dropna=False).head(10)
            value = [{"value": str(key), "count": int(count)} for key, count in counts.items()]
            return frame, ResearchFinding("distribution_" + op.column, value, "Top values in history")
        if op.name == "group_by":
            if not op.group_by:
                raise ValueError("group_by requires a grouping column")
            if op.column and op.aggregate in {"sum", "mean", "median", "min", "max"}:
                values = pd.to_numeric(frame[op.column], errors="coerce")
                grouped = values.groupby(frame[op.group_by]).agg(op.aggregate).head(10)
            else:
                grouped = frame.groupby(op.group_by, dropna=False).size().head(10)
            value = [{"group": str(key), "value": float(count)} for key, count in grouped.items()]
            return frame, ResearchFinding(
                metric=f"group_by_{op.group_by}", value=value,
                evidence="Grouped historical values",
            )
        if op.name == "comparison":
            if not op.column or op.current_value is None:
                raise ValueError("comparison requires column and current_value")
            numeric = pd.to_numeric(frame[op.column], errors="coerce").dropna()
            median = numeric.median()
            if pd.isna(median):
                raise ValueError("comparison column has no numeric values")
            ratio = None if median == 0 else float(op.current_value) / float(median)
            return frame, ResearchFinding(
                metric=f"current_vs_median_{op.column}",
                value={"current": op.current_value, "median": float(median), "ratio": ratio},
                evidence="Current value compared to historical median",
            )
        if op.name == "outlier":
            if not op.column or op.current_value is None:
                raise ValueError("outlier requires column and current_value")
            numeric = pd.to_numeric(frame[op.column], errors="coerce").dropna()
            q1, q3 = numeric.quantile([0.25, 0.75])
            iqr = q3 - q1
            lower, upper = float(q1 - 1.5 * iqr), float(q3 + 1.5 * iqr)
            is_outlier = float(op.current_value) < lower or float(op.current_value) > upper
            return frame, ResearchFinding(
                metric=f"outlier_{op.column}", value=is_outlier,
                evidence=f"IQR bounds are [{lower}, {upper}]",
                metadata={"lower_bound": lower, "upper_bound": upper},
            )
        if op.name == "trend":
            if not op.column or not op.group_by:
                raise ValueError("trend requires a date column and group_by frequency")
            dates = pd.to_datetime(frame[op.column], errors="coerce", utc=True)
            counts = dates.dropna().dt.to_period(op.group_by).value_counts().sort_index()
            value = [{"period": str(k), "count": int(v)} for k, v in counts.head(20).items()]
            return frame, ResearchFinding("trend_" + op.column, value, "Historical frequency trend")
        raise ValueError(f"unsupported operation: {op.name}")

    def _column_allowed(self, column: str | None) -> None:
        if column and self._config.allowed_columns and column not in self._config.allowed_columns:
            raise ValueError(f"column is not allowed: {column}")

    def _skipped(self, reason: str) -> ResearchResult:
        return ResearchResult(ResearchSource.HISTORY_PANDAS, ResearchStatus.SKIPPED, error=reason)


class VectorStoreResearchAgent:
    """Bounded semantic retrieval; the retriever owns store/version scoping."""

    def __init__(self, retriever: VectorStoreRetriever, config: VectorStoreResearchConfig) -> None:
        self._retriever = retriever
        self._config = config

    def research(self, request: ResearchRequest) -> ResearchResult:
        if request.source != ResearchSource.VECTOR_STORE:
            return ResearchResult(ResearchSource.VECTOR_STORE, ResearchStatus.SKIPPED, error="wrong research source")
        if not self._config.enabled or not self._config.vector_store_instance_id:
            return ResearchResult(ResearchSource.VECTOR_STORE, ResearchStatus.SKIPPED, error="vector store research is disabled or unconfigured")
        try:
            findings: list[ResearchFinding] = []
            trace: list[dict[str, Any]] = []
            for asset_type in self._config.allowed_asset_types:
                hits = self._retriever.search(request.question, asset_type=asset_type, top_k=self._config.max_documents_per_query)
                kept = [hit for hit in hits if float(hit.get("score", 0)) >= self._config.similarity_threshold]
                trace.append({"asset_type": asset_type, "hits": len(kept)})
                for hit in kept:
                    if len(findings) >= self._config.max_result_items:
                        break
                    findings.append(ResearchFinding(
                        metric="vector_store_match", value=hit.get("id"),
                        evidence=str(hit.get("text", ""))[:1_000],
                        metadata={"asset_type": asset_type, "score": hit.get("score")},
                    ))
                if len(findings) >= self._config.max_result_items:
                    break
            return ResearchResult(ResearchSource.VECTOR_STORE, ResearchStatus.EXECUTED, findings, trace)
        except Exception as exc:
            return ResearchResult(ResearchSource.VECTOR_STORE, ResearchStatus.FAILED, error=str(exc))


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
        future = executor.submit(contextvars.copy_context().run, self._agent.research, request)
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
                result = ResearchResult(request.source, ResearchStatus.SKIPPED, error="research agent is unavailable")
            else:
                result = agent.research(request)
            results.append(result)
            accept(result)
        return results
