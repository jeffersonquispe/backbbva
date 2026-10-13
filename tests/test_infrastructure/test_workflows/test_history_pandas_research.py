from src.application.dtos.research_dtos import (
    HistoryOperation,
    ResearchRequest,
    ResearchSource,
    ResearchStatus,
)
from src.domain.configurations.entities import (
    HistoryPandasResearchConfig,
)
from src.infrastructure.workflows.celery.history_pandas_research import (
    HistoryPandasResearchAgent,
)


class _Planner:
    def __init__(self, operations):
        self.operations = operations

    def plan(self, request):
        return self.operations


def _history_request():
    return ResearchRequest(ResearchSource.HISTORY_PANDAS, "is amount unusual?")


def test_history_agent_executes_only_declared_operations_and_returns_audit_trace():
    agent = HistoryPandasResearchAgent(
        _Planner(
            [
                HistoryOperation(
                    "filter", column="channel", operator="eq", value="app"
                ),
                HistoryOperation("comparison", column="amount", current_value=900),
                HistoryOperation("outlier", column="amount", current_value=900),
            ]
        ),
        HistoryPandasResearchConfig(
            enabled=True,
            allowed_columns=("channel", "amount"),
            max_analysis_operations=3,
        ),
    )
    result = agent.research(
        _history_request(),
        [
            {"channel": "app", "amount": 100},
            {"channel": "app", "amount": 200},
            {"channel": "web", "amount": 10000},
        ],
    )

    assert result.status == ResearchStatus.EXECUTED
    assert [f.metric for f in result.findings] == [
        "filtered_rows",
        "current_vs_median_amount",
        "outlier_amount",
    ]
    assert result.findings[1].value["median"] == 150
    assert len(result.trace) == 4


def test_history_agent_skips_operations_on_unauthorised_columns_without_exposing_them():
    agent = HistoryPandasResearchAgent(
        _Planner(
            [
                HistoryOperation("aggregate", column="document", aggregate="count"),
                HistoryOperation("aggregate", column="amount", aggregate="sum"),
            ]
        ),
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
        _Planner(
            [HistoryOperation("aggregate", column="amount", aggregate="count")] * 2
        ),
        HistoryPandasResearchConfig(
            enabled=True, allowed_columns=("amount",), max_analysis_operations=1
        ),
    )
    assert (
        agent.research(_history_request(), [{"amount": 3}]).status
        == ResearchStatus.FAILED
    )
