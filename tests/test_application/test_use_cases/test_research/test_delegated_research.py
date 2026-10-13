import threading

from src.application.dtos.research_dtos import (
    HistoryOperation,
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
    MonitoringSpan,
    ResearchCallOutcome,
)
from src.infrastructure.workflows.celery.history_pandas_research import HistoryPandasResearchAgent
from src.application.use_cases.research.delegated_research import (
    ResearchDelegationCoordinator,
    TimeBoundedResearchAgent,
    VectorStoreResearchAgent,
)


class _Planner:
    def __init__(self, operations):
        self.operations = operations

    def plan(self, request):
        return self.operations


class _Retriever:
    def __init__(self):
        self.calls = []

    def search(self, query, *, asset_type, top_k):
        self.calls.append((query, asset_type, top_k))
        return [
            {"id": "keep", "text": "relevant modus", "score": 0.91},
            {"id": "drop", "text": "weak", "score": 0.3},
        ]


def _history_request():
    return ResearchRequest(ResearchSource.HISTORY_PANDAS, "is amount unusual?")


def test_history_agent_executes_only_declared_operations_and_returns_audit_trace():
    agent = HistoryPandasResearchAgent(
        _Planner([
            HistoryOperation("filter", column="channel", operator="eq", value="app"),
            HistoryOperation("comparison", column="amount", current_value=900),
            HistoryOperation("outlier", column="amount", current_value=900),
        ]),
        HistoryPandasResearchConfig(
            enabled=True,
            allowed_columns=("channel", "amount"),
            max_analysis_operations=3,
        ),
    )
    result = agent.research(_history_request(), [
        {"channel": "app", "amount": 100}, {"channel": "app", "amount": 200},
        {"channel": "web", "amount": 10000},
    ])

    assert result.status == ResearchStatus.EXECUTED
    assert [f.metric for f in result.findings] == [
        "filtered_rows", "current_vs_median_amount", "outlier_amount"
    ]
    assert result.findings[1].value["median"] == 150
    assert len(result.trace) == 4


def test_history_agent_skips_operations_on_unauthorised_columns_without_exposing_them():
    agent = HistoryPandasResearchAgent(
        _Planner([
            HistoryOperation("aggregate", column="document", aggregate="count"),
            HistoryOperation("aggregate", column="amount", aggregate="sum"),
        ]),
        HistoryPandasResearchConfig(enabled=True, allowed_columns=("amount",)),
    )
    result = agent.research(_history_request(), [{"amount": 4, "document": "secret"}])

    # The column selection is a scope, not an error: operations outside it
    # are skipped, the rest still run, and the value never leaks.
    assert result.status == ResearchStatus.EXECUTED
    assert [finding.metric for finding in result.findings] == ["sum_amount"]
    assert "skipped" in result.trace[1]
    assert "secret" not in repr(result)


def test_history_agent_rejects_operation_budget():
    agent = HistoryPandasResearchAgent(
        _Planner([HistoryOperation("aggregate", column="amount", aggregate="count")] * 2),
        HistoryPandasResearchConfig(enabled=True, allowed_columns=("amount",), max_analysis_operations=1),
    )
    assert agent.research(_history_request(), [{"amount": 3}]).status == ResearchStatus.FAILED


def test_vector_agent_filters_hits_and_keeps_source_trace():
    retriever = _Retriever()
    agent = VectorStoreResearchAgent(retriever, VectorStoreResearchConfig(
        enabled=True, vector_store_instance_id="vs-1", allowed_asset_types=("modus_operandi",),
    ))
    result = agent.research(ResearchRequest(ResearchSource.VECTOR_STORE, "new beneficiary"))

    assert result.status == ResearchStatus.EXECUTED
    assert len(result.findings) == 1
    assert result.findings[0].metadata == {"asset_type": "modus_operandi", "score": 0.91}
    assert retriever.calls == [("new beneficiary", "modus_operandi", 8)]


class _Agent:
    def __init__(self, source):
        self.source = source
        self.calls = 0

    def research(self, request):
        self.calls += 1
        return ResearchResult(self.source, ResearchStatus.EXECUTED)


def test_coordinator_stops_after_evidence_becomes_conclusive():
    vector = _Agent(ResearchSource.VECTOR_STORE)
    pandas = _Agent(ResearchSource.HISTORY_PANDAS)
    coordinator = ResearchDelegationCoordinator({
        ResearchSource.VECTOR_STORE: vector, ResearchSource.HISTORY_PANDAS: pandas,
    })
    state = {"unknown": True}
    results = coordinator.delegate(
        [ResearchRequest(ResearchSource.VECTOR_STORE, "q"), ResearchRequest(ResearchSource.HISTORY_PANDAS, "q")],
        is_inconclusive=lambda: state["unknown"],
        accept=lambda result: state.update(unknown=False),
    )

    assert len(results) == 1
    assert vector.calls == 1
    assert pandas.calls == 0


class _SlowAgent:
    def __init__(self, release):
        self.release = release

    def research(self, request):
        self.release.wait(5)
        return ResearchResult(request.source, ResearchStatus.EXECUTED)


def test_time_bounded_agent_fails_the_call_when_the_call_overruns():
    release = threading.Event()
    agent = TimeBoundedResearchAgent(_SlowAgent(release), ResearchSource.VECTOR_STORE, 0.05)

    result = agent.research(ResearchRequest(ResearchSource.VECTOR_STORE, "q"))
    release.set()

    assert result.status == ResearchStatus.FAILED
    assert result.source == ResearchSource.VECTOR_STORE
    assert "timeout" in result.error


def test_time_bounded_agent_returns_the_result_within_the_limit():
    release = threading.Event()
    release.set()
    agent = TimeBoundedResearchAgent(_SlowAgent(release), ResearchSource.VECTOR_STORE, 5)

    result = agent.research(ResearchRequest(ResearchSource.VECTOR_STORE, "q"))

    assert result.status == ResearchStatus.EXECUTED


def test_time_bounded_agent_without_limit_calls_through():
    release = threading.Event()
    release.set()
    agent = TimeBoundedResearchAgent(_SlowAgent(release), ResearchSource.HISTORY_PANDAS, 0)

    result = agent.research(ResearchRequest(ResearchSource.HISTORY_PANDAS, "q"))

    assert result.status == ResearchStatus.EXECUTED


# --- T3: aria.research.calls producer ------------------------------------------


class _NoopSpan(MonitoringSpan):
    def write_input(self, data): ...
    def write_result(self, data): ...
    def write_inner_logs(self, entries): ...
    def write_operation_metas(self, metadata): ...
    def record_dependency(self, name, kind, metadata=None): ...
    def finish(self, error=None): ...


class RecordingResearchMonitoring(MonitoringPort):
    def __init__(self):
        self.research_calls: list[tuple[str, ResearchCallOutcome]] = []

    def start(self, operation_name, operation_type, metadata=None):
        return _NoopSpan()

    def record_research_call(self, source, outcome):
        self.research_calls.append((source, outcome))


class _StatusAgent:
    def __init__(self, status=None, raises=False):
        self._status = status
        self._raises = raises

    def research(self, request):
        if self._raises:
            raise RuntimeError("opensearch down")
        return ResearchResult(request.source, self._status)


def test_time_bounded_agent_records_ok_failed_and_timeout_calls():
    monitoring = RecordingResearchMonitoring()
    request = ResearchRequest(ResearchSource.VECTOR_STORE, "q")

    TimeBoundedResearchAgent(
        _StatusAgent(ResearchStatus.EXECUTED), ResearchSource.VECTOR_STORE, 5, monitoring
    ).research(request)
    TimeBoundedResearchAgent(
        _StatusAgent(ResearchStatus.FAILED), ResearchSource.VECTOR_STORE, 0, monitoring
    ).research(request)
    release = threading.Event()
    timed_out = TimeBoundedResearchAgent(
        _SlowAgent(release), ResearchSource.VECTOR_STORE, 0.05, monitoring
    ).research(request)
    release.set()

    # Behaviour unchanged: a timeout still comes back as FAILED.
    assert timed_out.status == ResearchStatus.FAILED
    assert monitoring.research_calls == [
        ("vector_store", ResearchCallOutcome.OK),
        ("vector_store", ResearchCallOutcome.FAILED),
        ("vector_store", ResearchCallOutcome.TIMEOUT),
    ]


def test_time_bounded_agent_records_a_raising_call_as_failed_and_skips_are_not_calls():
    monitoring = RecordingResearchMonitoring()
    request = ResearchRequest(ResearchSource.HISTORY_PANDAS, "q")

    try:
        TimeBoundedResearchAgent(
            _StatusAgent(raises=True), ResearchSource.HISTORY_PANDAS, 0, monitoring
        ).research(request)
    except RuntimeError:
        pass
    TimeBoundedResearchAgent(
        _StatusAgent(ResearchStatus.SKIPPED), ResearchSource.HISTORY_PANDAS, 0, monitoring
    ).research(request)

    assert monitoring.research_calls == [
        ("history_pandas", ResearchCallOutcome.FAILED)
    ]
