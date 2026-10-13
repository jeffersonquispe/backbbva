from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.ports.local_auth_port import LocalUser
from src.infrastructure.core.config import genai_config
from src.infrastructure.entrypoint.api.authorization import require_permission
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.schemas import USERS_TABLE


router = APIRouter(prefix="/e2e", tags=["e2e"])
USERS_TABLE_NAME = USERS_TABLE["TableName"]


@router.post("/clean")
def clean_e2e_state(
    _: Annotated[LocalUser, Depends(require_permission("alert_schema"))],
) -> dict[str, object]:
    """Delete application data for the real E2E suite.

    The destructive operation deliberately lives behind the API so the E2E
    runner never needs DynamoDB credentials or a second network path.
    """
    if genai_config.GENAI_ENVIRONMENT != "local" or not genai_config.E2E_CLEANUP_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="E2E cleanup is not enabled for this API environment",
        )

    client = get_dynamodb_resource().meta.client
    table_names = [
        table_name
        for page in client.get_paginator("list_tables").paginate()
        for table_name in page.get("TableNames", [])
    ]
    deleted = 0
    for table_name in table_names:
        if table_name == USERS_TABLE_NAME:
            continue
        table = get_dynamodb_resource().Table(table_name)
        key_names = [item["AttributeName"] for item in table.key_schema]
        expression_names = {
            f"#key{index}": name for index, name in enumerate(key_names)
        }
        scan_kwargs: dict[str, object] = {
            "ProjectionExpression": ", ".join(expression_names),
            "ExpressionAttributeNames": expression_names,
        }
        while True:
            page = table.scan(**scan_kwargs)
            keys = [
                {name: item[name] for name in key_names}
                for item in page.get("Items", [])
            ]
            if keys:
                with table.batch_writer() as batch:
                    for key in keys:
                        batch.delete_item(Key=key)
                        deleted += 1
            if "LastEvaluatedKey" not in page:
                break
            scan_kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    return {
        "deleted_items": deleted,
        "preserved_tables": [USERS_TABLE_NAME],
        "table_count": len(table_names),
    }
