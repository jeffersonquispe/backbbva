from src.application.dtos.research_dtos import (
    HistoryOperation,
    ResearchRequest,
    ResearchSource,
    ResearchStatus,
)
from src.application.ports.llm_unit_of_work_port import LLMInvocationResult
from src.domain.configurations.entities import (
    HistoryPandasResearchConfig,
)
from src.infrastructure.workflows.celery.history_pandas_research import (
    HistoryPandasResearchAgent,
)
from src.infrastructure.workflows.celery.research_adapters import (
    HeuristicHistoryResearchPlanner,
    LLMHistoryResearchPlanner,
)


class _LLM:
    def __init__(self, content):
        self.content = content
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        return LLMInvocationResult(
            content=self.content, model="cheap-model", input_tokens=120, output_tokens=30
        )


class _LLMFactory:
    def __init__(self, llm):
        self.llm = llm
        self.options = None

    def create(self, **options):
        self.options = options
        return self.llm


class _Planner:
    def __init__(self, operations):
        self.operations = operations

    def plan(self, request):
        return self.operations


def _history_request():
    return ResearchRequest(ResearchSource.HISTORY_PANDAS, "is amount unusual?")


def test_llm_history_planner_uses_closed_schema_and_rejects_unavailable_columns():
    llm = _LLM(
        '{"operations":['
        '{"name":"comparison","column":"amount","current_value":900},'
        '{"name":"aggregate","column":"document","aggregate":"count"},'
        '{"name":"run_python","column":"amount"}]}'
    )
    factory = _LLMFactory(llm)
    planner = LLMHistoryResearchPlanner(
        factory,
        model="cheap-model",
        monitoring=object(),
        columns=["amount"],
        allowed_operations=["comparison", "aggregate"],
        max_operations=4,
    )

    plan = planner.plan(_history_request())

    assert plan == [HistoryOperation("comparison", column="amount", current_value=900)]
    assert factory.options["model"] == "cheap-model"
    assert factory.options["temperature"] == 0.0
    assert "available_columns" in llm.messages[1].content
    assert planner.usage == {"input_tokens": 120, "output_tokens": 30}


def test_history_trace_records_planner_kind_latency_and_tokens():
    config = HistoryPandasResearchConfig(enabled=True, allowed_columns=["amount"])
    rows = [{"amount": 100}, {"amount": 200}, {"amount": 900}]
    llm_planner = LLMHistoryResearchPlanner(
        _LLMFactory(
            _LLM('{"operations":[{"name":"comparison","column":"amount","current_value":900}]}')
        ),
        model="cheap-model",
        monitoring=object(),
        columns=["amount"],
        allowed_operations=["comparison"],
        max_operations=4,
    )

    llm_trace = HistoryPandasResearchAgent(llm_planner, config).research(
        _history_request(), rows
    ).trace[0]
    fixed_trace = HistoryPandasResearchAgent(
        HeuristicHistoryResearchPlanner(900), config
    ).research(_history_request(), rows).trace[0]

    assert llm_trace["planner"] == "llm"
    assert (llm_trace["planner_input_tokens"], llm_trace["planner_output_tokens"]) == (120, 30)
    assert fixed_trace["planner"] == "heuristic"
    assert "planner_input_tokens" not in fixed_trace
    assert llm_trace["planning_ms"] >= 0 and fixed_trace["planning_ms"] >= 0


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


def test_history_analysis_has_no_row_cap():
    rows = [{"amount": float(i), "channel": "web"} for i in range(5_000)]
    agent = HistoryPandasResearchAgent(
        _Planner([HistoryOperation(name="aggregate", column="amount", aggregate="count")]),
        HistoryPandasResearchConfig(enabled=True),
        history_provider=lambda _request: rows,
    )

    result = agent.research(_history_request())

    assert result.status == ResearchStatus.EXECUTED
    assert result.trace[0]["rows_considered"] == 5_000
    assert result.findings[0].value == 5_000


def test_llm_history_planner_prompt_steers_away_from_full_scans():
    llm = _LLM('{"operations":[]}')
    planner = LLMHistoryResearchPlanner(
        _LLMFactory(llm),
        model="cheap-model",
        monitoring=None,
        columns=["amount"],
        allowed_operations=["filter", "aggregate"],
        max_operations=4,
    )

    planner.plan(_history_request())

    assert "no lo recorras completo" in llm.messages[0].content
