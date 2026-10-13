from __future__ import annotations

from uuid import UUID

from src.application.dtos.model_dtos import StartModelTrainingOutput
from src.application.errors import ConflictError
from src.application.ports.async_operation_port import (
    AsyncOperationRecord,
    AsyncOperationRepository,
    AsyncOperationStatus,
)
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.model_port import ModelRepository, ModelStatus
from src.application.ports.model_training_dispatcher_port import (
    ModelTrainingDispatcher,
)
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)
from src.domain.models.exceptions import (
    ModelNotFoundError,
)

OPERATION_TYPE = "model_training"


class StartModelTrainingUseCase:
    def __init__(
        self,
        model_repository: ModelRepository,
        async_operation_repository: AsyncOperationRepository,
        training_dispatcher: ModelTrainingDispatcher,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._models = model_repository
        self._async_operations = async_operation_repository
        self._dispatcher = training_dispatcher
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(self, model_id: UUID) -> StartModelTrainingOutput:
        model = self._models.get(model_id)
        if model is None:
            raise ModelNotFoundError(model_id)
        # An active model is the one serving (ModelRepository.get_active) -
        # never retrain it in place, whatever its status says.
        if model.active or model.status != ModelStatus.DRAFT:
            raise ConflictError(
                "El modelo solo puede entrenarse una vez; crea un nuevo modelo para volver a entrenar"
            )

        if model.feature_configuration is not None:
            from src.domain.models.feature_recipe import validate_feature_definition

            validate_feature_definition(
                model.feature_configuration, forbidden_paths=(model.target_field,)
            )

        now = self._clock.now()
        operation = self._async_operations.create(
            AsyncOperationRecord(
                id=self._id_generator.new_id(),
                operation_type=OPERATION_TYPE,
                status=AsyncOperationStatus.PENDING,
                payload={"model_id": str(model_id), "tag": model.tag},
                result=None,
                error=None,
                created_at=now,
                updated_at=now,
            )
        )
        model.status = ModelStatus.TRAINING
        model.error = None
        model.metrics = None
        model.training_report = None
        model.updated_at = now
        self._models.update(model)

        try:
            self._dispatcher.dispatch(model_id, operation.id)
        except Exception:
            model.status = ModelStatus.FAILED
            model.error = "No se pudo enviar el entrenamiento a la cola; crea un nuevo modelo para intentarlo de nuevo"
            self._models.update(model)
            self._async_operations.update(
                operation.id, status=AsyncOperationStatus.FAILED, error=model.error
            )
            raise

        return StartModelTrainingOutput(
            async_operation_id=operation.id, model_id=model_id
        )
