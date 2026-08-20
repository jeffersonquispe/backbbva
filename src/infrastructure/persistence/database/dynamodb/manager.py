from datetime import datetime, timezone

from botocore.exceptions import ClientError

from src.application.ports.configuration_port import (
    AgentSettings,
    ConfigurationRecord,
    GeneralSettings,
    InfraSettings,
    MonitoringSettings,
    OpsSettings,
    TestSettings,
)
from src.application.ports.fraud_playbook_port import FraudPlaybookRecord
from src.application.ports.operations_capacity_port import (
    ChannelCapacity,
    OperationsCapacityRecord,
)
from src.infrastructure.persistence.database.dynamodb.client import get_dynamodb_resource
from src.infrastructure.persistence.database.dynamodb.repositories.configuration_repository import (
    DynamoConfigurationRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.fraud_playbook_repository import (
    DynamoFraudPlaybookRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.operations_capacity_repository import (
    DynamoOperationsCapacityRepository,
)
from src.infrastructure.persistence.database.dynamodb.schemas import (
    ALERTS_TABLE,
    ASYNC_OPERATIONS_TABLE,
    AUDIT_LOG_TABLE,
    CONFIGURATIONS_TABLE,
    FRAUD_PLAYBOOKS_TABLE,
    OPERATIONS_CAPACITY_TABLE,
    TEST_RUNS_TABLE,
    WORKFLOW_EXECUTIONS_TABLE,
    WORKFLOW_STEP_EXECUTIONS_TABLE,
)

# Seeded once, only if missing - reference/ops data, not per-alert state.
_DEFAULT_PLAYBOOKS = [
    FraudPlaybookRecord(
        classification="ACCOUNT_TAKEOVER",
        title="Account takeover response playbook",
        steps=[
            "Verify the device/session change against the customer's known "
            "device and location history.",
            "Check for a recent credential or personal data change "
            "preceding the transaction.",
            "If identity cannot be confirmed with available signals, "
            "require step-up verification before releasing funds.",
            "If confirmed fraud, block the transaction and freeze the "
            "affected channel.",
        ],
        # Placeholder timestamps - this list is a template read by
        # seed_defaults() below, which stamps the real created_at/updated_at
        # at seed time. Required here only to satisfy the dataclass.
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ),
    FraudPlaybookRecord(
        classification="unknown",
        title="Generic manual review playbook",
        steps=[
            "No specific playbook matched this classification - treat as "
            "inconclusive.",
            "Review available evidence and prefer routing to a human "
            "analyst over an automated decision.",
        ],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ),
]

_DEFAULT_CAPACITY = OperationsCapacityRecord(
    analysts=ChannelCapacity(available=5, status="available"),
    voicebot=ChannelCapacity(available=20, status="available"),
    bidi=ChannelCapacity(available=10, status="available"),
    updated_at=datetime.now(timezone.utc),
)

# Seeded once (see seed_defaults) so a fresh environment always has exactly
# one active configuration, rather than every consumer needing a None-active
# fallback. All sub-settings use their dataclass defaults - see
# application/ports/configuration_port.py. Fixed id (not uuid4()) so the
# "already seeded?" check below is stable across process restarts.
_DEFAULT_CONFIGURATION_ID = "default"


def create_table(schema: dict) -> None:
    """Create a DynamoDB table from a boto3-style schema. Idempotent if table already exists."""
    dynamodb = get_dynamodb_resource()
    table_name = schema["TableName"]
    try:
        dynamodb.create_table(**schema)
        table = dynamodb.Table(table_name)
        table.wait_until_exists()
        print(f"Tabla creada: {table_name}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print(f"Tabla ya existe: {table_name}")
        else:
            raise


def ensure_all_tables() -> None:
    """Ensure all DynamoDB tables used by the application exist."""
    create_table(AUDIT_LOG_TABLE)
    create_table(ASYNC_OPERATIONS_TABLE)
    create_table(ALERTS_TABLE)
    create_table(WORKFLOW_EXECUTIONS_TABLE)
    create_table(WORKFLOW_STEP_EXECUTIONS_TABLE)
    create_table(FRAUD_PLAYBOOKS_TABLE)
    create_table(OPERATIONS_CAPACITY_TABLE)
    create_table(TEST_RUNS_TABLE)
    create_table(CONFIGURATIONS_TABLE)


def seed_defaults() -> None:
    """Seed reference/ops data the analyst step depends on, only if
    missing - idempotent, safe to run on every startup."""
    playbooks = DynamoFraudPlaybookRepository()
    for playbook in _DEFAULT_PLAYBOOKS:
        now = datetime.now(timezone.utc)
        if playbooks.get(playbook.classification) is None:
            playbooks.create(
                FraudPlaybookRecord(
                    classification=playbook.classification,
                    title=playbook.title,
                    steps=playbook.steps,
                    created_at=now,
                    updated_at=now,
                )
            )
            print(f"Playbook sembrado: {playbook.classification}")

    capacity_table = get_dynamodb_resource().Table(OPERATIONS_CAPACITY_TABLE["TableName"])
    existing = capacity_table.get_item(Key={"record_id": "current"}).get("Item")
    if existing is None:
        DynamoOperationsCapacityRepository().put_capacity(_DEFAULT_CAPACITY)
        print("Operations capacity sembrada")

    configurations = DynamoConfigurationRepository()
    if configurations.get(_DEFAULT_CONFIGURATION_ID, 1) is None:
        now = datetime.now(timezone.utc)
        default_config = configurations.create(
            ConfigurationRecord(
                configuration_id=_DEFAULT_CONFIGURATION_ID,
                version=1,
                name="Producción",
                description="Configuración por defecto, sembrada al iniciar.",
                active=False,
                general=GeneralSettings(),
                infra=InfraSettings(),
                ops=OpsSettings(),
                monitoring=MonitoringSettings(),
                agent=AgentSettings(),
                test=TestSettings(),
                created_at=now,
                updated_at=now,
            )
        )
        configurations.activate(
            default_config.configuration_id, default_config.version
        )
        print("Configuración por defecto sembrada y activada")


def drop_table(table_name: str) -> None:
    """Elimina una tabla DynamoDB. Idempotente si no existe."""
    dynamodb = get_dynamodb_resource()
    try:
        table = dynamodb.Table(table_name)
        table.delete()
        table.wait_until_not_exists()
        print(f"Tabla eliminada: {table_name}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            print(f"Tabla no existía: {table_name}")
        else:
            raise


def recreate_table(schema: dict) -> None:
    """Elimina y recrea una tabla con el esquema actualizado. Pierde todos los datos."""
    drop_table(schema["TableName"])
    create_table(schema)


if __name__ == "__main__":
    ensure_all_tables()
    seed_defaults()
