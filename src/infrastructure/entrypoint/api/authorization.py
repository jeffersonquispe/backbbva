from typing import Annotated

from fastapi import Depends, HTTPException

from src.application.ports.local_auth_port import ROLE_PERMISSIONS, LocalRole, LocalUser
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user

LIBRARY_WRITER_ROLES = frozenset({
    LocalRole.MANAGER, LocalRole.CHANNEL_MANAGER, LocalRole.DATA_ANALYST,
})


def require_library_access(
    user: Annotated[LocalUser, Depends(get_current_user)],
) -> LocalUser:
    """Single authorization boundary for every knowledge-library mutation.

    This prevents callers from bypassing the UI and mutating the graph through
    an unprotected CRUD endpoint.
    """
    if user.role not in LIBRARY_WRITER_ROLES:
        raise HTTPException(status_code=403, detail="Role is not permitted to manage the knowledge library")
    return user


def require_permission(permission: str):
    """Dependency factory: the caller's role must grant `permission`
    (ROLE_PERMISSIONS - the same list /auth/me returns to the frontend).
    Use as `Depends(require_permission("dashboard"))` at the route."""

    def dependency(user: Annotated[LocalUser, Depends(get_current_user)]) -> LocalUser:
        if permission not in ROLE_PERMISSIONS.get(user.role, frozenset()):
            raise HTTPException(
                status_code=403, detail=f"Role is not granted the '{permission}' permission"
            )
        return user

    return dependency
