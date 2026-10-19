from __future__ import annotations

from src.application.ports.e2e_state_cleaner_port import (
    E2EStateCleaner,
    E2EStateCleanResult,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.schemas import (
    ASSISTANT_OPTIMIZER_SETTINGS_CHANGES_TABLE,
    ASSISTANT_OPTIMIZER_SETTINGS_TABLE,
    DATASET_SAMPLER_STATE_TABLE,
    DATASET_SNAPSHOTS_TABLE,
    USERS_TABLE,
)

USERS_TABLE_NAME = USERS_TABLE["TableName"]


class DynamoE2EStateCleaner(E2EStateCleaner):
    """Empties every DynamoDB table except users (a full scan is acceptable:
    local E2E data only, gated by the entrypoint)."""

    def clean(self) -> E2EStateCleanResult:
        resource = get_dynamodb_resource()
        client = resource.meta.client
        table_names = [
            table_name
            for page in client.get_paginator("list_tables").paginate()
            for table_name in page.get("TableNames", [])
        ]
        settings_tables = [
            name
            for name in table_names
            if name
            in ASSISTANT_OPTIMIZER_SETTINGS_TABLE_NAMES | MATURE_SAMPLER_TABLE_NAMES
        ]
        other_tables = [
            name
            for name in table_names
            if name != USERS_TABLE_NAME
            and name
            not in ASSISTANT_OPTIMIZER_SETTINGS_TABLE_NAMES
            | MATURE_SAMPLER_TABLE_NAMES
        ]
        deleted = 0
        for table_name in (*settings_tables, *other_tables):
            table = resource.Table(table_name)
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

        return E2EStateCleanResult(
            deleted_items=deleted,
            preserved_tables=[USERS_TABLE_NAME],
            table_count=len(table_names),
        )


# H2 tables are explicitly scheduled for cleanup before the remaining tables.
ASSISTANT_OPTIMIZER_SETTINGS_TABLE_NAMES = frozenset(
    {
        ASSISTANT_OPTIMIZER_SETTINGS_TABLE["TableName"],
        ASSISTANT_OPTIMIZER_SETTINGS_CHANGES_TABLE["TableName"],
    }
)

# H6 sampler tables are cleaned alongside the settings state in real E2E runs.
MATURE_SAMPLER_TABLE_NAMES = frozenset(
    {
        DATASET_SNAPSHOTS_TABLE["TableName"],
        DATASET_SAMPLER_STATE_TABLE["TableName"],
    }
)
