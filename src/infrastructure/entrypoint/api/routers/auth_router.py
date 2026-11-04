from __future__ import annotations

import hmac
import hashlib
import json
import logging
import secrets
import time
import urllib.parse
import urllib.request
import jwt
from jwt import PyJWKClient
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.use_cases.auth.local_auth import (
    AuthenticateLocalUserUseCase,
    ChangeLocalUserPasswordUseCase,
    DuplicateEmailError,
    GetCurrentLocalUserUseCase,
    InvalidCredentialsError,
    ListLocalUsersUseCase,
    LocalUserNotFoundError,
    LogoutLocalUserUseCase,
    RegisterLocalUserUseCase,
    permissions_for,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.entrypoint.api.factories.local_auth_factory import (
    get_authenticate_local_user_use_case,
    get_change_local_user_password_use_case,
    get_current_local_user_use_case,
    get_jwt_service,
    get_local_user_repository,
    get_list_local_users_use_case,
    get_logout_local_user_use_case,
    get_register_local_user_use_case,
)
from src.infrastructure.monitoring.audit_context import (
    current_audit_context,
    update_audit_context,
)
from src.infrastructure.security.local_auth import JwtService, PasswordHasher
from src.application.ports.local_auth_port import LocalUserRepository
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator

logger = logging.getLogger(__name__)
_OIDC_STATE_COOKIE = "aria_oidc_state"
_OIDC_SESSION_COOKIE = "aria_oidc_session"


def _oidc_log(message: str, **fields: object) -> None:
    if genai_config.AUTH_OIDC_LOG_ENABLED:
        logger.info("OIDC %s %s", message, json.dumps(fields, sort_keys=True, default=str))


def _oidc_configured() -> bool:
    return bool(genai_config.AUTH_OIDC_ENABLED and genai_config.AUTH_OIDC_DISCOVERY_URL
        and genai_config.AUTH_OIDC_CLIENT_ID and genai_config.AUTH_OIDC_CLIENT_SECRET
        and genai_config.AUTH_OIDC_REDIRECT_URI)


def _fetch_json(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> dict:
    request = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data else "GET")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read())


def _signed_state(nonce: str) -> str:
    issued = int(time.time())
    payload = f"{issued}.{nonce}"
    signature = hmac.digest(genai_config.AUTH_JWT_SECRET.encode(), payload.encode(), "sha256").hex()
    return f"{payload}.{signature}"


def _verify_state(state: str, cookie: str) -> str:
    if not hmac.compare_digest(state, cookie):
        raise ValueError("OIDC state mismatch")
    issued_raw, nonce, signature = state.split(".", 2)
    payload = f"{issued_raw}.{nonce}"
    expected = hmac.digest(genai_config.AUTH_JWT_SECRET.encode(), payload.encode(), "sha256").hex()
    if not hmac.compare_digest(signature, expected) or int(issued_raw) < int(time.time()) - 600:
        raise ValueError("OIDC state expired or invalid")
    return nonce

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/oidc/enabled")
def oidc_enabled() -> dict[str, bool]:
    return {"enabled": _oidc_configured()}


@router.get("/oidc/start")
def oidc_start():
    if not _oidc_configured():
        raise HTTPException(status_code=404, detail="OIDC login is not enabled")
    metadata = _fetch_json(genai_config.AUTH_OIDC_DISCOVERY_URL)
    nonce = secrets.token_urlsafe(24)
    state = _signed_state(nonce)
    redirect = RedirectResponse(metadata["authorization_endpoint"] + "?" + urllib.parse.urlencode({
        "client_id": genai_config.AUTH_OIDC_CLIENT_ID,
        "response_type": "code", "redirect_uri": genai_config.AUTH_OIDC_REDIRECT_URI,
        "scope": "openid profile email", "state": state, "nonce": nonce,
    }))
    redirect.set_cookie(_OIDC_STATE_COOKIE, state, max_age=600, httponly=True,
        secure=genai_config.AUTH_OIDC_COOKIE_SECURE, samesite="lax", path="/api/v0/auth/oidc")
    _oidc_log("authorization_started")
    return redirect


@router.get("/oidc/callback")
def oidc_callback(request: Request, code: str | None = None, state: str | None = None,
                  error: str | None = None,
                  repository: Annotated[LocalUserRepository, Depends(get_local_user_repository)] = None):
    if not _oidc_configured():
        raise HTTPException(status_code=404, detail="OIDC login is not enabled")
    try:
        if error or not code or not state:
            raise ValueError("Authorization response is incomplete")
        nonce = _verify_state(state, request.cookies.get(_OIDC_STATE_COOKIE, ""))
        metadata = _fetch_json(genai_config.AUTH_OIDC_DISCOVERY_URL)
        form = urllib.parse.urlencode({"grant_type": "authorization_code", "code": code,
            "redirect_uri": genai_config.AUTH_OIDC_REDIRECT_URI,
            "client_id": genai_config.AUTH_OIDC_CLIENT_ID,
            "client_secret": genai_config.AUTH_OIDC_CLIENT_SECRET}).encode()
        tokens = _fetch_json(metadata["token_endpoint"], data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        id_token = tokens["id_token"]
        jwks = PyJWKClient(metadata["jwks_uri"], cache_jwk_set=True, lifespan=300)
        signing_key = jwks.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(id_token, signing_key.key,
            algorithms=["RS256", "RS384", "RS512"],
            audience=genai_config.AUTH_OIDC_CLIENT_ID, issuer=metadata["issuer"],
            options={"require": ["exp", "iat", "iss", "aud", "sub"]})
        if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
            raise ValueError("OIDC nonce mismatch")

        def claim(*names: str) -> str:
            for name in names:
                value = claims.get(name)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return ""

        email = claim("email", "mail", "preferred_username").lower()
        subject = claim("sub", "uid", "employee_id", "employeeId")
        email_verified = claims.get("email_verified")
        if not subject or not email or email_verified is False or str(email_verified).lower() == "false":
            raise ValueError("OIDC identity lacks a stable subject or verified email")
        name = claim("name", "displayName", "display_name") or email
        user = repository.get_by_email(email)
        provisioned = user is None
        if user is None:
            try:
                role = LocalRole(genai_config.AUTH_OIDC_INITIAL_ROLE)
            except ValueError as exc:
                raise ValueError("Invalid AUTH_OIDC_INITIAL_ROLE") from exc
            now = get_clock().now()
            user = repository.create(LocalUser(id=get_id_generator().new_id(), email=email,
                name=name, password_hash=PasswordHasher().hash(secrets.token_urlsafe(48)),
                role=role, is_active=True, created_at=now, updated_at=now))
        if not user.is_active:
            raise ValueError("ARIA account is inactive")
        token, _ = get_jwt_service().issue(user)
        result = RedirectResponse(genai_config.AUTH_OIDC_FRONTEND_URL, status_code=303)
        result.set_cookie(_OIDC_SESSION_COOKIE, token, httponly=True,
            secure=genai_config.AUTH_OIDC_COOKIE_SECURE, samesite="lax",
            max_age=genai_config.AUTH_JWT_TTL_SECONDS, path="/api/v0")
        result.delete_cookie(_OIDC_STATE_COOKIE, path="/api/v0/auth/oidc")
        _oidc_log(
            "authentication_succeeded",
            provisioned=provisioned,
            subject_hash=hashlib.sha256(subject.encode()).hexdigest()[:12],
        )
        return result
    except Exception as exc:
        _oidc_log("authentication_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=401, detail="OIDC authentication failed") from exc


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=256)


class CreateLocalUserRequest(LoginRequest):
    name: str = Field(min_length=1, max_length=160)
    role: LocalRole


class ChangePasswordRequest(BaseModel):
    password: str = Field(min_length=8, max_length=256)


class UserResponse(BaseModel):
    id: UUID
    email: str
    name: str
    role: LocalRole
    permissions: list[str]


class ManagedUserResponse(UserResponse):
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LoginResponse(UserResponse):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


def _to_user_response(user: LocalUser) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        permissions=permissions_for(user.role),
    )


def _to_managed_user_response(user: LocalUser) -> ManagedUserResponse:
    return ManagedUserResponse(
        **_to_user_response(user).model_dump(),
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def require_bootstrap_token(
    request: Request,
    bootstrap_token: Annotated[str | None, Header(alias="X-Bootstrap-Token")] = None,
) -> None:
    """User administration (create/list/reset password) is gated by the
    provisioning token, not by a user session — see `make local-users`."""
    if (
        not genai_config.AUTH_BOOTSTRAP_TOKEN
        or not bootstrap_token
        or not hmac.compare_digest(bootstrap_token, genai_config.AUTH_BOOTSTRAP_TOKEN)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A valid bootstrap token is required to manage local users",
        )
    request.state.audit_actor_id = "bootstrap"
    if current_audit_context().actor_id == "anonymous":
        update_audit_context(actor_type="user", actor_id="bootstrap")


def get_token_claims(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    jwt_service: Annotated[JwtService, Depends(get_jwt_service)] = None,
) -> dict:
    bearer = authorization.removeprefix("Bearer ") if authorization and authorization.startswith("Bearer ") else request.cookies.get(_OIDC_SESSION_COOKIE)
    if not bearer:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return jwt_service.decode(bearer)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_user(
    request: Request,
    claims: Annotated[dict, Depends(get_token_claims)],
    use_case: Annotated[
        GetCurrentLocalUserUseCase, Depends(get_current_local_user_use_case)
    ] = None,
) -> LocalUser:
    user = use_case.execute(UUID(claims["sub"]), token_id=claims.get("jti"))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session ended or user is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    request.state.audit_actor_id = str(user.id)
    if current_audit_context().actor_id == "anonymous":
        update_audit_context(actor_type="user", actor_id=str(user.id))
    return user


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_bootstrap_token)],
)
def create_local_user(
    request: CreateLocalUserRequest,
    use_case: Annotated[
        RegisterLocalUserUseCase, Depends(get_register_local_user_use_case)
    ],
):
    try:
        return _to_user_response(
            use_case.execute(
                email=str(request.email),
                name=request.name,
                password=request.password,
                role=request.role,
            )
        )
    except DuplicateEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.get(
    "/users",
    response_model=list[ManagedUserResponse],
    dependencies=[Depends(require_bootstrap_token)],
)
def list_local_users(
    use_case: Annotated[ListLocalUsersUseCase, Depends(get_list_local_users_use_case)],
):
    return [_to_managed_user_response(user) for user in use_case.execute()]


@router.put(
    "/users/{user_id}/password",
    response_model=ManagedUserResponse,
    dependencies=[Depends(require_bootstrap_token)],
)
def change_local_user_password(
    user_id: UUID,
    request: ChangePasswordRequest,
    use_case: Annotated[
        ChangeLocalUserPasswordUseCase, Depends(get_change_local_user_password_use_case)
    ],
):
    try:
        return _to_managed_user_response(
            use_case.execute(user_id=user_id, password=request.password)
        )
    except LocalUserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post("/login", response_model=LoginResponse)
def login(
    request: LoginRequest,
    use_case: Annotated[
        AuthenticateLocalUserUseCase, Depends(get_authenticate_local_user_use_case)
    ],
):
    try:
        authenticated = use_case.execute(
            email=str(request.email), password=request.password
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return LoginResponse(
        **_to_user_response(authenticated.user).model_dump(),
        access_token=authenticated.access_token,
        expires_in=authenticated.expires_in,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    claims: Annotated[dict, Depends(get_token_claims)],
    _: Annotated[LocalUser, Depends(get_current_user)],
    use_case: Annotated[
        LogoutLocalUserUseCase, Depends(get_logout_local_user_use_case)
    ],
):
    """End the caller's session: its access token is rejected from now on,
    even though it has not reached its exp yet."""
    use_case.execute(
        token_id=claims.get("jti"),
        expires_at=datetime.fromtimestamp(int(claims["exp"]), UTC),
    )
    response.delete_cookie(_OIDC_SESSION_COOKIE, path="/api/v0")


@router.get("/me", response_model=UserResponse)
def me(user: Annotated[LocalUser, Depends(get_current_user)]):
    return _to_user_response(user)
