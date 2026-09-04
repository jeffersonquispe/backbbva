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
