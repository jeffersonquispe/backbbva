from scripts import compare_history_planners as compare


def _tools() -> dict:
    return {"delegated_research": {"history_pandas": {"enabled": False}}}


def _base() -> dict:
    return {
        "general": {},
        "infra": {},
        "test": {},
        "segments": {
            "TC": {
                "agent": {
                    "detector": _tools(),
                    "detector_adversarial": _tools(),
                    "classification": _tools(),
                    "adversarial": _tools(),
                }
            }
        },
    }


def test_variants_differ_only_in_planner_and_enable_history_where_it_runs() -> None:
    base = _base()

    fixed = compare.planner_variant(base, "heuristic", "fijo")
    llm = compare.planner_variant(base, "llm", "llm")

    agent = fixed["segments"]["TC"]["agent"]
    assert agent["detector"]["delegated_research"]["history_pandas"] == {
        "enabled": True,
        "planner": "heuristic",
    }
    assert agent["adversarial"]["delegated_research"]["history_pandas"]["enabled"] is False
    assert llm["segments"]["TC"]["agent"]["classification"]["delegated_research"][
        "history_pandas"
    ]["planner"] == "llm"
    # The base configuration is never mutated.
    assert "planner" not in str(base)


def test_window_days_override_applies_to_every_history_config_without_touching_base() -> None:
    base = _base()

    variant = compare.planner_variant(base, "llm", "llm", window_days=0)

    agent = variant["segments"]["TC"]["agent"]
    assert all(
        agent[step]["delegated_research"]["history_pandas"]["window_days"] == 0
        for step in agent
    )
    assert "window_days" not in str(base)
    # Without the override the base value is kept (no key added).
    plain = compare.planner_variant(base, "llm", "llm")
    assert "window_days" not in plain["segments"]["TC"]["agent"]["detector"][
        "delegated_research"
    ]["history_pandas"]


def test_variants_enable_every_segment_so_tool_settings_apply() -> None:
    base = _base()
    base["segments"]["TC"]["enabled"] = False

    variant = compare.planner_variant(base, "llm", "llm")

    assert variant["segments"]["TC"]["enabled"] is True
    assert base["segments"]["TC"]["enabled"] is False


class RecordingApi:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def call(self, method: str, path: str, body=None):
        self.paths.append(path)
        if path == "/test-runs/run-1":
            return {
                "status": "SUCCEEDED",
                "total": 2,
                "failed": 0,
                "input_tokens": 900,
                "output_tokens": 100,
                "cases": [{"workflow_execution_id": "a"}, {"workflow_execution_id": "b"}],
                "ground_truth_metrics": {
                    "total": 2,
                    "macro_f1": 0.5,
                    "confusion_matrix": {"fraud": {"fraud": 1}, "no_fraud": {"fraud": 1}},
                },
                "total_duration_stats": {"avg_seconds": 12.0, "p95_seconds": 20.0},
            }
        history = {
            "source": "history_pandas",
            "status": "executed",
            "findings": [{"metric": "m"}],
            "trace": [
                {
                    "rows_considered": 4,
                    "planner": "llm",
                    "planning_ms": 300,
                    "planner_input_tokens": 120,
                    "planner_output_tokens": 30,
                }
            ],
        }
        open_step = path.endswith("/a")
        return {
            "steps": [
                {"step_name": "classification", "attempt": 1, "output": {"is_fraud": "fraud"}},
                {
                    "step_name": "classification",
                    "attempt": 2,
                    "output": {
                        "is_fraud": "unknown" if open_step else "fraud",
                        "research_delegations": [history],
                    },
                },
            ]
        }


def test_summary_reports_rates_tokens_and_planner_trace() -> None:
    summary = compare.summarize(RecordingApi(), "run-1")

    assert summary["inconclusive_rate"] == 0.5
    assert summary["accuracy_vs_marcacion"] == 0.5
    assert summary["tokens_per_alert"] == 500.0
    assert summary["history_analyses"] == 2
    assert summary["planner_seen"] == ["llm"]
    assert (summary["planning_ms_avg"], summary["planner_tokens_avg"]) == (300, 150)
