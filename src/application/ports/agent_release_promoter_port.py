from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.domain.agents.experiment import ComponentVersionReference
from src.domain.agents.release import AgentRelease


@dataclass(frozen=True)
class ComponentHandoff:
    """Where a promoted non-model component went and what state it is in."""

    component: str
    flow: str
    reference: str
    status: str


class ComponentHandoffError(Exception):
    """The component could not be handed to its promotion flow."""


class AgentReleaseComponentPromoter(ABC):
    """Hands a winning configuration, library or vector store to the flow that
    already promotes it in production (deploy request, promotion, review)."""

    @abstractmethod
    def hand_off(
        self,
        release: AgentRelease,
        pin: ComponentVersionReference,
        *,
        actor: str,
        actor_id: str,
    ) -> ComponentHandoff:
        raise NotImplementedError
