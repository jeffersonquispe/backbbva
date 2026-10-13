from __future__ import annotations

from functools import lru_cache

from src.application.ports.async_operation_port import AsyncOperationRepository
from src.application.ports.model_port import ModelRepository
from src.application.ports.model_training_dispatcher_port import (
    ModelTrainingDispatcher,
)
from src.application.use_cases.models.activate_model import ActivateModelUseCase
from src.application.use_cases.models.create_model import CreateModelUseCase
from src.application.use_cases.models.delete_model import DeleteModelUseCase
from src.application.use_cases.models.get_model import GetModelUseCase
from src.application.use_cases.models.list_models import ListModelsUseCase
from src.application.use_cases.models.start_model_training import (
    StartModelTrainingUseCase,
)
from src.infrastructure.persistence.database.dynamodb.repositories.async_operation_repository import (
    DynamoAsyncOperationRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.model_repository import (
    DynamoModelRepository,
)


@lru_cache
def get_model_repository() -> ModelRepository:
    return DynamoModelRepository()


@lru_cache
def get_model_async_operation_repository() -> AsyncOperationRepository:
    return DynamoAsyncOperationRepository()


@lru_cache
def get_model_training_dispatcher() -> ModelTrainingDispatcher:
    # Lazy import - keeps celery out of the API process's import graph until
    # a training run is actually requested, matching
    # dataset_factory.py::get_dataset_analysis_dispatcher()'s pattern.
    from src.infrastructure.queues.celery.model_training_dispatcher import (
        CeleryModelTrainingDispatcher,
    )

    return CeleryModelTrainingDispatcher()


def get_create_model_use_case() -> CreateModelUseCase:
    return CreateModelUseCase(get_model_repository())


def get_list_models_use_case() -> ListModelsUseCase:
    return ListModelsUseCase(get_model_repository())


def get_get_model_use_case() -> GetModelUseCase:
    return GetModelUseCase(get_model_repository())


def get_delete_model_use_case() -> DeleteModelUseCase:
    return DeleteModelUseCase(get_model_repository())


def get_activate_model_use_case() -> ActivateModelUseCase:
    return ActivateModelUseCase(get_model_repository())


def get_start_model_training_use_case() -> StartModelTrainingUseCase:
    return StartModelTrainingUseCase(
        model_repository=get_model_repository(),
        async_operation_repository=get_model_async_operation_repository(),
        training_dispatcher=get_model_training_dispatcher(),
    )


@lru_cache
def get_feature_template_repository():
    from src.infrastructure.persistence.database.dynamodb.repositories.feature_template_repository import (
        DynamoFeatureTemplateRepository,
    )

    return DynamoFeatureTemplateRepository()


def get_feature_templates_use_case():
    from src.application.use_cases.models.feature_engineering import (
        FeatureTemplatesUseCase,
    )

    return FeatureTemplatesUseCase(get_feature_template_repository())


def get_preview_features_use_case():
    from src.application.use_cases.models.feature_engineering import (
        PreviewFeaturesUseCase,
    )

    return PreviewFeaturesUseCase()


def get_feature_capabilities_use_case():
    from src.application.use_cases.models.feature_engineering import (
        FeatureCapabilitiesUseCase,
    )

    return FeatureCapabilitiesUseCase()
