"""Decision -> mark translation (decision D8, docs/OBSERVABILITY_TASKS.md).

mark has three values: fraud, no_fraud, pending. block -> fraud;
pass / discard -> no_fraud; bidi -> pending; voicebot by its outcome;
escalated, voicebot not yet resolved, failed or skipped -> pending."""
from __future__ import annotations

from src.application.ports.alert_port import AlertResolutionMethod, Mark

# Executor executed_action values (alert_review_workflow._run_executor) plus
# "discarded" for a deterministic-rule discard.
_WORKFLOW_ACTIONS: dict[str, tuple[Mark, AlertResolutionMethod]] = {
    "block": (Mark.FRAUD, AlertResolutionMethod.ARIA),
    "none": (Mark.NO_FRAUD, AlertResolutionMethod.ARIA),
    "pass": (Mark.NO_FRAUD, AlertResolutionMethod.ARIA),
    "discarded": (Mark.NO_FRAUD, AlertResolutionMethod.ARIA),
    "bidi": (Mark.PENDING, AlertResolutionMethod.BIDI),
    "voicebot": (Mark.PENDING, AlertResolutionMethod.VOICEBOT),
    "scale_to_analyst": (Mark.PENDING, AlertResolutionMethod.ANALYST),
}

# VALID_ANALYST_RESOLUTIONS (analyst_queue_dtos.py).
_ANALYST_DECISIONS: dict[str, tuple[Mark, AlertResolutionMethod]] = {
    "block": (Mark.FRAUD, AlertResolutionMethod.ANALYST),
    "pass": (Mark.NO_FRAUD, AlertResolutionMethod.ANALYST),
    "bidi": (Mark.PENDING, AlertResolutionMethod.BIDI),
}

# The voicebot callback's outcome is free text today (no provider contract
# yet). Recognized values; anything else (no_answer, busy, hung_up, error,
# ...) means the call didn't settle the case -> pending.
VOICEBOT_FRAUD_OUTCOMES = frozenset(
    {
        "fraud",
        "fraud_confirmed",
        "confirmed_fraud",
        "not_recognized",
        "customer_not_recognized",
        "customer_denies",
        "block",
        "blocked",
    }
)
VOICEBOT_NO_FRAUD_OUTCOMES = frozenset(
    {
        "no_fraud",
        "not_fraud",
        "legit",
        "legitimate",
        "recognized",
        "customer_recognized",
        "customer_confirms",
        "pass",
    }
)


def workflow_resolution(
    executed_action: str | None,
) -> tuple[Mark, AlertResolutionMethod | None]:
    if executed_action is None:
        return Mark.PENDING, None
    return _WORKFLOW_ACTIONS.get(executed_action.strip().lower(), (Mark.PENDING, None))


def analyst_resolution(decision: str) -> tuple[Mark, AlertResolutionMethod]:
    return _ANALYST_DECISIONS.get(
        decision.strip().lower(), (Mark.PENDING, AlertResolutionMethod.ANALYST)
    )


def voicebot_outcome_mark(outcome: str | None) -> Mark:
    normalized = (outcome or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in VOICEBOT_FRAUD_OUTCOMES:
        return Mark.FRAUD
    if normalized in VOICEBOT_NO_FRAUD_OUTCOMES:
        return Mark.NO_FRAUD
    return Mark.PENDING
