from functools import lru_cache

from src.infrastructure.persistence.database.dynamodb.repositories.configuration_deploy_request_repository import (
    DynamoConfigurationDeployRequestRepository,
)


@lru_cache
def get_configuration_deploy_request_repository() -> (
    DynamoConfigurationDeployRequestRepository
):
    return DynamoConfigurationDeployRequestRepository()
