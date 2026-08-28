import uuid
from datetime import datetime, timezone

from botocore.exceptions import ClientError

from src.application.ports.configuration_port import (
    ConfigurationRecord,
    GeneralSettings,
    InfraSettings,
    OpsSettings,
    ResolutionTag,
    TestSettings,
)
from src.application.ports.fraud_playbook_port import FraudPlaybookRecord
from src.application.ports.marcacion_catalog_port import MarcacionCategory, RiskLabel
from src.application.ports.resolution_method_catalog_port import ResolutionMethod
from src.application.ports.operations_capacity_port import (
    ChannelCapacity,
    OperationsCapacityRecord,
)
from src.application.ports.tag_catalog_port import TagCategory, TagEntry
from src.application.ports.variable_catalog_port import VariableEntry
from src.infrastructure.persistence.database.dynamodb.client import get_dynamodb_resource
from src.infrastructure.persistence.database.dynamodb.repositories.configuration_repository import (
    DynamoConfigurationRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.fraud_playbook_repository import (
    DynamoFraudPlaybookRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.marcacion_catalog_repository import (
    DynamoMarcacionCatalogRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.flag_library_repository import (
    DynamoFlagLibraryRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.modus_operandi_library_repository import (
    DynamoModusOperandiLibraryRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.operations_capacity_repository import (
    DynamoOperationsCapacityRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.resolution_method_catalog_repository import (
    DynamoResolutionMethodCatalogRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.similar_case_library_repository import (
    DynamoSimilarCaseLibraryRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.taxonomy_library_repository import (
    DynamoTaxonomyLibraryRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.tag_catalog_repository import (
    DynamoTagCatalogRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.variable_catalog_repository import (
    DynamoVariableCatalogRepository,
)
from src.infrastructure.persistence.database.dynamodb.schemas import (
    ALERTS_TABLE,
    ASYNC_OPERATIONS_TABLE,
    AUDIT_LOG_TABLE,
    CONFIGURATION_ANALYST_PROFILES_TABLE,
    CONFIGURATION_EVALUATION_TABLE,
    CONFIGURATION_EXAMPLES_TABLE,
    CONFIGURATION_FIELD_CATEGORIZATIONS_TABLE,
    CONFIGURATION_FILTER_CONDITIONS_TABLE,
    CONFIGURATION_FILTER_GROUPS_TABLE,
    CONFIGURATION_GENERAL_TABLE,
    CONFIGURATION_INFRASTRUCTURE_TABLE,
    CONFIGURATION_MODUS_OPERANDI_TABLE,
    CONFIGURATION_OPERATIONS_TABLE,
    CONFIGURATION_PLAYBOOKS_TABLE,
    CONFIGURATION_PROFILING_STRATEGIES_TABLE,
    CONFIGURATION_RED_YELLOW_FLAGS_TABLE,
    CONFIGURATION_SAMPLING_CRITERIA_TABLE,
    CONFIGURATION_SAMPLING_CRITERIA_VALUES_TABLE,
    CONFIGURATION_SEGMENTS_TABLE,
    CONFIGURATION_TAXONOMIES_TABLE,
    CONFIGURATION_VOICEBOT_PROMPTS_TABLE,
    CONFIGURATIONS_TABLE,
    DATASET_SAMPLES_TABLE,
    DATASET_SUMMARIES_TABLE,
    FRAUD_PLAYBOOKS_TABLE,
    LIBRARY_FLAGS_TABLE,
    LIBRARY_MODUS_OPERANDI_TABLE,
    LIBRARY_SIMILAR_CASES_TABLE,
    LIBRARY_TAXONOMIES_TABLE,
    MARCACION_CATALOG_TABLE,
    OPERATIONS_CAPACITY_TABLE,
    RESOLUTION_METHOD_CATALOG_TABLE,
    TAG_CATALOG_TABLE,
    TEST_RUNS_TABLE,
    VARIABLE_CATALOG_TABLE,
    WATCHLIST_TABLE,
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

# Small illustrative starter set per category - the real ~40+ triggered-rule
# catalog from the fraud team is loaded later via POST /tag-catalog (or a
# one-off seed script), not baked into the boot path. No integration_point
# examples were provided, so that category starts empty until an admin adds
# entries through the UI.
_DEFAULT_TAGS: list[tuple[TagCategory, str]] = [
    (TagCategory.TRIGGERED_RULE, "CUSTOMER - dg_no_digital"),
    (TagCategory.TRIGGERED_RULE, "CUSTOMER - Score1000Net"),
    (TagCategory.TRIGGERED_RULE, "CUSTOMER - Lista_Negra_DeviceID"),
    (TagCategory.TRIGGERED_RULE, "CUSTOMER - dg_modelosfs099"),
    (TagCategory.TRIGGERED_RULE, "CUSTOMER - ListaNegraMUID"),
    (TagCategory.TRIGGERED_RULE, "CUSTOMER - Score1000PSE"),
    (TagCategory.TRIGGERED_RULE, "CUSTOMER - dg_breb_montomax"),
    (TagCategory.EVENT_TYPE, "authentication: login por primera vez"),
    (
        TagCategory.EVENT_TYPE,
        "updateDetails: alerta eventos sobre autenticacion outOfBank",
    ),
]

# Small illustrative starter set - the real ~20-entry "Razón de marcación"
# catalog from the fraud team is loaded later via POST /marcacion-catalog,
# not baked into the boot path.
_DEFAULT_MARCACION_CATEGORIES: list[tuple[str, RiskLabel]] = [
    ("NF___FALSO_POSITIVO", RiskLabel.NO_RISK),
    ("NF___CLIENTE_RECONOCE_OPERACION", RiskLabel.NO_RISK),
    ("FR___ESTAFA", RiskLabel.RISK_SUSPECTED),
    ("FR___SUPLANTACION_DE_IDENTIDAD", RiskLabel.RISK_SUSPECTED),
    ("FR___TOMA_DE_CONTROL_DE_CUENTA", RiskLabel.RISK_SUSPECTED),
    ("FR___LAVADO_DE_ACTIVOS", RiskLabel.RISK_SUSPECTED),
]

# One default method per existing ResolutionTag so playbooks keep working
# out of the box once the "Resolución" dropdown switches from that fixed
# enum to this catalog - admins can rename/add alongside these.
_DEFAULT_RESOLUTION_METHODS: list[tuple[str, ResolutionTag]] = [
    ("Escalar a analista", ResolutionTag.SCALE_TO_ANALYST),
    ("Enviar a voicebot", ResolutionTag.SEND_TO_VOICEBOT),
    ("Resolver con ARIA", ResolutionTag.HANDLE_BY_ARIA),
]

# Starter pool matching the frontend's previous hardcoded ALL_VARIABLES
# (data/configs.ts) so existing VariablePicker usages keep working once the
# picker switches from that const to this catalog - admins can add/retire
# from here afterward.
_DEFAULT_VARIABLES: list[str] = [
    "Altamira", "Documento", "Celular", "Nombre del cliente", "Teléfono adicional",
    "Segmento", "Fecha de alta", "Correo", "Saldo", "Dirección", "Fecha de nacimiento",
    "Segmento empresa", "País de origen", "Canal de ingreso", "Tipo de cuenta",
    "Última transacción", "Número de cuenta", "Oficina", "Producto",
]


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
    create_table(CONFIGURATION_GENERAL_TABLE)
    create_table(CONFIGURATION_INFRASTRUCTURE_TABLE)
    create_table(CONFIGURATION_OPERATIONS_TABLE)
    create_table(CONFIGURATION_EVALUATION_TABLE)
    create_table(CONFIGURATION_ANALYST_PROFILES_TABLE)
    create_table(CONFIGURATION_SEGMENTS_TABLE)
    create_table(CONFIGURATION_PROFILING_STRATEGIES_TABLE)
    create_table(CONFIGURATION_FIELD_CATEGORIZATIONS_TABLE)
    create_table(CONFIGURATION_TAXONOMIES_TABLE)
    create_table(CONFIGURATION_MODUS_OPERANDI_TABLE)
    create_table(CONFIGURATION_RED_YELLOW_FLAGS_TABLE)
    create_table(CONFIGURATION_EXAMPLES_TABLE)
    create_table(CONFIGURATION_PLAYBOOKS_TABLE)
    create_table(CONFIGURATION_VOICEBOT_PROMPTS_TABLE)
    create_table(CONFIGURATION_SAMPLING_CRITERIA_TABLE)
    create_table(CONFIGURATION_SAMPLING_CRITERIA_VALUES_TABLE)
    create_table(CONFIGURATION_FILTER_GROUPS_TABLE)
    create_table(CONFIGURATION_FILTER_CONDITIONS_TABLE)
    create_table(DATASET_SAMPLES_TABLE)
    create_table(DATASET_SUMMARIES_TABLE)
    create_table(TAG_CATALOG_TABLE)
    create_table(MARCACION_CATALOG_TABLE)
    create_table(RESOLUTION_METHOD_CATALOG_TABLE)
    create_table(VARIABLE_CATALOG_TABLE)
    create_table(LIBRARY_TAXONOMIES_TABLE)
    create_table(LIBRARY_MODUS_OPERANDI_TABLE)
    create_table(LIBRARY_FLAGS_TABLE)
    create_table(LIBRARY_SIMILAR_CASES_TABLE)
    create_table(WATCHLIST_TABLE)


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
                test=TestSettings(),
                created_at=now,
                updated_at=now,
            )
        )
        configurations.activate(
            default_config.configuration_id, default_config.version
        )
        print("Configuración por defecto sembrada y activada")

    tags = DynamoTagCatalogRepository()
    by_category: dict[TagCategory, set[str]] = {}
    for category, value in _DEFAULT_TAGS:
        existing_values = by_category.setdefault(
            category,
            {entry.value for entry in tags.list_by_category(category)},
        )
        if value not in existing_values:
            now = datetime.now(timezone.utc)
            tags.create(
                TagEntry(
                    id=str(uuid.uuid4()),
                    category=category,
                    value=value,
                    created_at=now,
                    updated_at=now,
                )
            )
            existing_values.add(value)
            print(f"Tag sembrado: {category.value}/{value}")

    marcacion = DynamoMarcacionCatalogRepository()
    existing_marcacion_values = {entry.value for entry in marcacion.list()}
    for value, risk_label in _DEFAULT_MARCACION_CATEGORIES:
        if value not in existing_marcacion_values:
            now = datetime.now(timezone.utc)
            marcacion.create(
                MarcacionCategory(
                    id=str(uuid.uuid4()),
                    value=value,
                    risk_label=risk_label,
                    created_at=now,
                    updated_at=now,
                )
            )
            existing_marcacion_values.add(value)
            print(f"Categoría de marcación sembrada: {value}")

    resolution_methods = DynamoResolutionMethodCatalogRepository()
    existing_method_values = {entry.value for entry in resolution_methods.list()}
    for value, tag in _DEFAULT_RESOLUTION_METHODS:
        if value not in existing_method_values:
            now = datetime.now(timezone.utc)
            resolution_methods.create(
                ResolutionMethod(
                    id=str(uuid.uuid4()),
                    value=value,
                    resolution_tag=tag,
                    created_at=now,
                    updated_at=now,
                )
            )
            existing_method_values.add(value)
            print(f"Método de resolución sembrado: {value}")

    variables = DynamoVariableCatalogRepository()
    existing_variable_values = {entry.value for entry in variables.list()}
    for value in _DEFAULT_VARIABLES:
        if value not in existing_variable_values:
            now = datetime.now(timezone.utc)
            variables.create(
                VariableEntry(
                    id=str(uuid.uuid4()),
                    value=value,
                    created_at=now,
                    updated_at=now,
                )
            )
            existing_variable_values.add(value)
            print(f"Variable sembrada: {value}")


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
