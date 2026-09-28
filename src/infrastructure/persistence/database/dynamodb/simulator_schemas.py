from __future__ import annotations

from botocore.exceptions import ClientError

from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

# Table shared by aria-api (scenario CRUD/lifecycle, see
# entrypoint/api/routers/scenarios_router.py) and the event-simulator's own
# Celery worker (entrypoint/simulator/celery/, reads/writes it directly -
# never imported by aria-worker). Deliberately does not import
# infrastructure/persistence/database/dynamodb/schemas.py or manager.py so
# the standalone simulator-worker project can keep importing this module
# without pulling in aria-api's/aria-worker's full schema surface (see
# backend CLAUDE.md's "Two (really three) separate poetry projects"
# section) - aria-api's own startup calls ensure_simulator_tables() too
# (initialization/tables.py) since it now owns the CRUD side.

EVENT_SIMULATION_SCENARIOS_TABLE = {
    "TableName": "event_simulation_scenarios",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "partition", "KeyType": "HASH"},
        {"AttributeName": "scenario_id", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "partition", "AttributeType": "S"},
        {"AttributeName": "scenario_id", "AttributeType": "S"},
        {"AttributeName": "status", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "StatusIdx",
            "KeySchema": [
                {"AttributeName": "status", "KeyType": "HASH"},
                {"AttributeName": "scenario_id", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        },
    ],
}


def _create_table_if_missing(schema: dict) -> None:
    """Create a DynamoDB table from a boto3-style schema. Idempotent if the
    table already exists - copies create_table()'s error-handling approach
    from persistence/database/dynamodb/manager.py without importing it."""
    dynamodb = get_dynamodb_resource()
    table_name = schema["TableName"]
    try:
        dynamodb.create_table(**schema)
        dynamodb.Table(table_name).wait_until_exists()
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceInUseException":
            raise


def ensure_simulator_tables() -> None:
    """Ensure all DynamoDB tables owned by the event-simulator exist."""
    _create_table_if_missing(EVENT_SIMULATION_SCENARIOS_TABLE)
