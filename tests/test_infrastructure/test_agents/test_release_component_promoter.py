from __future__ import annotations

from datetime import UTC, datetime

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


def _promoter(promote=lambda instance_id, actor: None):
    deploy = DeployRequests()
    return (
        ExistingFlowReleasePromoter(
            deploy_requests=deploy,
            configurations=Configurations(),
            promote_vector_store=promote,
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


def test_vector_store_uses_its_promotion_and_failures_are_safe():
    promoted = []
    promoter, _ = _promoter(lambda instance_id, actor: promoted.append(instance_id))
    pin = ComponentVersionReference("vector_store", "vs-2", "3", "b" * 64)

    assert (
        promoter.hand_off(_release(), pin, actor="m", actor_id="m-1").status
        == "promoted"
    )
    assert promoted == ["vs-2"]

    def broken(instance_id, actor):
        raise RuntimeError("opensearch down")

    failing, _ = _promoter(broken)
    with pytest.raises(ComponentHandoffError):
        failing.hand_off(_release(), pin, actor="m", actor_id="m-1")


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
