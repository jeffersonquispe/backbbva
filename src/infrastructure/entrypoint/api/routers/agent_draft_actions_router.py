from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends

from src.application.ports.local_auth_port import LocalUser
from src.application.use_cases.agent.list_draft_actions import list_agent_draft_actions
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user

router = APIRouter(prefix="/agent", tags=["agent-draft-actions"])


@router.get("/draft-actions")
def get_agent_draft_actions(
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    """List proposal actions allowed for the authenticated user's role."""
    return [asdict(action) for action in list_agent_draft_actions(user.role)]
