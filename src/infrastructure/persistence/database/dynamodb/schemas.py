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


ALERTS_TABLE = {
    "TableName": "alerts",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "partition", "KeyType": "HASH"},
        {"AttributeName": "alert_id", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "partition", "AttributeType": "S"},
        {"AttributeName": "alert_id", "AttributeType": "S"},
        {"AttributeName": "event_id", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "EventIdIdx",
            "KeySchema": [
                {"AttributeName": "event_id", "KeyType": "HASH"},
                {"AttributeName": "alert_id", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        },
    ],
}


WORKFLOW_EXECUTIONS_TABLE = {
    "TableName": "workflow_executions",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "partition", "KeyType": "HASH"},
        {"AttributeName": "workflow_execution_id", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "partition", "AttributeType": "S"},
        {"AttributeName": "workflow_execution_id", "AttributeType": "S"},
        {"AttributeName": "status", "AttributeType": "S"},
        {"AttributeName": "test_run_id", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "StatusIdx",
            "KeySchema": [
                {"AttributeName": "status", "KeyType": "HASH"},
                {
                    "AttributeName": "workflow_execution_id",
                    "KeyType": "RANGE",
                },
            ],
            "Projection": {"ProjectionType": "ALL"},
        },
        {
            "IndexName": "TestRunIdx",
            "KeySchema": [
                {"AttributeName": "test_run_id", "KeyType": "HASH"},
                {
                    "AttributeName": "workflow_execution_id",
                    "KeyType": "RANGE",
                },
            ],
            "Projection": {"ProjectionType": "ALL"},
        },
    ],
}


WORKFLOW_STEP_EXECUTIONS_TABLE = {
    "TableName": "workflow_step_executions",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "workflow_execution_id", "KeyType": "HASH"},
        {"AttributeName": "step_execution_id", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "workflow_execution_id", "AttributeType": "S"},
        {"AttributeName": "step_execution_id", "AttributeType": "S"},
    ],
}


FRAUD_PLAYBOOKS_TABLE = {
    "TableName": "fraud_playbooks",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "classification", "KeyType": "HASH"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "classification", "AttributeType": "S"},
    ],
}


TEST_RUNS_TABLE = {
    "TableName": "test_runs",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "test_run_id", "KeyType": "HASH"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "test_run_id", "AttributeType": "S"},
    ],
}


MODELS_TABLE = {
    "TableName": "models",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "model_id", "KeyType": "HASH"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "model_id", "AttributeType": "S"},
    ],
}


DATASET_SAMPLES_TABLE = {
    "TableName": "dataset_samples",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "dataset_name", "KeyType": "HASH"},
        {"AttributeName": "sample_id", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "dataset_name", "AttributeType": "S"},
        {"AttributeName": "sample_id", "AttributeType": "S"},
    ],
}


DATASET_SUMMARIES_TABLE = {
    "TableName": "dataset_summaries",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "dataset_name", "KeyType": "HASH"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "dataset_name", "AttributeType": "S"},
    ],
}


OPERATIONS_CAPACITY_TABLE = {
    "TableName": "operations_capacity",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "record_id", "KeyType": "HASH"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "record_id", "AttributeType": "S"},
    ],
}


CONFIGURATIONS_TABLE = {
    "TableName": "configurations",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "configuration_id", "KeyType": "HASH"},
        {"AttributeName": "version", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "configuration_id", "AttributeType": "S"},
        {"AttributeName": "version", "AttributeType": "N"},
    ],
}


# Every table below holds either a 1:1 configuration sub-section (its own
# row per configuration_id+version, exactly like `configurations` itself) or
# a configuration sub-entity that carries its own identity (an `id`, a real
# uuid - see configuration_repository.py's use of uuid.uuid4()) and repeats
# per segment (or per parent record, for a nested list-of-entities). Each
# row is a real, independent DynamoDB item, foreign-keyed back to its owner
# - see configuration_repository.py's _config_key/_group_key/_criterion_key
# for how each FK string is built. configuration_segments is the one place
# a fixed business key (segment_code: "tarjetas"/"canales_digitales") still
# appears, as a plain attribute alongside its own uuid `id` - every other
# per-segment table below is foreign-keyed off that uuid ("segment_id"), not
# off the code. FilterGroup/FilterCondition (a recursive AND/OR tree) and
# SamplingCriterion/DistributionValue (criterion -> its value buckets) need
# a 2-level FK chain on top of that; everything else is a flat one-hop FK.
def _fk_key_schema(hash_attribute: str, range_attribute: str = "id") -> dict:
    # range_attribute defaults to "id" (a real uuid) for entities with their
    # own identity. A couple of entities have no id of their own and are
    # naturally keyed by a fixed business field instead - ProfilingStrategy
    # (by its `key` enum: usuario/transaccion/transaccional) and
    # FieldCategorization (by the `field` name it categorizes) - those pass
    # range_attribute explicitly.
    return {
        "KeySchema": [
            {"AttributeName": hash_attribute, "KeyType": "HASH"},
            {"AttributeName": range_attribute, "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": hash_attribute, "AttributeType": "S"},
            {"AttributeName": range_attribute, "AttributeType": "S"},
        ],
    }


_OWNER_1_1_KEY_SCHEMA = {
    "KeySchema": [
        {"AttributeName": "configuration_id", "KeyType": "HASH"},
        {"AttributeName": "version", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "configuration_id", "AttributeType": "S"},
        {"AttributeName": "version", "AttributeType": "N"},
    ],
}

# --- 1:1 config-wide sections (one row per configuration_id+version) ------

CONFIGURATION_GENERAL_TABLE = {
    "TableName": "configuration_general",
    "BillingMode": "PAY_PER_REQUEST",
    **_OWNER_1_1_KEY_SCHEMA,
}

CONFIGURATION_INFRASTRUCTURE_TABLE = {
    "TableName": "configuration_infrastructure",
    "BillingMode": "PAY_PER_REQUEST",
    **_OWNER_1_1_KEY_SCHEMA,
}

CONFIGURATION_OPERATIONS_TABLE = {
    "TableName": "configuration_operations",
    "BillingMode": "PAY_PER_REQUEST",
    **_OWNER_1_1_KEY_SCHEMA,
}

CONFIGURATION_EVALUATION_TABLE = {
    "TableName": "configuration_evaluation",
    "BillingMode": "PAY_PER_REQUEST",
    **_OWNER_1_1_KEY_SCHEMA,
}

# --- config-wide entity lists (FK = config_key = configuration_id#version) -

CONFIGURATION_ANALYST_PROFILES_TABLE = {
    "TableName": "configuration_analyst_profiles",
    "BillingMode": "PAY_PER_REQUEST",
    **_fk_key_schema("config_key"),
}

# The two segment objects (digital channels / cards) - born together with
# their configuration at create() time, each with its own uuid `id`.
# `segment_code` is a plain attribute here (not part of the key) so the
# fixed SegmentCode label survives, but every other per-segment table below
# references this row's uuid, not its code.
CONFIGURATION_SEGMENTS_TABLE = {
    "TableName": "configuration_segments",
    "BillingMode": "PAY_PER_REQUEST",
    **_fk_key_schema("config_key"),
}

# --- per-segment entity lists (FK = segment_id, configuration_segments.id) -

# Keyed by `key` (the fixed ProfilingStrategyKey enum: usuario/transaccion/
# transaccional), not a uuid - there's no separate identity to invent, and
# the 3-step pipeline order matters (each strategy's output feeds the next),
# which is why configuration_repository.py re-sorts after querying instead
# of trusting DynamoDB's alphabetical RANGE-key order.
CONFIGURATION_PROFILING_STRATEGIES_TABLE = {
    "TableName": "configuration_profiling_strategies",
    "BillingMode": "PAY_PER_REQUEST",
    **_fk_key_schema("segment_id", range_attribute="key"),
}

# Keyed by `field` (the field name it categorizes) - a field is categorized
# at most once per segment, so that's already a natural unique key.
CONFIGURATION_FIELD_CATEGORIZATIONS_TABLE = {
    "TableName": "configuration_field_categorizations",
    "BillingMode": "PAY_PER_REQUEST",
    **_fk_key_schema("segment_id", range_attribute="field"),
}

CONFIGURATION_TAXONOMIES_TABLE = {
    "TableName": "configuration_taxonomies",
    "BillingMode": "PAY_PER_REQUEST",
    **_fk_key_schema("segment_id"),
}

CONFIGURATION_MODUS_OPERANDI_TABLE = {
    "TableName": "configuration_modus_operandi",
    "BillingMode": "PAY_PER_REQUEST",
    **_fk_key_schema("segment_id"),
}

CONFIGURATION_RED_YELLOW_FLAGS_TABLE = {
    "TableName": "configuration_red_yellow_flags",
    "BillingMode": "PAY_PER_REQUEST",
    **_fk_key_schema("segment_id"),
}

CONFIGURATION_EXAMPLES_TABLE = {
    "TableName": "configuration_examples",
    "BillingMode": "PAY_PER_REQUEST",
    **_fk_key_schema("segment_id"),
}

CONFIGURATION_PLAYBOOKS_TABLE = {
    "TableName": "configuration_playbooks",
    "BillingMode": "PAY_PER_REQUEST",
    **_fk_key_schema("segment_id"),
}

CONFIGURATION_VOICEBOT_PROMPTS_TABLE = {
    "TableName": "configuration_voicebot_prompts",
    "BillingMode": "PAY_PER_REQUEST",
    **_fk_key_schema("segment_id"),
}

CONFIGURATION_SAMPLING_CRITERIA_TABLE = {
    "TableName": "configuration_sampling_criteria",
    "BillingMode": "PAY_PER_REQUEST",
    **_fk_key_schema("segment_id"),
}

# FilterGroup is self-referencing (parent_group_id, a plain attribute, not
# part of the key) to model AND/OR nesting under one segment.
CONFIGURATION_FILTER_GROUPS_TABLE = {
    "TableName": "configuration_filter_groups",
    "BillingMode": "PAY_PER_REQUEST",
    **_fk_key_schema("segment_id"),
}

# --- 2-level FK chains (owner entity -> its own child entities) -----------

# FK = group_key = f"{segment_id}#{group_id}" - a condition belongs to one
# specific FilterGroup, not just to the segment.
CONFIGURATION_FILTER_CONDITIONS_TABLE = {
    "TableName": "configuration_filter_conditions",
    "BillingMode": "PAY_PER_REQUEST",
    **_fk_key_schema("group_key"),
}

# FK = criterion_key = f"{segment_id}#{criterion_id}" - a distribution
# value belongs to one specific SamplingCriterion.
CONFIGURATION_SAMPLING_CRITERIA_VALUES_TABLE = {
    "TableName": "configuration_sampling_criteria_values",
    "BillingMode": "PAY_PER_REQUEST",
    **_fk_key_schema("criterion_key"),
}


TAG_CATALOG_TABLE = {
    "TableName": "tag_catalog",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "category", "KeyType": "HASH"},
        {"AttributeName": "tag_id", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "category", "AttributeType": "S"},
        {"AttributeName": "tag_id", "AttributeType": "S"},
    ],
}


MARCACION_CATALOG_TABLE = {
    "TableName": "marcacion_catalog",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "id", "KeyType": "HASH"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "id", "AttributeType": "S"},
    ],
}


LIBRARY_TAXONOMIES_TABLE = {
    "TableName": "library_taxonomies",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "id", "KeyType": "HASH"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "id", "AttributeType": "S"},
    ],
}

LIBRARY_CHANNELS_TABLE = {
    "TableName": "library_channels",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "id", "KeyType": "HASH"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "id", "AttributeType": "S"},
    ],
}


LIBRARY_MODUS_OPERANDI_TABLE = {
    "TableName": "library_modus_operandi",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "id", "KeyType": "HASH"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "id", "AttributeType": "S"},
    ],
}


LIBRARY_FLAGS_TABLE = {
    "TableName": "library_flags",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "id", "KeyType": "HASH"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "id", "AttributeType": "S"},
    ],
}


LIBRARY_SIMILAR_CASES_TABLE = {
    "TableName": "library_similar_cases",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "id", "KeyType": "HASH"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "id", "AttributeType": "S"},
    ],
}


RESOLUTION_METHOD_CATALOG_TABLE = {
    "TableName": "resolution_method_catalog",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "id", "KeyType": "HASH"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "id", "AttributeType": "S"},
    ],
}


VARIABLE_CATALOG_TABLE = {
    "TableName": "variable_catalog",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "id", "KeyType": "HASH"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "id", "AttributeType": "S"},
    ],
}


WATCHLIST_TABLE = {
    "TableName": "watchlists",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "id", "KeyType": "HASH"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "id", "AttributeType": "S"},
    ],
}


# One item per element (watchlist_id, normalized value) instead of a list
# embedded in the watchlist item - a Dynamo item caps at 400KB, which a
# "gigantic" list blows past. This shape gives O(1) GetItem/BatchGetItem
# membership checks and incremental add/remove regardless of list size. See
# watchlist_repository.py.
WATCHLIST_ELEMENTS_TABLE = {
    "TableName": "watchlist_elements",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "watchlist_id", "KeyType": "HASH"},
        {"AttributeName": "value", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "watchlist_id", "AttributeType": "S"},
        {"AttributeName": "value", "AttributeType": "S"},
    ],
}
