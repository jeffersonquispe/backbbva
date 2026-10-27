"""Hands winning non-model components to the flows that already promote them."""

from __future__ import annotations

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
from src.application.ports.vector_store_generation_port import (
    VectorStoreGenerationRepository,
    VectorStoreGenerationStatus,
)
from src.domain.agents.experiment import ComponentVersionReference
from src.domain.agents.release import AgentRelease
from src.domain.fraud_knowledge.vector_store_generations import (
    VectorStorePin,
    configuration_vector_store_pins,
)


class ExistingFlowReleasePromoter(AgentReleaseComponentPromoter):
    """Configuration -> deploy request (approved by manager/release manager);
    library -> manual review in Biblioteca, because library entries are not
    versioned for automatic activation. A vector-store generation is never
    published on its own: production searches what the active configuration
    pins, so it goes live through the configuration's deploy request when
    the release's configuration pins it, and otherwise needs a configuration
    version that pins it (saved, tested and deployed as usual)."""

    def __init__(
        self,
        *,
        deploy_requests: ConfigurationDeployRequestRepository,
        configurations: ConfigurationRepository,
        vector_store_generations: VectorStoreGenerationRepository,
        clock: Clock,
    ) -> None:
        self._deploy_requests = deploy_requests
        self._configurations = configurations
        self._vector_store_generations = vector_store_generations
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
            return self._vector_store(release, pin)
        if pin.component == "library":
            return ComponentHandoff(
                pin.component,
                "library_review",
                f"{pin.entity_id}@{pin.version[:12]}",
                "manual",
            )
        raise ComponentHandoffError(pin.component)

    def _vector_store(
        self, release: AgentRelease, pin: ComponentVersionReference
    ) -> ComponentHandoff:
        try:
            generation_number = int(pin.version)
        except ValueError as error:
            raise ComponentHandoffError(pin.component) from error
        generation = self._vector_store_generations.get(
            pin.entity_id, generation_number
        )
        if generation is None or generation.status != VectorStoreGenerationStatus.READY:
            raise ComponentHandoffError(pin.component)
        reference = f"{pin.entity_id}@g{generation_number}"
        configuration_pin = next(
            (
                item
                for item in release.candidate_component_pins
                if item.component == "configuration"
            ),
            None,
        )
        configuration = (
            self._configurations.get(
                configuration_pin.entity_id, int(configuration_pin.version)
            )
            if configuration_pin is not None
            else None
        )
        if configuration is not None and VectorStorePin(
            pin.entity_id, generation_number
        ) in configuration_vector_store_pins(configuration):
            return ComponentHandoff(
                pin.component, "configuration_deploy_request", reference, "pending"
            )
        return ComponentHandoff(
            pin.component, "configuration_pin_required", reference, "manual"
        )

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
