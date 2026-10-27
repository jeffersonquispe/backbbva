from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.application.ports.agent_release_promoter_port import ComponentHandoffError
from src.application.ports.clock_port import Clock
from src.domain.agents.experiment import ComponentVersionReference
from src.domain.agents.release import AgentRelease, AgentReleaseStatus
from src.infrastructure.agents.release_component_promoter import (
    ExistingFlowReleasePromoter,
)

NOW = datetime(2026, 10, 26, tzinfo=UTC)


class FixedClock(Clock):
    def now(self):
        return NOW


class DeployRequests:
    def __init__(self):
        self.created = []

    def create(self, request):
        self.created.append(request)
        return request


class Active:
    configuration_id = "cfg-active"
    version = 4


class Configurations:
    def get(self, configuration_id, version):
        return None

    def get_active(self):
        return Active()


def _release():
    return AgentRelease(
        release_id="rel-1",
        validation_id="v",
        session_id="s",
        experiment_id="e",
        status=AgentReleaseStatus.PENDING_APPROVAL,
        candidate_component_pins=(),
        previous_component_pins=(),
        requested_by="cm",
        requested_by_id="cm-1",
        requested_at=NOW,
        title="Mejor umbral",
        reason="Validado con 120 casos",
    )


class InMemoryGenerations:
    def get(self, instance, generation):
        return SimpleNamespace(status="ready") if generation == 3 else None


def _promoter():
    deploy = DeployRequests()
    return (
        ExistingFlowReleasePromoter(
            deploy_requests=deploy,
            configurations=Configurations(),
            vector_store_generations=InMemoryGenerations(),
            clock=FixedClock(),
        ),
        deploy,
    )


def test_configuration_becomes_a_pending_deploy_request_against_the_active_one():
    promoter, deploy = _promoter()

    handoff = promoter.hand_off(
        _release(),
        ComponentVersionReference("configuration", "cfg-new", "7", "a" * 64),
        actor="manager",
        actor_id="m-1",
    )

    request = deploy.created[0]
    assert (request.target_configuration_id, request.target_version) == ("cfg-new", 7)
    assert (request.current_configuration_id, request.current_version) == (
        "cfg-active",
        4,
    )
    assert "rel-1" in request.message
    assert (handoff.flow, handoff.reference, handoff.status) == (
        "configuration_deploy_request",
        request.id,
        "pending",
    )


def test_vector_store_requires_a_configuration_pin_instead_of_publishing_itself():
    promoter, _ = _promoter()
    pin = ComponentVersionReference("vector_store", "vs-2", "3", "b" * 64)
    result = promoter.hand_off(_release(), pin, actor="m", actor_id="m-1")
    assert (result.flow, result.status) == ("configuration_pin_required", "manual")
    with pytest.raises(ComponentHandoffError):
        promoter.hand_off(_release(), replace(pin, version="999"), actor="m", actor_id="m-1")


def test_library_is_left_for_manual_review():
    promoter, deploy = _promoter()

    handoff = promoter.hand_off(
        _release(),
        ComponentVersionReference("library", "mo-1", "c" * 64, "c" * 64),
        actor="m",
        actor_id="m-1",
    )

    assert (handoff.flow, handoff.status) == ("library_review", "manual")
    assert deploy.created == []


class PinningConfigurations(Configurations):
    """cfg-new v7 searches vs-2 generation 3."""

    def get(self, configuration_id, version):
        from src.domain.configurations.entities import default_segments

        if (configuration_id, version) != ("cfg-new", 7):
            return None
        segments = default_segments()
        research = segments["tarjetas"].agent.classification.delegated_research.vector_store
        research.enabled = True
        research.vector_store_instance_id = "vs-2"
        research.vector_store_generation = 3
        return SimpleNamespace(segments=segments)


def test_vector_store_goes_live_through_the_configuration_that_pins_it():
    deploy = DeployRequests()
    promoter = ExistingFlowReleasePromoter(
        deploy_requests=deploy,
        configurations=PinningConfigurations(),
        vector_store_generations=InMemoryGenerations(),
        clock=FixedClock(),
    )
    release = replace(
        _release(),
        candidate_component_pins=(
            ComponentVersionReference("configuration", "cfg-new", "7", "a" * 64),
            ComponentVersionReference("vector_store", "vs-2", "3", "b" * 64),
        ),
    )

    result = promoter.hand_off(
        release, release.candidate_component_pins[1], actor="m", actor_id="m-1"
    )

    assert (result.flow, result.reference, result.status) == (
        "configuration_deploy_request",
        "vs-2@g3",
        "pending",
    )
    # The vector store opens no deploy request of its own.
    assert deploy.created == []
