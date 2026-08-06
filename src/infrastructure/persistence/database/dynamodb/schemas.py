AUDIT_LOG_TABLE = {
    "TableName": "audit_log",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "partition", "KeyType": "HASH"},
        {"AttributeName": "log_id", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "partition", "AttributeType": "S"},
        {"AttributeName": "log_id", "AttributeType": "S"},
        {"AttributeName": "tipo", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "TipoIdx",
            "KeySchema": [
                {"AttributeName": "tipo", "KeyType": "HASH"},
                {"AttributeName": "log_id", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        },
    ],
}


ASYNC_OPERATIONS_TABLE = {
    "TableName": "async_operations",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "partition", "KeyType": "HASH"},
        {"AttributeName": "operation_id", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "partition", "AttributeType": "S"},
        {"AttributeName": "operation_id", "AttributeType": "S"},
        {"AttributeName": "status", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "StatusIdx",
            "KeySchema": [
                {"AttributeName": "status", "KeyType": "HASH"},
                {"AttributeName": "operation_id", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        },
    ],
}
