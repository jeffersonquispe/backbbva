import time
import uuid
from datetime import datetime, timezone

from botocore.exceptions import ClientError

from src.application.ports.configuration_port import (
    ConfigurationRecord,
    GeneralSettings,
    InfraSettings,
    ResolutionTag,
    TestSettings,
)
from src.application.ports.channel_library_port import ChannelLibraryEntry
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
from src.infrastructure.persistence.database.dynamodb.repositories.channel_library_repository import (
    DynamoChannelLibraryRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.tag_catalog_repository import (
    DynamoTagCatalogRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.variable_catalog_repository import (
    DynamoVariableCatalogRepository,
)
from src.infrastructure.persistence.database.dynamodb.schemas import (
    ALERT_FIELD_MAPPINGS_TABLE,
    ALERTS_TABLE,
    ASYNC_OPERATIONS_TABLE,
    AUDIT_LOG_TABLE,
    CONFIGURATION_EVALUATION_TABLE,
    CONFIGURATION_EXAMPLES_TABLE,
    CONFIGURATION_FILTER_CONDITIONS_TABLE,
    CONFIGURATION_FILTER_GROUPS_TABLE,
    CONFIGURATION_GENERAL_TABLE,
    CONFIGURATION_INFRASTRUCTURE_TABLE,
    CONFIGURATION_MODUS_OPERANDI_TABLE,
    CONFIGURATION_PROFILING_STRATEGIES_TABLE,
    CONFIGURATION_RED_YELLOW_FLAGS_TABLE,
    CONFIGURATION_SAMPLING_CRITERIA_TABLE,
    CONFIGURATION_SAMPLING_CRITERIA_VALUES_TABLE,
    CONFIGURATION_SEGMENTS_TABLE,
    CONFIGURATION_TAXONOMIES_TABLE,
    CONFIGURATION_VOICEBOT_PROMPTS_TABLE,
    CONFIGURATIONS_TABLE,
    CONFIGURATION_DEPLOY_REQUESTS_TABLE,
    ALERT_SCHEMA_VERSIONS_TABLE,
    ALERT_SCHEMA_PRESENCE_REPORTS_TABLE,
    ALERT_SCHEMA_SUGGESTIONS_TABLE,
    DATASET_SAMPLES_TABLE,
    DATASET_SUMMARIES_TABLE,
    FEEDBACK_TABLE,
    FRAUD_LABEL_REVIEWS_TABLE,
    LIBRARY_CHANNELS_TABLE,
    LIBRARY_FLAGS_TABLE,
    LIBRARY_MODUS_OPERANDI_TABLE,
    LIBRARY_SIMILAR_CASES_TABLE,
    LIBRARY_TAXONOMIES_TABLE,
    METRICS_ROLLUPS_TABLE,
    ALERT_REASONING_EVALUATIONS_TABLE,
    VECTOR_STORE_INSTANCE_ASSETS_TABLE,
    VECTOR_STORE_INSTANCES_TABLE,
    MARCACION_CATALOG_TABLE,
    MODELS_TABLE,
    OPERATIONAL_SETTINGS_HISTORY_TABLE,
    OPERATIONAL_SETTINGS_TABLE,
    OPERATIONS_CAPACITY_TABLE,
    RESOURCE_LOCKS_TABLE,
    RESOURCE_RESERVATIONS_TABLE,
    REVOKED_TOKENS_TABLE,
    RESOLUTION_METHOD_CATALOG_TABLE,
    TAG_CATALOG_TABLE,
    TEST_RUNS_TABLE,
    VARIABLE_CATALOG_TABLE,
    WATCHLIST_ELEMENTS_TABLE,
    WATCHLIST_TABLE,
    WORKFLOW_EXECUTIONS_TABLE,
    WORKFLOW_STEP_EXECUTIONS_TABLE,
    USERS_TABLE,
)

# Seeded once, only if missing - only its bidi entry is read today (analyst
# and voicebot availability are computed live, see LiveOperationsCapacity).
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

# Source-variable schema from Muestra_total_ARIA_Ver2_2.csv.  Names and casing
# intentionally match the file headers exactly.  The leading unnamed pandas
# index column is not alert data and is therefore omitted.  Derived variables
# created by profiling are kept separately, as recipe names in
# ProfilingConfig.field_enrichment (see EnrichProfilingFieldsUseCase).
_DEFAULT_VARIABLES: list[str] = [
    "reviewstatus_first",
    "marcacion_final",
    "razon_marcacion",
    "eventtype",
    "channel",
    "integrationpoint",
    "biocatch_score",
    "Model_score",
    "amount_value",
    "fecha_transaccion",
    "fecha_primer_marcacion",
    "fecha_ultima_marcacion",
    "biocatch_isMobileRat",
    "biocatch_isEmulator",
    "biocatch_isRat",
    "biocatch_isBot",
    "biocatch_indrobo1",
    "biocatch_isOnCall",
    "biocatch_isVoipOnCall",
    "biocatch_screenBroadcast",
    "deviceid",
    "eventid",
    "triggered_rules",
    "device_ipaddress_encrypted",
    "counterpartyentityid_encrypted",
    "customerid",
    "transactionid",
    "output_tags",
    "tipo_documento",
    "numero_documento",
    "nombre_razon_social",
    "fecha_nacimiento",
    "sexo",
    "fecha_expedicion_documento",
    "indicador_revinculado",
    "codigo_ciudad",
    "ciudad",
    "empleado_banco",
    "fecha_alta",
    "direccion",
    "correo_1",
    "correo_2",
    "celular",
    "fecha_ultima_modificacion",
    "MontoMasAltoPSE",
    "MontoMasAltoPasarelaPago",
    "MontoMasAltoBreB",
    "MontoMasAltoGlomo",
    "MontoMasAltoNet",
    "MontoMasAltoPrestamo",
    "MontoMasAltoFacturas",
    "MontoMasAltoRetirosTarjeta",
    "tipo",
    "transacciones_json",
]

# Defaults used before the source schema was aligned with
# Muestra_total_ARIA_Ver2_2.csv.  They are retained only to migrate an existing
# catalog once: deactivation hides them from active pickers without breaking
# historical configurations that still reference their values.
_LEGACY_DEFAULT_VARIABLES = {
    "Altamira",
    "Documento",
    "Celular",
    "Nombre del cliente",
    "Teléfono adicional",
    "Segmento",
    "Fecha de alta",
    "Correo",
    "Saldo",
    "Dirección",
    "Fecha de nacimiento",
    "Segmento empresa",
    "País de origen",
    "Canal de ingreso",
    "Tipo de cuenta",
    "Última transacción",
    "Número de cuenta",
    "Oficina",
    "Producto",
    "CoT (cadena de razonamiento)",
    "Variables de entrada",
    "Score de confianza",
    "Taxonomía asignada",
    "Red flag detectada",
    "Prompt utilizado",
    "Latencia de respuesta",
    "Resultado final",
}

# One entry per existing SegmentCode value so configs keep working out of
# the box once segments switch from that fixed enum to this catalog -
# admins can rename/add/deactivate alongside these.
_DEFAULT_CHANNELS: list[tuple[str, str]] = [
    ("canales_digitales", "Canales digitales"),
    ("tarjetas", "Tarjetas"),
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


def enable_ttl(schema: dict, attribute: str) -> None:
    """Turn on DynamoDB TTL for a table. Idempotent; best effort, since the
    readers never rely on TTL deletion for correctness."""
    try:
        get_dynamodb_resource().meta.client.update_time_to_live(
            TableName=schema["TableName"],
            TimeToLiveSpecification={"Enabled": True, "AttributeName": attribute},
        )
    except ClientError as e:
        print(f"TTL no aplicado en {schema['TableName']}: {e.response['Error']['Code']}")


def _wait_for_index(client, table_name: str, index_name: str, timeout_s: int = 300) -> None:
    """Block until the new GSI is ACTIVE (the table itself stays ACTIVE
    while the index backfills; writes right after creation can fail)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        indexes = client.describe_table(TableName=table_name)["Table"].get(
            "GlobalSecondaryIndexes"
        ) or []
        status = next(
            (i.get("IndexStatus") for i in indexes if i["IndexName"] == index_name), None
        )
        if status == "ACTIVE":
            return
        time.sleep(1)


def ensure_global_secondary_indexes(schema: dict) -> None:
    """Add any GSI declared in the schema that an already-existing table is
    missing (create_table only applies them to new tables). Idempotent; one
    index per UpdateTable call, as DynamoDB requires."""
    client = get_dynamodb_resource().meta.client
    table_name = schema["TableName"]
    description = client.describe_table(TableName=table_name)["Table"]
    existing = {
        index["IndexName"] for index in description.get("GlobalSecondaryIndexes") or []
    }
    definitions = {
        attribute["AttributeName"]: attribute
        for attribute in schema["AttributeDefinitions"]
    }
    for index in schema.get("GlobalSecondaryIndexes") or []:
        if index["IndexName"] in existing:
            continue
        key_attributes = [key["AttributeName"] for key in index["KeySchema"]]
        create: dict = {
            "IndexName": index["IndexName"],
            "KeySchema": index["KeySchema"],
            "Projection": index["Projection"],
        }
        if "ProvisionedThroughput" in index:
            create["ProvisionedThroughput"] = index["ProvisionedThroughput"]
        try:
            client.update_table(
                TableName=table_name,
                AttributeDefinitions=[definitions[name] for name in key_attributes],
                GlobalSecondaryIndexUpdates=[{"Create": create}],
            )
            _wait_for_index(client, table_name, index["IndexName"])
            print(f"Índice creado: {table_name}.{index['IndexName']}")
        except ClientError as e:
            print(
                f"Índice no creado {table_name}.{index['IndexName']}: "
                f"{e.response['Error']['Code']}"
            )


def ensure_all_tables() -> None:
    """Ensure all DynamoDB tables used by the application exist."""
    create_table(AUDIT_LOG_TABLE)
    create_table(USERS_TABLE)
    create_table(REVOKED_TOKENS_TABLE)
    enable_ttl(REVOKED_TOKENS_TABLE, "expires_at")
    create_table(ASYNC_OPERATIONS_TABLE)
    create_table(ALERTS_TABLE)
    ensure_global_secondary_indexes(ALERTS_TABLE)
    create_table(METRICS_ROLLUPS_TABLE)
    enable_ttl(METRICS_ROLLUPS_TABLE, "expires_at")
    create_table(ALERT_REASONING_EVALUATIONS_TABLE)
    create_table(FRAUD_LABEL_REVIEWS_TABLE)
    create_table(WORKFLOW_EXECUTIONS_TABLE)
    create_table(WORKFLOW_STEP_EXECUTIONS_TABLE)
    create_table(OPERATIONS_CAPACITY_TABLE)
    create_table(OPERATIONAL_SETTINGS_TABLE)
    create_table(OPERATIONAL_SETTINGS_HISTORY_TABLE)
    create_table(RESOURCE_LOCKS_TABLE)
    create_table(RESOURCE_RESERVATIONS_TABLE)
    create_table(TEST_RUNS_TABLE)
    from src.infrastructure.persistence.database.dynamodb.schemas import FEATURE_TEMPLATES_TABLE
    create_table(FEATURE_TEMPLATES_TABLE)
    create_table(MODELS_TABLE)
    create_table(CONFIGURATIONS_TABLE)
    create_table(CONFIGURATION_DEPLOY_REQUESTS_TABLE)
    create_table(ALERT_SCHEMA_VERSIONS_TABLE)
    create_table(ALERT_SCHEMA_PRESENCE_REPORTS_TABLE)
    create_table(ALERT_SCHEMA_SUGGESTIONS_TABLE)
    create_table(CONFIGURATION_GENERAL_TABLE)
    create_table(CONFIGURATION_INFRASTRUCTURE_TABLE)
    create_table(CONFIGURATION_EVALUATION_TABLE)
    create_table(CONFIGURATION_SEGMENTS_TABLE)
    create_table(CONFIGURATION_PROFILING_STRATEGIES_TABLE)
    create_table(CONFIGURATION_TAXONOMIES_TABLE)
    create_table(CONFIGURATION_MODUS_OPERANDI_TABLE)
    create_table(CONFIGURATION_RED_YELLOW_FLAGS_TABLE)
    create_table(CONFIGURATION_EXAMPLES_TABLE)
    create_table(CONFIGURATION_VOICEBOT_PROMPTS_TABLE)
    create_table(CONFIGURATION_SAMPLING_CRITERIA_TABLE)
    create_table(CONFIGURATION_SAMPLING_CRITERIA_VALUES_TABLE)
    create_table(CONFIGURATION_FILTER_GROUPS_TABLE)
    create_table(CONFIGURATION_FILTER_CONDITIONS_TABLE)
    create_table(DATASET_SAMPLES_TABLE)
    create_table(DATASET_SUMMARIES_TABLE)
    create_table(ALERT_FIELD_MAPPINGS_TABLE)
    create_table(FEEDBACK_TABLE)
    create_table(TAG_CATALOG_TABLE)
    create_table(MARCACION_CATALOG_TABLE)
    create_table(RESOLUTION_METHOD_CATALOG_TABLE)
    create_table(VARIABLE_CATALOG_TABLE)
    create_table(LIBRARY_TAXONOMIES_TABLE)
    create_table(LIBRARY_CHANNELS_TABLE)
    create_table(LIBRARY_MODUS_OPERANDI_TABLE)
    create_table(LIBRARY_FLAGS_TABLE)
    create_table(LIBRARY_SIMILAR_CASES_TABLE)
    create_table(VECTOR_STORE_INSTANCES_TABLE)
    create_table(VECTOR_STORE_INSTANCE_ASSETS_TABLE)
    create_table(WATCHLIST_TABLE)
    create_table(WATCHLIST_ELEMENTS_TABLE)


def seed_defaults() -> None:
    """Seed reference/ops data the analyst step depends on, only if
    missing - idempotent, safe to run on every startup."""
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
    existing_variables = variables.list()
    existing_variable_values = {entry.value for entry in existing_variables}
    source_schema_was_present = set(_DEFAULT_VARIABLES).issubset(
        existing_variable_values
    )
    if not source_schema_was_present:
        for entry in existing_variables:
            if entry.active and entry.value in _LEGACY_DEFAULT_VARIABLES:
                variables.update(entry.id, active=False)
                print(f"Variable predeterminada anterior desactivada: {entry.value}")
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

    channels = DynamoChannelLibraryRepository()
    existing_channel_codes = {entry.code for entry in channels.list()}
    for code, name in _DEFAULT_CHANNELS:
        if code not in existing_channel_codes:
            now = datetime.now(timezone.utc)
            channels.create(
                ChannelLibraryEntry(
                    id=str(uuid.uuid4()),
                    code=code,
                    name=name,
                    description="",
                    created_at=now,
                    updated_at=now,
                )
            )
            existing_channel_codes.add(code)
            print(f"Canal sembrado: {code}")


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
