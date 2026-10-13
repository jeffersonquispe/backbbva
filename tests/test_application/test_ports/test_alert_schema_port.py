import pytest

from src.application.ports.alert_schema_port import (
    AlertSchemaDataSource,
    AlertSchemaField,
    AlertSchemaFieldType,
    AlertSchemaValidationError,
    AlertSchemaVersion,
    validate_schema,
)


def test_empty_v1_schema_is_valid_until_fields_are_defined():
    validate_schema(AlertSchemaVersion(version=1))


def test_schema_rejects_duplicate_source_locations():
    fields = [
        AlertSchemaField(
            "first", AlertSchemaDataSource.ARIC, "one", field_ds_loc="event.id"
        ),
        AlertSchemaField(
            "second", AlertSchemaDataSource.ARIC, "two", field_ds_loc="event.id"
        ),
    ]

    with pytest.raises(AlertSchemaValidationError, match="unique"):
        validate_schema(AlertSchemaVersion(version=1, fields=fields, field_roles={}))


def test_schema_rejects_mandatory_aria_field():
    field = AlertSchemaField(
        "score",
        AlertSchemaDataSource.ARIA,
        "score",
        type=AlertSchemaFieldType.NUMBER,
        is_mandatory=True,
    )

    with pytest.raises(AlertSchemaValidationError, match="mandatory"):
        validate_schema(AlertSchemaVersion(version=1, fields=[field], field_roles={}))
