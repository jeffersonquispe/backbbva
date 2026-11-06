from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.ports.alert_reasoning_evaluation_port import (
    AlertReasoningEvaluationRecord,
    ReasoningEvaluationStatus,
)
from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.use_cases.metrics.read_reasoning_evaluations import (
    AlertReasoningEvaluationView,
    ReasoningEvaluationAlertNotFoundError,
    ReasoningEvaluationRangeError,
    ReasoningEvaluationState,
)
from src.infrastructure.entrypoint.api.routers import reasoning_evaluations_router as r
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user

NOW = datetime(2026, 11, 5, tzinfo=UTC)
ALERT = uuid4()
RECORD = AlertReasoningEvaluationRecord(
    alert_id=ALERT,
    workflow_execution_id=uuid4(),
    status=ReasoningEvaluationStatus.EVALUATED,
    hallucination=True,
    data_use_correct=False,
    rationale="Cita un monto inexistente.",
    judge_model="judge",
    evaluated_at=NOW,
    input_tokens=900,
    output_tokens=40,
    prompt_version="v2",
    step_verdicts={
        "classification": {
            "hallucination": True,
            "data_use_correct": False,
            "note": "monto 9999",
        }
    },
    attempts=2,
)


class RecordingUseCase:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result, self.error, self.calls = result, error, []

    def execute(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return self.result


def _provider(use_case):
    def provide():
        return use_case

    return provide


def _client(role: LocalRole, *, get=None, listing=None) -> TestClient:
    user = LocalUser(
        UUID("00000000-0000-0000-0000-000000000001"),
        "u@example.com",
        "U",
        "",
        role,
        True,
        NOW,
        NOW,
    )
    app = FastAPI()
    app.include_router(r.router)
    app.dependency_overrides[get_current_user] = lambda: user
    if get:
        app.dependency_overrides[r.get_get_alert_reasoning_evaluation_use_case] = (
            _provider(get)
        )
    if listing:
        app.dependency_overrides[r.get_list_reasoning_evaluations_use_case] = _provider(
            listing
        )
    return TestClient(app)


def test_the_alert_explanation_includes_rationale_and_per_step_notes() -> None:
    view = AlertReasoningEvaluationView(
        ALERT, ReasoningEvaluationState.EVALUATED, RECORD
    )

    response = _client(LocalRole.MANAGER, get=RecordingUseCase(view)).get(
        f"/alerts/{ALERT}/reasoning-evaluation"
    )

    body = response.json()
    assert response.status_code == 200 and body["state"] == "evaluated"
    assert body["evaluation"]["rationale"] == "Cita un monto inexistente."
    assert (
        body["evaluation"]["prompt_version"] == "v2"
        and body["evaluation"]["attempts"] == 2
    )
    assert body["evaluation"]["steps"] == [
        {
            "step": "classification",
            "hallucination": True,
            "data_use_correct": False,
            "note": "monto 9999",
        }
    ]
    # Neither the judge prompt nor the evidence it saw is ever part of the answer.
    assert "prompt" not in body["evaluation"] and "evidence" not in body["evaluation"]


def test_a_missing_verdict_explains_why() -> None:
    view = AlertReasoningEvaluationView(
        ALERT, ReasoningEvaluationState.NOT_SAMPLED, None
    )

    response = _client(LocalRole.MANAGER, get=RecordingUseCase(view)).get(
        f"/alerts/{ALERT}/reasoning-evaluation"
    )

    assert response.json() == {
        "alert_id": str(ALERT),
        "state": "not_sampled",
        "evaluation": None,
    }


def test_unknown_alert_is_404() -> None:
    response = _client(
        LocalRole.MANAGER,
        get=RecordingUseCase(error=ReasoningEvaluationAlertNotFoundError("x")),
    ).get(f"/alerts/{ALERT}/reasoning-evaluation")

    assert response.status_code == 404


def test_the_listing_passes_filters_and_maps_range_errors() -> None:
    listing = RecordingUseCase([RECORD])
    client = _client(LocalRole.OPS_ANALYST, listing=listing)

    response = client.get(
        "/metrics/reasoning-evaluations?from_day=2026-11-01&to_day=2026-11-05"
        "&hallucination=true&status=evaluated&limit=5"
    )

    assert response.status_code == 200 and len(response.json()) == 1
    assert listing.calls == [
        (
            (),
            {
                "from_day": date(2026, 11, 1),
                "to_day": date(2026, 11, 5),
                "hallucination": True,
                "data_use_correct": None,
                "status": ReasoningEvaluationStatus.EVALUATED,
                "limit": 5,
            },
        )
    ]
    bad = _client(
        LocalRole.MANAGER,
        listing=RecordingUseCase(error=ReasoningEvaluationRangeError("x")),
    )
    assert (
        bad.get(
            "/metrics/reasoning-evaluations?from_day=2026-01-01&to_day=2026-11-05"
        ).status_code
        == 422
    )
    assert client.get("/metrics/reasoning-evaluations").status_code == 422


def test_it_needs_the_monitor_permission() -> None:
    for role in (LocalRole.FRAUD_ANALYST, LocalRole.FRAUD_REVIEWER):
        client = _client(role)
        assert client.get(f"/alerts/{ALERT}/reasoning-evaluation").status_code == 403
        assert (
            client.get(
                "/metrics/reasoning-evaluations?from_day=2026-11-01&to_day=2026-11-05"
            ).status_code
            == 403
        )
