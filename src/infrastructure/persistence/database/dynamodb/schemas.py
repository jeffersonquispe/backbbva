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

AGENT_AUDIT_EVENTS_TABLE = {
    "TableName": "agent_audit_events",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "session_id", "KeyType": "HASH"},
        {"AttributeName": "event_key", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "session_id", "AttributeType": "S"},
        {"AttributeName": "event_key", "AttributeType": "S"},
    ],
}


# Local identities. A user deliberately carries exactly one role; permissions
# are derived from that enum in application code and are never data-managed.
USERS_TABLE = {
    "TableName": "users",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [{"AttributeName": "user_id", "KeyType": "HASH"}],
    "AttributeDefinitions": [
        {"AttributeName": "user_id", "AttributeType": "S"},
        {"AttributeName": "email", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "EmailIdx",
            "KeySchema": [{"AttributeName": "email", "KeyType": "HASH"}],
            "Projection": {"ProjectionType": "ALL"},
        }
    ],
}


BACKUPS_TABLE = {
    "TableName": "backups",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [{"AttributeName": "backup_id", "KeyType": "HASH"}],
    "AttributeDefinitions": [{"AttributeName": "backup_id", "AttributeType": "S"}],
}


# Access tokens ended by POST /auth/logout before their exp, keyed by the
# token's jti. expires_at (epoch seconds) is the TTL attribute - see
# manager.ensure_all_tables.
REVOKED_TOKENS_TABLE = {
    "TableName": "revoked_tokens",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [{"AttributeName": "jti", "KeyType": "HASH"}],
    "AttributeDefinitions": [{"AttributeName": "jti", "AttributeType": "S"}],
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
        {"AttributeName": "created_day", "AttributeType": "S"},
        {"AttributeName": "created_at", "AttributeType": "S"},
        {"AttributeName": "status", "AttributeType": "S"},
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
        # Alerts by calendar day in the operations timezone (Bogota) -
        # reconciliation, backfill and the fraud history page read a day
        # without a Scan. Added to pre-existing tables by
        # manager.ensure_global_secondary_indexes; alerts written before
        # created_day existed are absent from it until backfilled (R6).
        {
            "IndexName": "CreatedDayIdx",
            "KeySchema": [
                {"AttributeName": "created_day", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        },
        # Alerts by current status (R9): the live funnel counts and the
        # analyst queue list read one status instead of paging through
        # every alert. KEYS_ONLY keeps a COUNT over 10k in-flight alerts at
        # ~1.5 MB (two pages); list_by_status fetches the items by key.
        {
            "IndexName": "StatusIdx",
            "KeySchema": [
                {"AttributeName": "status", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "KEYS_ONLY"},
        },
    ],
}


# Additive metrics rollups (see application/ports/metrics_rollup_port.py and
# docs/OBSERVABILITY_STRATEGY.md "Fase C"). pk "<data_type>#<level>#<period>"
# (e.g. "alert#day#2026-10-01"), sk = the dimension combination serialized in
# a fixed order. Measures are flat top-level numbers "<measure>__h<HH>" (one
# per hour of day) because DynamoDB's ADD only works on top-level
# attributes. Day rows carry expires_at (TTL, 90 days); month/year don't.
METRICS_ROLLUPS_TABLE = {
    "TableName": "metrics_rollups",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "pk", "KeyType": "HASH"},
        {"AttributeName": "sk", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "pk", "AttributeType": "S"},
        {"AttributeName": "sk", "AttributeType": "S"},
    ],
}


# Append-only audit of fraud-team reviews of an alert's fraud_label (C5,
# application/ports/fraud_label_review_port.py): who, when, from -> to,
# note, channel (ui | csv). One partition per alert, sorted by review time;
# rows are only ever put (conditioned on not existing), never updated.
FRAUD_LABEL_REVIEWS_TABLE = {
    "TableName": "fraud_label_reviews",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "alert_id", "KeyType": "HASH"},
        {"AttributeName": "review_key", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "alert_id", "AttributeType": "S"},
        {"AttributeName": "review_key", "AttributeType": "S"},
    ],
}


# One LLM-judge verdict per alert (D6, EvaluateAlertReasoning). Counts go to
# metrics_rollups (data_type "evaluation"); this table keeps the verdict and
# its rationale for audit.
ALERT_REASONING_EVALUATIONS_TABLE = {
    "TableName": "alert_reasoning_evaluations",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [{"AttributeName": "alert_id", "KeyType": "HASH"}],
    "AttributeDefinitions": [{"AttributeName": "alert_id", "AttributeType": "S"}],
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


# Historical export mappings: each save is retained for the schema version it
# was made for; curation itself reads the alert canonical shape directly.
ALERT_FIELD_MAPPINGS_TABLE = {
    "TableName": "alert_field_mappings",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "dataset_name", "KeyType": "HASH"},
        {"AttributeName": "saved_at", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "dataset_name", "AttributeType": "S"},
        {"AttributeName": "saved_at", "AttributeType": "S"},
    ],
}


# An analyst's structured feedback about a configuration version, captured
# from the "Al dataset" alert-curation action - owned by the configuration
# it's about, not by whichever dataset the alert also got curated into (see
# feedback_port.py). Flat CRUD repo (own id), list() filters/scans by
# configuration_id/version rather than a GSI - low write volume expected.
FEEDBACK_TABLE = {
    "TableName": "feedback",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "id", "KeyType": "HASH"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "id", "AttributeType": "S"},
    ],
}


# Static channel snapshot - today only its `bidi` entry is read (analyst and
# voicebot availability are computed live from OperationalSettings minus
# active reservations, see LiveOperationsCapacity).
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


# Admin-configured operational levers (agent/analyst/voicebot on-off,
# voicebot slots, analyst staffing matrix, queue handling, test-platform
# limits) - see operational_settings_port.py.
OPERATIONAL_SETTINGS_TABLE = {
    "TableName": "operational_settings",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "record_id", "KeyType": "HASH"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "record_id", "AttributeType": "S"},
    ],
}

# Currently-claimed resource locks (voicebot slots, analyst reservations) -
# see resource_reservation_repository.py. pk resource, sk lock name
# ("slot#0003", "alert#<id>", "holder#<user>").
RESOURCE_LOCKS_TABLE = {
    "TableName": "resource_locks",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "resource", "KeyType": "HASH"},
        {"AttributeName": "lock", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "resource", "AttributeType": "S"},
        {"AttributeName": "lock", "AttributeType": "S"},
    ],
}

# Every reservation ever made (active, released, expired) - audit trail.
RESOURCE_RESERVATIONS_TABLE = {
    "TableName": "resource_reservations",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "id", "KeyType": "HASH"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "id", "AttributeType": "S"},
    ],
}

# Append-only change log for OPERATIONAL_SETTINGS_TABLE - one row per
# update() call, sorted by changed_at so list_changes() can Query with
# ScanIndexForward=False instead of a scan+sort.
OPERATIONAL_SETTINGS_HISTORY_TABLE = {
    "TableName": "operational_settings_history",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "record_id", "KeyType": "HASH"},
        {"AttributeName": "changed_at", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "record_id", "AttributeType": "S"},
        {"AttributeName": "changed_at", "AttributeType": "S"},
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

CONFIGURATION_DEPLOY_REQUESTS_TABLE = {
    "TableName": "configuration_deploy_requests",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
    "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
}

ALERT_SCHEMA_VERSIONS_TABLE = {
    "TableName": "alert_schema_versions",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [{"AttributeName": "version", "KeyType": "HASH"}],
    "AttributeDefinitions": [{"AttributeName": "version", "AttributeType": "N"}],
}

ALERT_SCHEMA_SUGGESTIONS_TABLE = {
    "TableName": "alert_schema_suggestions",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
    "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
}

ALERT_SCHEMA_PRESENCE_REPORTS_TABLE = {
    "TableName": "alert_schema_presence_reports",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [{"AttributeName": "report_day", "KeyType": "HASH"}],
    "AttributeDefinitions": [{"AttributeName": "report_day", "AttributeType": "S"}],
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
    # own identity. ProfilingStrategy has no id of its own and is naturally
    # keyed by a fixed business field instead - its `key` enum
    # (usuario/transaccion/transaccional) - so it passes range_attribute
    # explicitly.
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

CONFIGURATION_EVALUATION_TABLE = {
    "TableName": "configuration_evaluation",
    "BillingMode": "PAY_PER_REQUEST",
    **_OWNER_1_1_KEY_SCHEMA,
}

# --- config-wide entity lists (FK = config_key = configuration_id#version) -

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

LIBRARY_MODUS_OPERANDI_REVISIONS_TABLE = {
    "TableName": "library_modus_operandi_revisions",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "entry_id", "KeyType": "HASH"},
        {"AttributeName": "revision_sha256", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "entry_id", "AttributeType": "S"},
        {"AttributeName": "revision_sha256", "AttributeType": "S"},
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


# Immutable vector-store manifests. The second table is deliberately a
# relation table: one instance/version may contain every individual library
# asset, and stores the exact asset revision and embedding selected.
VECTOR_STORE_INSTANCES_TABLE = {
    "TableName": "vector_store_instances",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
    "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
}

VECTOR_STORE_INSTANCE_ASSETS_TABLE = {
    "TableName": "vector_store_instance_assets",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "vector_store_instance_id", "KeyType": "HASH"},
        {"AttributeName": "relation_id", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "vector_store_instance_id", "AttributeType": "S"},
        {"AttributeName": "relation_id", "AttributeType": "S"},
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


# Agent orchestration backbone. All records contain only safe metadata and
# references; per-case dataset rows and raw model errors are never persisted.
AGENT_SESSIONS_TABLE = {
    "TableName": "agent_sessions",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [{"AttributeName": "session_id", "KeyType": "HASH"}],
    "AttributeDefinitions": [
        {"AttributeName": "session_id", "AttributeType": "S"},
        {"AttributeName": "owner_id", "AttributeType": "S"},
        {"AttributeName": "created_at", "AttributeType": "S"},
        {"AttributeName": "status", "AttributeType": "S"},
        {"AttributeName": "updated_at", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "OwnerIdx",
            "KeySchema": [
                {"AttributeName": "owner_id", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        },
        {
            "IndexName": "StatusIdx",
            "KeySchema": [
                {"AttributeName": "status", "KeyType": "HASH"},
                {"AttributeName": "updated_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        },
    ],
}
AGENT_ITERATIONS_TABLE = {
    "TableName": "agent_iterations",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "session_id", "KeyType": "HASH"},
        {"AttributeName": "number", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "session_id", "AttributeType": "S"},
        {"AttributeName": "number", "AttributeType": "N"},
    ],
}
AGENT_RETROSPECTIVE_VALIDATIONS_TABLE = {
    "TableName": "agent_retrospective_validations",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [{"AttributeName": "validation_id", "KeyType": "HASH"}],
    "AttributeDefinitions": [
        {"AttributeName": "validation_id", "AttributeType": "S"}
    ],
}
AGENT_RELEASE_OBSERVATIONS_TABLE = {
    "TableName": "agent_release_observations",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "release_id", "KeyType": "HASH"},
        {"AttributeName": "observation_id", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "release_id", "AttributeType": "S"},
        {"AttributeName": "observation_id", "AttributeType": "S"},
    ],
}
AGENT_RELEASE_ACTIVE_TABLE = {
    "TableName": "agent_release_active",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [{"AttributeName": "slot", "KeyType": "HASH"}],
    "AttributeDefinitions": [{"AttributeName": "slot", "AttributeType": "S"}],
}
AGENT_RELEASES_TABLE = {
    "TableName": "agent_releases",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [{"AttributeName": "release_id", "KeyType": "HASH"}],
    "AttributeDefinitions": [
        {"AttributeName": "release_id", "AttributeType": "S"},
        {"AttributeName": "status", "AttributeType": "S"},
        {"AttributeName": "requested_at", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "StatusRequestedIdx",
            "KeySchema": [
                {"AttributeName": "status", "KeyType": "HASH"},
                {"AttributeName": "requested_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }
    ],
}
AGENT_RUNS_TABLE = {
    "TableName": "agent_runs",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [{"AttributeName": "run_id", "KeyType": "HASH"}],
    "AttributeDefinitions": [
        {"AttributeName": "run_id", "AttributeType": "S"},
        {"AttributeName": "status", "AttributeType": "S"},
        {"AttributeName": "lease_expires_at", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "StatusLeaseIdx",
            "KeySchema": [
                {"AttributeName": "status", "KeyType": "HASH"},
                {"AttributeName": "lease_expires_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }
    ],
}
AGENT_TOOL_CALLS_TABLE = {
    "TableName": "agent_tool_calls",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "run_id", "KeyType": "HASH"},
        {"AttributeName": "call_id", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "run_id", "AttributeType": "S"},
        {"AttributeName": "call_id", "AttributeType": "S"},
    ],
}
AGENT_BUDGET_LEDGER_TABLE = {
    "TableName": "agent_budget_ledger",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "session_id", "KeyType": "HASH"},
        {"AttributeName": "entry_id", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "session_id", "AttributeType": "S"},
        {"AttributeName": "entry_id", "AttributeType": "S"},
    ],
}
AGENT_VERIFICATIONS_TABLE = {
    "TableName": "agent_verifications",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "subject_id", "KeyType": "HASH"},
        {"AttributeName": "verification_id", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "subject_id", "AttributeType": "S"},
        {"AttributeName": "verification_id", "AttributeType": "S"},
    ],
}
AGENT_OBJECTIVES_TABLE = {
    "TableName": "agent_objectives",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "objective_id", "KeyType": "HASH"},
        {"AttributeName": "version", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "objective_id", "AttributeType": "S"},
        {"AttributeName": "version", "AttributeType": "N"},
    ],
}
AGENT_OBJECTIVE_ACTIVE_TABLE = {
    "TableName": "agent_objective_active",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [{"AttributeName": "objective_id", "KeyType": "HASH"}],
    "AttributeDefinitions": [{"AttributeName": "objective_id", "AttributeType": "S"}],
}
AGENT_PACKAGES_TABLE = {
    "TableName": "agent_packages",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [{"AttributeName": "package_id", "KeyType": "HASH"}],
    "AttributeDefinitions": [
        {"AttributeName": "package_id", "AttributeType": "S"},
        {"AttributeName": "session_id", "AttributeType": "S"},
        {"AttributeName": "created_at", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "SessionIdx",
            "KeySchema": [
                {"AttributeName": "session_id", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }
    ],
}
AGENT_CONFIRMATIONS_TABLE = {
    "TableName": "agent_confirmations",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "session_id", "KeyType": "HASH"},
        {"AttributeName": "confirmation_id", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "session_id", "AttributeType": "S"},
        {"AttributeName": "confirmation_id", "AttributeType": "S"},
    ],
}
AGENT_PROMPTS_TABLE = {
    "TableName": "agent_prompts",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "prompt_name", "KeyType": "HASH"},
        {"AttributeName": "version", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "prompt_name", "AttributeType": "S"},
        {"AttributeName": "version", "AttributeType": "N"},
    ],
}
AGENT_PROMPT_ACTIVE_TABLE = {
    "TableName": "agent_prompt_active",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [{"AttributeName": "prompt_name", "KeyType": "HASH"}],
    "AttributeDefinitions": [
        {"AttributeName": "prompt_name", "AttributeType": "S"},
    ],
}

# H4 chat data. User-visible content is already irreversibly masked; only
# message metadata and safe text are persisted. The key is client message id
# for conditional idempotency, with SessionSeqIdx for after_seq reads.
AGENT_MESSAGES_TABLE = {
    "TableName": "agent_messages",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "session_id", "KeyType": "HASH"},
        {"AttributeName": "client_message_id", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "session_id", "AttributeType": "S"},
        {"AttributeName": "client_message_id", "AttributeType": "S"},
        {"AttributeName": "seq", "AttributeType": "N"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "SessionSeqIdx",
            "KeySchema": [
                {"AttributeName": "session_id", "KeyType": "HASH"},
                {"AttributeName": "seq", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        },
    ],
}
AGENT_INSIGHTS_TABLE = {
    "TableName": "agent_insights",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "session_id", "KeyType": "HASH"},
        {"AttributeName": "insight_id", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "session_id", "AttributeType": "S"},
        {"AttributeName": "insight_id", "AttributeType": "S"},
        {"AttributeName": "scope_key", "AttributeType": "S"},
        {"AttributeName": "status", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "ScopeStatusIdx",
            "KeySchema": [
                {"AttributeName": "scope_key", "KeyType": "HASH"},
                {"AttributeName": "status", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        },
    ],
}
AGENT_LINKS_TABLE = {
    "TableName": "agent_links",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "session_id", "KeyType": "HASH"},
        {"AttributeName": "link_key", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "session_id", "AttributeType": "S"},
        {"AttributeName": "link_key", "AttributeType": "S"},
        {"AttributeName": "dst_key", "AttributeType": "S"},
        {"AttributeName": "src_key", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "DstIdx",
            "KeySchema": [
                {"AttributeName": "dst_key", "KeyType": "HASH"},
                {"AttributeName": "src_key", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        },
    ],
}
AGENT_SESSION_SUMMARIES_TABLE = {
    "TableName": "agent_session_summaries",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "session_id", "KeyType": "HASH"},
        {"AttributeName": "version", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "session_id", "AttributeType": "S"},
        {"AttributeName": "version", "AttributeType": "N"},
    ],
}

FEATURE_TEMPLATES_TABLE = {
    "TableName": "feature_templates",
    "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
    "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
    "BillingMode": "PAY_PER_REQUEST",
}

# Assistant and optimizer runtime configuration. The two tables are managed
# by ensure_all_tables() for local and OKD DynamoDB Local deployments.
ASSISTANT_OPTIMIZER_SETTINGS_TABLE = {
    "TableName": "assistant_optimizer_settings",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [{"AttributeName": "record_id", "KeyType": "HASH"}],
    "AttributeDefinitions": [{"AttributeName": "record_id", "AttributeType": "S"}],
}

ASSISTANT_OPTIMIZER_SETTINGS_CHANGES_TABLE = {
    "TableName": "assistant_optimizer_settings_changes",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "record_id", "KeyType": "HASH"},
        {"AttributeName": "changed_at", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "record_id", "AttributeType": "S"},
        {"AttributeName": "changed_at", "AttributeType": "S"},
    ],
}

# Immutable manifests for mature data samples and the idempotency/cooldown
# cursor used by the sampler scheduler (H6 / Fase S).
DATASET_SNAPSHOTS_TABLE = {
    "TableName": "dataset_snapshots",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "snapshot_id", "KeyType": "HASH"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "snapshot_id", "AttributeType": "S"},
        {"AttributeName": "snapshot_group", "AttributeType": "S"},
        {"AttributeName": "created_at", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "CreatedAtIdx",
            "KeySchema": [
                {"AttributeName": "snapshot_group", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }
    ],
}

DATASET_SAMPLER_STATE_TABLE = {
    "TableName": "dataset_sampler_state",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "state_id", "KeyType": "HASH"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "state_id", "AttributeType": "S"},
    ],
}

# H9 persisted hypotheses and their safe, aggregate evidence references.

AGENT_ENTITY_CLAIMS_TABLE = {
    "TableName": "agent_entity_claims",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "entity_key", "KeyType": "HASH"},
        {"AttributeName": "session_id", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "entity_key", "AttributeType": "S"},
        {"AttributeName": "session_id", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "SessionIdx",
            "KeySchema": [{"AttributeName": "session_id", "KeyType": "HASH"}],
            "Projection": {"ProjectionType": "ALL"},
        },
    ],
}


AGENT_EVENTS_TABLE = {
    "TableName": "agent_events",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "session_id", "KeyType": "HASH"},
        {"AttributeName": "seq", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "session_id", "AttributeType": "S"},
        {"AttributeName": "seq", "AttributeType": "N"},
    ],
}
OPTIMIZER_INSIGHTS_TABLE = {
    "TableName": "optimizer_insights",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [{"AttributeName": "insight_id", "KeyType": "HASH"}],
    "AttributeDefinitions": [
        {"AttributeName": "insight_id", "AttributeType": "S"},
        {"AttributeName": "scope_key", "AttributeType": "S"},
        {"AttributeName": "status", "AttributeType": "S"},
        {"AttributeName": "review_after", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "ScopeStatusIdx",
            "KeySchema": [
                {"AttributeName": "scope_key", "KeyType": "HASH"},
                {"AttributeName": "status", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        },
        {
            "IndexName": "StatusReviewIdx",
            "KeySchema": [
                {"AttributeName": "status", "KeyType": "HASH"},
                {"AttributeName": "review_after", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        },
    ],
}

# One partition per optimizer run: `RUN`, `CAND#<hypothesis>`, `EXP#<experiment>`
# and `FIND#<finding>` items. Hypotheses, experiments and findings live here.
OPTIMIZATION_RUNS_TABLE = {
    "TableName": "optimization_runs",
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": "run_id", "KeyType": "HASH"},
        {"AttributeName": "node", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "run_id", "AttributeType": "S"},
        {"AttributeName": "node", "AttributeType": "S"},
    ],
}
