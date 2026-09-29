from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.dtos.configuration_dtos import (
    ConfigurationChange,
    ConfigurationPreviewOutput,
    CreateConfigurationInput,
)
from src.infrastructure.entrypoint.api.factories.configuration_factory import (
    get_test_configuration_use_case,
)
from src.infrastructure.entrypoint.api.routers.configurations_router import (
    configuration_test_router,
)


class FakePreviewConfigurationUseCase:
    received: CreateConfigurationInput | None = None

    def execute(self, input: CreateConfigurationInput) -> ConfigurationPreviewOutput:
        self.received = input
        return ConfigurationPreviewOutput(
            changes=[
                ConfigurationChange(
                    path="infra.max_instances", previous=8, proposed=12
                )
            ],
            warnings=["Cambio de alto impacto"],
        )


def test_configuration_test_endpoint_returns_preview_without_saving() -> None:
    fake = FakePreviewConfigurationUseCase()
    app = FastAPI()
    app.include_router(configuration_test_router)
    app.dependency_overrides[get_test_configuration_use_case] = lambda: fake

    response = TestClient(app).post(
        "/configuration/test",
        json={"name": "Propuesta", "infra": {"max_instances": 12}},
    )

    assert response.status_code == 200
    assert response.json() == {
        "valid": True,
        "changes": [
            {"path": "infra.max_instances", "previous": 8, "proposed": 12}
        ],
        "warnings": ["Cambio de alto impacto"],
    }
    assert fake.received is not None
    assert fake.received.name == "Propuesta"
    assert fake.received.infra.max_instances == 12


def _request_with_rubric(scores: list[float]) -> dict:
    return {
        "name": "Propuesta",
        "segments": {
            "tarjetas": {
                "agent": {
                    "rubrics": [
                        {
                            "id": "r1",
                            "name": "estafa_score",
                            "conditions": [
                                {"id": f"c{i}", "variable": "amount", "comparison": "gt",
                                 "values": ["1"], "score": score}
                                for i, score in enumerate(scores)
                            ],
                        }
                    ]
                }
            }
        },
    }


def test_configuration_request_rejects_rubric_not_summing_to_100() -> None:
    fake = FakePreviewConfigurationUseCase()
    app = FastAPI()
    app.include_router(configuration_test_router)
    app.dependency_overrides[get_test_configuration_use_case] = lambda: fake

    response = TestClient(app).post(
        "/configuration/test", json=_request_with_rubric([40, 50])
    )

    assert response.status_code == 422
    assert "estafa_score" in response.text
    assert "90" in response.text
    assert fake.received is None


def test_configuration_request_accepts_rubric_summing_to_100() -> None:
    fake = FakePreviewConfigurationUseCase()
    app = FastAPI()
    app.include_router(configuration_test_router)
    app.dependency_overrides[get_test_configuration_use_case] = lambda: fake

    response = TestClient(app).post(
        "/configuration/test", json=_request_with_rubric([33.3, 33.3, 33.4])
    )

    assert response.status_code == 200
    assert fake.received.segments["tarjetas"].agent.rubrics[0].name == "estafa_score"
