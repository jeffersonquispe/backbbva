from datetime import UTC, datetime

from src.application.use_cases.configurations.get_configuration_graph import (
    ConfigurationGraphNode,
)
from src.domain.configurations.entities import ConfigurationRecord
from src.infrastructure.entrypoint.api.configuration_mapper import (
    input_from_request,
    to_detail_response,
    to_graph_node_response,
    to_summary_response,
)
from src.infrastructure.entrypoint.api.schemas import CreateConfigurationRequest


def test_configuration_mapper_round_trips_request_through_record_response() -> None:
    request = CreateConfigurationRequest.model_validate(
        {
            "name": "Fraude tarjetas",
            "configuration_id": "fraude-tarjetas",
            "parent_ref": {"configuration_id": "config-origen", "version": 2},
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
        parent_ref=mapped_input.parent_ref,
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
    assert summary.parent_ref == {"configuration_id": "config-origen", "version": 2}


def test_graph_node_response_carries_the_promotion_comment() -> None:
    from src.domain.configurations.entities import (
        GeneralSettings,
        InfraSettings,
        TestSettings,
    )

    record = ConfigurationRecord(
        configuration_id="fraude",
        version=3,
        name="Fraude",
        description="",
        active=True,
        general=GeneralSettings(),
        infra=InfraSettings(),
        test=TestSettings(),
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
        ever_activated=True,
    )

    promoted = to_graph_node_response(ConfigurationGraphNode(record, "Sube umbral"))
    unpromoted = to_graph_node_response(ConfigurationGraphNode(record))

    assert promoted.promotion_comment == "Sube umbral"
    assert promoted.version == 3 and promoted.active
    assert unpromoted.promotion_comment is None
