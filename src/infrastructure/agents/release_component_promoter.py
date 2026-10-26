"""Hands winning non-model components to the flows that already promote them."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from src.application.ports.agent_release_promoter_port import (
    AgentReleaseComponentPromoter,
    ComponentHandoff,
    ComponentHandoffError,
)
from src.application.ports.clock_port import Clock
from src.application.ports.configuration_deploy_request_port import (
    ConfigurationDeployRequest,
    ConfigurationDeployRequestRepository,
)
from src.application.ports.configuration_port import ConfigurationRepository
from src.domain.agents.experiment import ComponentVersionReference
from src.domain.agents.release import AgentRelease


class ExistingFlowReleasePromoter(AgentReleaseComponentPromoter):
    """Configuration -> deploy request (approved by manager/release manager);
    vector store -> its promotion; library -> manual review in Biblioteca,
    because library entries are not versioned for automatic activation."""

    def __init__(
        self,
        *,
        deploy_requests: ConfigurationDeployRequestRepository,
        configurations: ConfigurationRepository,
        promote_vector_store: Callable[..., object],
        clock: Clock,
    ) -> None:
        self._deploy_requests = deploy_requests
        self._configurations = configurations
        self._promote_vector_store = promote_vector_store
        self._clock = clock

    def hand_off(
        self,
        release: AgentRelease,
        pin: ComponentVersionReference,
        *,
        actor: str,
        actor_id: str,
    ) -> ComponentHandoff:
        if pin.component == "configuration":
            return self._configuration(release, pin, actor, actor_id)
        if pin.component == "vector_store":
            try:
                self._promote_vector_store(pin.entity_id, actor=actor)
            except Exception as error:  # noqa: BLE001 - surfaced as a safe code
                raise ComponentHandoffError(pin.component) from error
            return ComponentHandoff(
                pin.component, "vector_store_promotion", pin.entity_id, "promoted"
            )
        if pin.component == "library":
            return ComponentHandoff(
                pin.component,
                "library_review",
                f"{pin.entity_id}@{pin.version[:12]}",
                "manual",
            )
        raise ComponentHandoffError(pin.component)

    def _configuration(self, release, pin, actor, actor_id) -> ComponentHandoff:
        try:
            target_version = int(pin.version)
        except ValueError as error:
            raise ComponentHandoffError(pin.component) from error
        active = self._configurations.get_active()
        request = self._deploy_requests.create(
            ConfigurationDeployRequest(
                id=str(uuid4()),
                target_configuration_id=pin.entity_id,
                target_version=target_version,
                current_configuration_id=active.configuration_id if active else None,
                current_version=active.version if active else None,
                title=f"Optimizador: {release.title}"[:200],
                message=f"{release.reason} (release {release.release_id})"[:2000],
                changes=[],
                requested_by=actor,
                requested_at=self._clock.now(),
                requested_by_id=actor_id,
            )
        )
        return ComponentHandoff(
            pin.component, "configuration_deploy_request", request.id, request.status
        )
