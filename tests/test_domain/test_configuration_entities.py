from src.domain.configurations.entities import (
    ConfigurationRecord,
    ConfigurationRef,
    GeneralSettings,
    InfraSettings,
)
from src.domain.configurations.entities import (
    TestSettings as ConfigurationSettings,
)


def test_configuration_ref_can_pin_a_specific_version() -> None:
    assert ConfigurationRef(configuration_id="fraud", version=7).version == 7
    assert ConfigurationRef(configuration_id="fraud").version is None


def test_configuration_defaults_are_independent() -> None:
    first = ConfigurationRecord(
        configuration_id="fraud",
        version=1,
        name="Fraud",
        description="",
        active=False,
        general=GeneralSettings(),
        infra=InfraSettings(),
        test=ConfigurationSettings(),
        created_at=__import__("datetime").datetime.now(),
        updated_at=__import__("datetime").datetime.now(),
    )
    second = ConfigurationRecord(
        configuration_id="fraud",
        version=2,
        name="Fraud",
        description="",
        active=False,
        general=GeneralSettings(),
        infra=InfraSettings(),
        test=ConfigurationSettings(),
        created_at=first.created_at,
        updated_at=first.updated_at,
    )

    first.segments.clear()

    assert second.segments
