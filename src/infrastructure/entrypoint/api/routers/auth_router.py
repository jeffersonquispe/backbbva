from __future__ import annotations

import hmac
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.use_cases.auth.local_auth import (
    AuthenticateLocalUserUseCase, DuplicateEmailError, GetCurrentLocalUserUseCase,
    InvalidCredentialsError, RegisterLocalUserUseCase, permissions_for,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.entrypoint.api.factories.local_auth_factory import (
    get_authenticate_local_user_use_case, get_current_local_user_use_case,
    get_jwt_service, get_register_local_user_use_case,
)
from src.infrastructure.security.local_auth import JwtService

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=256)


class CreateLocalUserRequest(LoginRequest):
    name: str = Field(min_length=1, max_length=160)
    role: LocalRole


class UserResponse(BaseModel):
    id: UUID
    email: str
    name: str
    role: LocalRole
    permissions: list[str]


class LoginResponse(UserResponse):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


def _to_user_response(user: LocalUser) -> UserResponse:
    return UserResponse(id=user.id, email=user.email, name=user.name, role=user.role, permissions=permissions_for(user.role))


def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    jwt_service: Annotated[JwtService, Depends(get_jwt_service)] = None,
    use_case: Annotated[GetCurrentLocalUserUseCase, Depends(get_current_local_user_use_case)] = None,
) -> LocalUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = jwt_service.decode(authorization.removeprefix("Bearer "))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc), headers={"WWW-Authenticate": "Bearer"}) from exc
    user = use_case.execute(UUID(claims["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive", headers={"WWW-Authenticate": "Bearer"})
    return user


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_local_user(
    request: CreateLocalUserRequest,
    bootstrap_token: Annotated[str | None, Header(alias="X-Bootstrap-Token")] = None,
    use_case: Annotated[RegisterLocalUserUseCase, Depends(get_register_local_user_use_case)] = None,
):
    if not genai_config.AUTH_BOOTSTRAP_TOKEN or not bootstrap_token or not hmac.compare_digest(bootstrap_token, genai_config.AUTH_BOOTSTRAP_TOKEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A valid bootstrap token is required to create local users")
    try:
        return _to_user_response(use_case.execute(email=str(request.email), name=request.name, password=request.password, role=request.role))
    except DuplicateEmailError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/login", response_model=LoginResponse)
def login(
    request: LoginRequest,
    use_case: Annotated[AuthenticateLocalUserUseCase, Depends(get_authenticate_local_user_use_case)],
):
    try:
        authenticated = use_case.execute(email=str(request.email), password=request.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password", headers={"WWW-Authenticate": "Bearer"}) from exc
    return LoginResponse(**_to_user_response(authenticated.user).model_dump(), access_token=authenticated.access_token, expires_in=authenticated.expires_in)


@router.get("/me", response_model=UserResponse)
def me(user: Annotated[LocalUser, Depends(get_current_user)]):
    return _to_user_response(user)
