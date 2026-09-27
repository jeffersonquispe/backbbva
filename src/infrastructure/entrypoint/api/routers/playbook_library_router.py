from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.ports.fraud_playbook_port import FraudPlaybookRecord
from src.infrastructure.entrypoint.api.authorization import require_library_access
from src.infrastructure.entrypoint.api.schemas import (
    FraudPlaybookSchema,
    UpsertFraudPlaybookRequest,
)
from src.infrastructure.persistence.database.dynamodb.repositories.fraud_playbook_repository import (
    DynamoFraudPlaybookRepository,
)

router = APIRouter(
    prefix="/library/playbooks",
    tags=["knowledge-library"],
    dependencies=[Depends(require_library_access)],
)


def get_playbook_repository() -> DynamoFraudPlaybookRepository:
    return DynamoFraudPlaybookRepository()


@router.get("", response_model=list[FraudPlaybookSchema])
def list_playbooks(
    repository: Annotated[DynamoFraudPlaybookRepository, Depends(get_playbook_repository)],
):
    return [_to_schema(playbook) for playbook in repository.list()]


@router.put("/{classification}", response_model=FraudPlaybookSchema)
def upsert_playbook(
    classification: str,
    request: UpsertFraudPlaybookRequest,
    repository: Annotated[DynamoFraudPlaybookRepository, Depends(get_playbook_repository)],
):
    existing = repository.update(
        classification, title=request.title, steps=request.steps
    )
    if existing is not None:
        return _to_schema(existing)
    now = datetime.now(timezone.utc)
    return _to_schema(repository.create(FraudPlaybookRecord(
        classification=classification,
        title=request.title,
        steps=request.steps,
        created_at=now,
        updated_at=now,
    )))


@router.get("/{classification}", response_model=FraudPlaybookSchema)
def get_playbook(
    classification: str,
    repository: Annotated[DynamoFraudPlaybookRepository, Depends(get_playbook_repository)],
):
    playbook = repository.get(classification)
    if playbook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playbook not found")
    return _to_schema(playbook)


def _to_schema(playbook: FraudPlaybookRecord) -> FraudPlaybookSchema:
    return FraudPlaybookSchema(**playbook.__dict__)
