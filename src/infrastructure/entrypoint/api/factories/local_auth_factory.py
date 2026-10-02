from functools import lru_cache

from src.application.use_cases.auth.local_auth import (
    AuthenticateLocalUserUseCase, GetCurrentLocalUserUseCase, LogoutLocalUserUseCase,
    RegisterLocalUserUseCase,
)
from src.infrastructure.persistence.database.dynamodb.repositories.local_user_repository import DynamoLocalUserRepository
from src.infrastructure.persistence.database.dynamodb.repositories.revoked_token_repository import DynamoRevokedTokenRepository
from src.infrastructure.security.local_auth import JwtService, PasswordHasher


@lru_cache
def get_revoked_token_repository() -> DynamoRevokedTokenRepository:
    return DynamoRevokedTokenRepository()


def get_register_local_user_use_case() -> RegisterLocalUserUseCase:
    return RegisterLocalUserUseCase(DynamoLocalUserRepository(), PasswordHasher())


def get_authenticate_local_user_use_case() -> AuthenticateLocalUserUseCase:
    return AuthenticateLocalUserUseCase(DynamoLocalUserRepository(), PasswordHasher(), JwtService())


def get_current_local_user_use_case() -> GetCurrentLocalUserUseCase:
    return GetCurrentLocalUserUseCase(DynamoLocalUserRepository(), get_revoked_token_repository())


def get_logout_local_user_use_case() -> LogoutLocalUserUseCase:
    return LogoutLocalUserUseCase(get_revoked_token_repository())


def get_jwt_service() -> JwtService:
    return JwtService()
