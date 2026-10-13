from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AlertActionResult:
    action: str
    detail: str


class AlertChannelActionPort(ABC):
    """Executes the channel action the analyst decided on. Each method is
    one branch of the executor step's block/bidi/voicebot case - "pass" is
    a no-op that never reaches this port, and "scale_to_analyst" goes
    through AnalystEscalationDispatcher instead (a human analyst, not a
    channel).

    `comment`/`script` are the executor step's generated content
    (AgentSettings.executor.aric_marking for block/bidi, .voicebot_call for
    voicebot - see alert_review_workflow.py's _run_executor) - optional so
    a caller with no active configuration/segment still gets the old
    behavior instead of an error."""

    def block(self, alert_id: UUID, comment: str | None = None) -> AlertActionResult:
        raise NotImplementedError

    def route_to_bidi(
        self, alert_id: UUID, comment: str | None = None
    ) -> AlertActionResult:
        raise NotImplementedError

    def route_to_voicebot(
        self, alert_id: UUID, script: str | None = None
    ) -> AlertActionResult:
        raise NotImplementedError
