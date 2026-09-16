from src.application.use_cases.auth.local_auth import (
    AuthenticateLocalUserUseCase, GetCurrentLocalUserUseCase, RegisterLocalUserUseCase,
)
from src.infrastructure.persistence.database.dynamodb.repositories.local_user_repository import DynamoLocalUserRepository
from src.infrastructure.security.local_auth import JwtService, PasswordHasher


def get_register_local_user_use_case() -> RegisterLocalUserUseCase:
    return RegisterLocalUserUseCase(DynamoLocalUserRepository(), PasswordHasher())


def get_authenticate_local_user_use_case() -> AuthenticateLocalUserUseCase:
    return AuthenticateLocalUserUseCase(DynamoLocalUserRepository(), PasswordHasher(), JwtService())


def get_current_local_user_use_case() -> GetCurrentLocalUserUseCase:
    return GetCurrentLocalUserUseCase(DynamoLocalUserRepository())


def get_jwt_service() -> JwtService:
    return JwtService()
