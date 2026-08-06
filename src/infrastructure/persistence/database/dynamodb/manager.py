from botocore.exceptions import ClientError

from src.infrastructure.persistence.database.dynamodb.client import get_dynamodb_resource
from src.infrastructure.persistence.database.dynamodb.schemas import (
    ALERTS_TABLE,
    ASYNC_OPERATIONS_TABLE,
    AUDIT_LOG_TABLE,
    WORKFLOW_EXECUTIONS_TABLE,
    WORKFLOW_STEP_EXECUTIONS_TABLE,
)


def create_table(schema: dict) -> None:
    """Create a DynamoDB table from a boto3-style schema. Idempotent if table already exists."""
    dynamodb = get_dynamodb_resource()
    table_name = schema["TableName"]
    try:
        dynamodb.create_table(**schema)
        table = dynamodb.Table(table_name)
        table.wait_until_exists()
        print(f"Tabla creada: {table_name}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print(f"Tabla ya existe: {table_name}")
        else:
            raise


def ensure_all_tables() -> None:
    """Ensure all DynamoDB tables used by the application exist."""
    create_table(AUDIT_LOG_TABLE)
    create_table(ASYNC_OPERATIONS_TABLE)
    create_table(ALERTS_TABLE)
    create_table(WORKFLOW_EXECUTIONS_TABLE)
    create_table(WORKFLOW_STEP_EXECUTIONS_TABLE)


def drop_table(table_name: str) -> None:
    """Elimina una tabla DynamoDB. Idempotente si no existe."""
    dynamodb = get_dynamodb_resource()
    try:
        table = dynamodb.Table(table_name)
        table.delete()
        table.wait_until_not_exists()
        print(f"Tabla eliminada: {table_name}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            print(f"Tabla no existía: {table_name}")
        else:
            raise


def recreate_table(schema: dict) -> None:
    """Elimina y recrea una tabla con el esquema actualizado. Pierde todos los datos."""
    drop_table(schema["TableName"])
    create_table(schema)


if __name__ == "__main__":
    ensure_all_tables()
