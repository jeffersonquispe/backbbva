from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from src.application.dtos.classify_alert_dtos import ClassifyAlertOutput
from src.application.dtos.pre_process_dtos import PreProcessAlertOutput
from src.application.dtos.profile_alert_dtos import ProfileAlertOutput
from src.application.ports.modus_operandi_library_port import ModusOperandiPlaybook

# The five actions the analyst decision agent can route an alert to.
VALID_ANALYST_DECISIONS = (
    "block",
    "pass",
    "bidi",
    "voicebot",
    "scale_to_analyst",
)


@dataclass
class AnalystReviewAlertInput:
    alert_id: UUID
    pre_process: PreProcessAlertOutput
    profile: ProfileAlertOutput
    classification: ClassifyAlertOutput


@dataclass
class AnalystReviewAlertOutput:
    decision: str  # one of VALID_ANALYST_DECISIONS
    reasoning: str
    # The modus operandi playbook that guided the decision (resolved via
    # ResolveAnalystPlaybookUseCase). None = no close modus operandi had a
    # playbook, so the no-playbook default applied (escalate to an analyst,
    # block soft if none is available) without calling the LLM. The
    # executor reads its fallbacks when the chosen resource is gone by the
    # time it reserves it.
    modus_operandi_id: str | None = None
    modus_operandi_title: str | None = None
    playbook: ModusOperandiPlaybook | None = None
    # channel -> {"available": int, "status": str, "total": int | None}, no
    # datetimes - this DTO gets dataclasses.asdict()'d straight into a
    # DynamoDB step record and into a Celery task's JSON args, both of
    # which reject raw datetime values.
    operations_capacity: dict[str, dict[str, object]] = field(
        default_factory=dict
    )
    input_tokens: int = 0
    output_tokens: int = 0
