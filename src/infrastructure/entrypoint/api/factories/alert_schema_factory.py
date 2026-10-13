from functools import lru_cache

from src.application.use_cases.alert_schema.analyze_impact import (
    AlertSchemaImpactAnalyzer,
)
from src.application.use_cases.alert_schema.analyze_presence import (
    AnalyzeAlertSchemaPresenceUseCase,
)
from src.application.use_cases.alert_schema.approve_schema import (
    ApproveAlertSchemaUseCase,
)
from src.application.use_cases.alert_schema.create_suggestion import (
    CreateAlertSchemaSuggestionUseCase,
    ListAlertSchemaSuggestionsUseCase,
)
from src.application.use_cases.alert_schema.get_active_schema import (
    GetActiveAlertSchemaUseCase,
)
from src.application.use_cases.alert_schema.list_schema_versions import (
    GetAlertSchemaVersionUseCase,
    ListAlertSchemaVersionsUseCase,
)
from src.application.use_cases.alert_schema.propose_schema import (
    ProposeAlertSchemaUseCase,
)
from src.application.use_cases.alert_schema.reject_schema import (
    RejectAlertSchemaUseCase,
)
from src.application.use_cases.alert_schema.save_schema_draft import (
    SaveAlertSchemaDraftUseCase,
)
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.entrypoint.api.factories.alert_factory import (
    get_alert_repository,
)
from src.infrastructure.entrypoint.api.factories.configuration_factory import (
    get_configuration_repository,
)
from src.infrastructure.entrypoint.api.factories.model_factory import (
    get_model_repository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.alert_schema_presence_repository import (
    DynamoAlertSchemaPresenceReportRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.alert_schema_repository import (
    DynamoAlertSchemaRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.alert_schema_suggestion_repository import (
    DynamoAlertSchemaSuggestionRepository,
)


@lru_cache
def get_alert_schema_repository():
    return DynamoAlertSchemaRepository()


@lru_cache
def get_alert_schema_suggestion_repository():
    return DynamoAlertSchemaSuggestionRepository()


@lru_cache
def get_alert_schema_presence_report_repository():
    return DynamoAlertSchemaPresenceReportRepository()


def get_get_active_alert_schema_use_case():
    return GetActiveAlertSchemaUseCase(get_alert_schema_repository())


def get_list_alert_schema_versions_use_case():
    return ListAlertSchemaVersionsUseCase(get_alert_schema_repository())


def get_get_alert_schema_version_use_case():
    return GetAlertSchemaVersionUseCase(get_alert_schema_repository())


def get_save_alert_schema_draft_use_case():
    return SaveAlertSchemaDraftUseCase(get_alert_schema_repository())


def get_propose_alert_schema_use_case():
    return ProposeAlertSchemaUseCase(
        get_alert_schema_repository(),
        AlertSchemaImpactAnalyzer(
            get_configuration_repository(), get_model_repository()
        ),
        clock=get_clock(),
    )


def get_approve_alert_schema_use_case():
    return ApproveAlertSchemaUseCase(get_alert_schema_repository(), clock=get_clock())


def get_reject_alert_schema_use_case():
    return RejectAlertSchemaUseCase(get_alert_schema_repository())


def get_create_alert_schema_suggestion_use_case():
    return CreateAlertSchemaSuggestionUseCase(
        get_alert_schema_suggestion_repository(),
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


def get_list_alert_schema_suggestions_use_case():
    return ListAlertSchemaSuggestionsUseCase(get_alert_schema_suggestion_repository())


def get_alert_schema_presence_use_case():
    return AnalyzeAlertSchemaPresenceUseCase(
        get_alert_repository(),
        get_alert_schema_repository(),
        get_alert_schema_presence_report_repository(),
        clock=get_clock(),
    )
