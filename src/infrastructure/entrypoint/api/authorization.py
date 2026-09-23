from typing import Annotated

from fastapi import Depends, HTTPException

from src.application.ports.local_auth_port import LocalRole, LocalUser
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
