from datetime import UTC, datetime

from src.domain.configurations.entities import ConfigurationRecord
from src.infrastructure.entrypoint.api.configuration_mapper import (
    input_from_request,
    to_detail_response,
    to_summary_response,
)
from src.infrastructure.entrypoint.api.schemas import CreateConfigurationRequest


def test_configuration_mapper_round_trips_request_through_record_response() -> None:
    request = CreateConfigurationRequest.model_validate(
        {
            "name": "Fraude tarjetas",
            "configuration_id": "fraude-tarjetas",
            "description": "Configuración de prueba",
            "segments": {"tarjetas": {"enabled": True, "order": 2}},
        }
    )

    mapped_input = input_from_request(request)
    record = ConfigurationRecord(
        configuration_id=mapped_input.configuration_id or "fraude-tarjetas",
        version=1,
        active=False,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
        name=mapped_input.name,
        description=mapped_input.description,
        created_by=mapped_input.created_by,
        general=mapped_input.general,
        infra=mapped_input.infra,
        test=mapped_input.test,
        segments=mapped_input.segments,
    )

    detail = to_detail_response(record)
    summary = to_summary_response(record)

    assert detail.configuration_id == request.configuration_id
    assert detail.name == request.name
    assert detail.description == request.description
    assert detail.segments["tarjetas"].enabled is True
    assert detail.segments["tarjetas"].order == 2
    assert summary.configuration_id == detail.configuration_id
    assert summary.version == detail.version
    assert summary.name == detail.name
