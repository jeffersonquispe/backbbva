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
from src.application.use_cases.research.delegated_research import (
    HistoryPandasResearchAgent,
    ResearchDelegationCoordinator,
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


def test_history_agent_rejects_unauthorised_columns_and_never_raises_to_workflow():
    agent = HistoryPandasResearchAgent(
        _Planner([HistoryOperation("aggregate", column="document", aggregate="count")]),
        HistoryPandasResearchConfig(enabled=True, allowed_columns=("amount",)),
    )
    result = agent.research(_history_request(), [{"amount": 4, "document": "secret"}])

    assert result.status == ResearchStatus.FAILED
    assert "column is not allowed" in result.error


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
