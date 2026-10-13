from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class PostProcessAlertInput:
    alert_id: UUID
    workflow_started_at: datetime
    # The analyst's decision: block/pass/bidi/voicebot/scale_to_analyst -
    # this is what the executor step acted on, and what closes the alert.
    resolution_path: str
    # Already-generated final documentation (AgentSettings.executor
    # .documentador - template substitution or an agent LLM call,
    # depending on strategy) - built by the workflow (same pattern as
    # classification/adversarial's extra_instructions) before this use
    # case runs, so it stays a plain "package it into the output" step
    # with no LLM/config dependency of its own. Empty when there's no
    # active configuration/segment to generate it from.
    documentation: str = ""


@dataclass
class PostProcessAlertOutput:
    status: str  # "success"
    resolution_path: str
    total_duration_seconds: float
    # ISO 8601 keeps the API/workflow output representation portable.
    closed_at: str
    documentation: str = ""
