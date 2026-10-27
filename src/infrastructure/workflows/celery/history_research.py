from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

from src.application.dtos.pre_process_dtos import PreProcessAlertOutput
from src.application.dtos.research_dtos import ResearchRequest, ResearchSource
from src.domain.alerts.transaction_history_selection import (
    parse_event_time,
    select_transaction_history,
)
from src.domain.configurations.entities import (
    AgentToolsConfig,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.llm.langchain import get_llm_unit_of_work_factory
from src.infrastructure.monitoring.opentelemetry import get_monitoring
from src.infrastructure.workflows.celery.research_adapters import (
    HeuristicHistoryResearchPlanner,
    LLMHistoryResearchPlanner,
)


def _history_research(
    context: dict[str, Any], cfg: AgentToolsConfig, reasoning: str
) -> list[dict[str, Any]]:
    """Run the history analysis over the configured history slice."""
    settings = cfg.delegated_research.history_pandas
    pre_process: PreProcessAlertOutput = context["pre_process"]
    history = pre_process.enrichment.get("transaction_history") or []
    if not settings.enabled or settings.max_delegations <= 0 or not history:
        return []
    # Selector: time window before the alert + most recent N rows. Column
    # restriction (allowed_columns) is enforced by the agent itself.
    selected = select_transaction_history(
        history,
        columns=[],
        window_days=settings.window_days,
        max_transactions=settings.max_history_rows,
        reference_time=parse_event_time(pre_process.roles.get("event_time")),
    )
    from src.infrastructure.workflows.celery import task_factories

    if settings.planner == "llm" and genai_config.REPORT_LLM_MODEL:
        planner = LLMHistoryResearchPlanner(
            get_llm_unit_of_work_factory(),
            model=genai_config.REPORT_LLM_MODEL,
            monitoring=get_monitoring(),
            columns=settings.allowed_columns
            or (list(selected[0].keys()) if selected else []),
            allowed_operations=settings.allowed_operations,
            max_operations=settings.max_analysis_operations,
        )
    else:
        planner = HeuristicHistoryResearchPlanner(pre_process.roles.get("amount"))
    agent = task_factories.get_history_research_agent(
        planner,
        settings,
        history_provider=lambda _request: selected,
    )
    request = ResearchRequest(
        ResearchSource.HISTORY_PANDAS,
        "Investiga evidencia adicional en el historial de la alerta. "
        f"Razonamiento previo: {reasoning}",
        alert_context={"amount": pre_process.roles.get("amount")},
        prior_evidence=[],
    )
    results = task_factories.get_research_delegation_coordinator(
        {ResearchSource.HISTORY_PANDAS: agent}
    ).delegate([request], is_inconclusive=lambda: True, accept=lambda _result: None)
    return [dataclasses.asdict(result) for result in results]


_MAX_HISTORY_ROUNDS = 5


def _history_rounds(
    context: dict[str, Any],
    cfg: AgentToolsConfig,
    segment_kwargs: dict[str, Any],
    output: Any,
    run: Callable[[dict[str, Any]], Any],
    *,
    is_open: Callable[[Any], bool],
    reasoning_of: Callable[[Any], str],
) -> Any:
    """Up to history_pandas.max_delegations rounds (capped at 5) while the
    step stays open (inconclusive / challenged): each round runs the
    history analysis, then the step once more with every finding so far.

    Stops early when the step concludes, or when a round brings back the
    same findings as the previous one - re-asking would only repeat the
    same prompt.
    """
    rounds = min(
        cfg.delegated_research.history_pandas.max_delegations, _MAX_HISTORY_ROUNDS
    )
    research: list[dict[str, Any]] = []
    previous: list[Any] | None = None
    for _ in range(rounds):
        if not is_open(output):
            break
        found = _history_research(context, cfg, reasoning_of(output))
        evidence = [(item.get("status"), item.get("findings")) for item in found]
        if not found or evidence == previous:
            break
        previous = evidence
        research.extend(found)
        output = dataclasses.replace(
            run(_with_research(segment_kwargs, research)),
            research_delegations=list(research),
        )
    return output


def _with_research(
    kwargs: dict[str, Any], research: list[dict[str, Any]]
) -> dict[str, Any]:
    final_kwargs = dict(kwargs)
    final_kwargs["extra_instructions"] = (
        str(final_kwargs.get("extra_instructions") or "")
        + "\n\nInvestigación delegada: análisis de historial. Úsala como "
        "evidencia adicional y responde ahora con tu conclusión final:\n"
        f"{research}"
    )
    return final_kwargs
