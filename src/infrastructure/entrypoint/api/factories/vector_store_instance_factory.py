from functools import lru_cache

from src.application.use_cases.vector_store_instances.create_vector_store_instance import (
    CreateVectorStoreInstanceUseCase,
)
from src.application.use_cases.vector_store_instances.list_vector_store_instances import (
    ListVectorStoreInstancesUseCase,
)
from src.application.use_cases.vector_store_instances.manage_vector_store_instance import (
    AddVectorStoreDocumentUseCase,
    RemoveVectorStoreDocumentUseCase,
    UpdateVectorStoreInstanceUseCase,
)
from src.application.use_cases.vector_store_instances.promote_vector_store_instance import (
    PromoteVectorStoreInstanceUseCase,
)
from src.infrastructure.entrypoint.api.factories.fraud_knowledge_factory import (
    get_fraud_knowledge_repository,
    get_ingest_flag_use_case,
    get_ingest_modus_operandi_use_case,
    get_ingest_similar_case_use_case,
    get_ingest_taxonomia_use_case,
)
from src.infrastructure.persistence.database.dynamodb.repositories.vector_store_instance_repository import (
    DynamoVectorStoreInstanceRepository,
)


def get_knowledge_graph_service():
    from src.application.use_cases.vector_store_instances.knowledge_graph import (
        KnowledgeGraphService,
    )
    from src.infrastructure.entrypoint.api.factories.flag_library_factory import (
        get_flag_library_repository,
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

    return KnowledgeGraphService(
        instances=get_vector_store_instance_repository(),
        taxonomies=get_taxonomy_library_repository(),
        modus_operandi=get_modus_operandi_library_repository(),
        flags=get_flag_library_repository(),
        similar_cases=get_similar_case_library_repository(),
    )


@lru_cache
def get_vector_store_instance_repository() -> DynamoVectorStoreInstanceRepository:
    return DynamoVectorStoreInstanceRepository()


def get_create_vector_store_instance_use_case() -> CreateVectorStoreInstanceUseCase:
    return CreateVectorStoreInstanceUseCase(get_vector_store_instance_repository())


def get_list_vector_store_instances_use_case() -> ListVectorStoreInstancesUseCase:
    return ListVectorStoreInstancesUseCase(get_vector_store_instance_repository())


def get_update_vector_store_instance_use_case() -> UpdateVectorStoreInstanceUseCase:
    return UpdateVectorStoreInstanceUseCase(get_vector_store_instance_repository())


def get_add_vector_store_document_use_case() -> AddVectorStoreDocumentUseCase:
    return AddVectorStoreDocumentUseCase(get_vector_store_instance_repository())


def get_remove_vector_store_document_use_case() -> RemoveVectorStoreDocumentUseCase:
    return RemoveVectorStoreDocumentUseCase(get_vector_store_instance_repository())


def get_promote_vector_store_instance_use_case() -> PromoteVectorStoreInstanceUseCase:
    from src.infrastructure.entrypoint.api.factories.flag_library_factory import (
        get_flag_library_repository,
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

    return PromoteVectorStoreInstanceUseCase(
        instances=get_vector_store_instance_repository(),
        taxonomies=get_taxonomy_library_repository(),
        modus_operandi=get_modus_operandi_library_repository(),
        flags=get_flag_library_repository(),
        similar_cases=get_similar_case_library_repository(),
        fraud_knowledge_repository=get_fraud_knowledge_repository(),
        ingest_taxonomia=get_ingest_taxonomia_use_case(),
        ingest_modus_operandi=get_ingest_modus_operandi_use_case(),
        ingest_flag=get_ingest_flag_use_case(),
        ingest_similar_case=get_ingest_similar_case_use_case(),
    )
