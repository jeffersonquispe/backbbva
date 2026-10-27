from __future__ import annotations

from functools import lru_cache

from src.application.ports.agent_specialist_executor_port import (
    AgentSpecialistExecutor,
)
from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
    SearchFraudKnowledgeUseCase,
)
from src.infrastructure.agents.factories import get_personal_data_masker
from src.infrastructure.agents.optimizer_specialist_executors import (
    ConfigurationSpecialistExecutor,
    LibrarySpecialistExecutor,
    VectorStoreSpecialistExecutor,
    XGBoostSpecialistExecutor,
)


@lru_cache
def get_optimizer_specialist_executors() -> dict[str, AgentSpecialistExecutor]:
    # API factories are reused here as the single composition point for the
    # existing repositories and domain use cases; the executor implementations
    # depend only on application ports/use cases.
    from src.infrastructure.entrypoint.api.factories.configuration_factory import (
        get_configuration_repository,
        get_create_configuration_use_case,
        get_test_configuration_use_case,
    )
    from src.infrastructure.entrypoint.api.factories.fraud_knowledge_factory import (
        get_fraud_knowledge_search_port,
    )
    from src.infrastructure.entrypoint.api.factories.model_factory import (
        get_create_model_use_case,
        get_model_repository,
        get_start_model_training_use_case,
    )
    from src.infrastructure.entrypoint.api.factories.modus_operandi_library_factory import (
        get_modus_operandi_library_repository,
    )
    from src.infrastructure.entrypoint.api.factories.similar_case_library_factory import (
        get_similar_case_library_repository,
    )
    from src.infrastructure.entrypoint.api.factories.taxonomy_library_factory import (
        get_taxonomy_library_repository,
    )
    from src.infrastructure.entrypoint.api.factories.vector_store_instance_factory import (
        get_build_vector_store_generation_use_case,
        get_create_vector_store_instance_use_case,
        get_vector_store_generation_repository,
        get_vector_store_instance_repository,
    )
    from src.infrastructure.entrypoint.api.factories.watchlist_factory import (
        get_watchlist_repository,
    )

    configurations = get_configuration_repository()
    vector_instances = get_vector_store_instance_repository()
    models = get_model_repository()
    return {
        "configuration": ConfigurationSpecialistExecutor(
            configurations=configurations,
            preview=get_test_configuration_use_case(),
            create=get_create_configuration_use_case(),
        ),
        "library": LibrarySpecialistExecutor(
            taxonomies=get_taxonomy_library_repository(),
            modus_operandi=get_modus_operandi_library_repository(),
            similar_cases=get_similar_case_library_repository(),
            watchlists=get_watchlist_repository(),
            masker=get_personal_data_masker(),
        ),
        "vector_store": VectorStoreSpecialistExecutor(
            instances=vector_instances,
            create=get_create_vector_store_instance_use_case(),
            build=get_build_vector_store_generation_use_case(),
            search=SearchFraudKnowledgeUseCase(
                get_fraud_knowledge_search_port(),
                get_vector_store_generation_repository(),
            ),
        ),
        "xgboost": XGBoostSpecialistExecutor(
            models=models,
            create=get_create_model_use_case(),
            start_training=get_start_model_training_use_case(),
        ),
    }
