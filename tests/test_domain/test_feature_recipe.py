from copy import deepcopy

import pytest

from src.domain.models.feature_recipe import (
    FeatureRecipeValidationError,
    describe_capabilities,
    describe_operations,
    evaluate_feature_definition,
    validate_feature_definition,
)


def definition(steps=None, **recipe):
    return {
        "schema_version": 1,
        "mappings": {
            "reference_time": "transaction.time",
            "history": "history",
            "history_time": "time",
            "entity": "transaction.customer",
            "history_entity": "customer",
            "timezone": "UTC",
        },
        "recipes": [
            {
                "id": "f1",
                "name": "feature",
                "source": "history",
                "window_seconds": 86400,
                "steps": steps or [{"id": "count", "operation": "count"}],
                **recipe,
            }
        ],
    }


def row():
    return {
        "transaction": {
            "time": "2026-01-02T00:00:00Z",
            "customer": "a",
            "amount": 60,
            "destination": "bank",
        },
        "history": [
            {
                "time": "2026-01-01T00:00:00Z",
                "customer": "a",
                "amount": 10,
                "destination": "bank",
            },
            {
                "time": "2026-01-01T23:00:00Z",
                "customer": "a",
                "amount": 30,
                "destination": "bank",
            },
            {"time": "2026-01-02T00:00:00Z", "customer": "a", "amount": 99},
            {"time": "2026-01-03T00:00:00Z", "customer": "a", "amount": 99},
            {"time": "2025-12-31T23:59:59Z", "customer": "a", "amount": 99},
            {"time": "2026-01-01T12:00:00Z", "customer": "b", "amount": 99},
            {"time": "bad timestamp", "customer": "a", "amount": 99},
        ],
    }


def test_history_cutoff_window_entity_and_bad_dates_have_explanations():
    result = evaluate_feature_definition(definition(), row())
    assert result["values"] == {"feature": 2}
    assert result["features"][0]["history"]["included"] == [0, 1]
    assert [x["reason"] for x in result["features"][0]["history"]["excluded"]] == [
        "at_or_after_reference",
        "at_or_after_reference",
        "outside_window",
        "different_entity",
        "Invalid ISO timestamp",
    ]


def test_chained_history_filter_mean_ratio_category():
    config = definition(
        [
            {
                "id": "filter",
                "operation": "filter",
                "conditions": [
                    {
                        "path": "destination",
                        "operator": "eq",
                        "current_path": "transaction.destination",
                    }
                ],
            },
            {"id": "mean", "operation": "mean", "path": "amount"},
            {"id": "ratio", "operation": "ratio", "current_path": "transaction.amount"},
            {
                "id": "category",
                "operation": "categorize",
                "rules": [{"max": 3, "value": "normal"}, {"min": 3, "value": "high"}],
            },
        ],
        output_type="string",
    )
    result = evaluate_feature_definition(config, row())
    assert result["values"]["feature"] == "high"
    assert [x["value"] for x in result["features"][0]["trace"]][2:] == [20, 3, "high"]


def test_trace_starts_with_the_raw_input_value():
    config = definition(
        [{"id": "numeric", "operation": "number"}],
        source="current",
        path="transaction.amount",
    )
    trace = evaluate_feature_definition(config, row())["features"][0]["trace"]
    assert (trace[0]["step_id"], trace[0]["operation"], trace[0]["value"]) == (
        "_input",
        "input",
        60,
    )
    assert (trace[1]["step_id"], trace[1]["value"]) == ("numeric", 60.0)


@pytest.mark.parametrize(
    "policy,expected,status",
    [("missing", None, "missing"), ("constant", 7, "ok"), ("error", None, "error")],
)
def test_division_zero_missing_policy(policy, expected, status):
    config = definition(
        [{"id": "divide", "operation": "divide", "value": 0}],
        source="current",
        path="transaction.amount",
        missing={"policy": policy, "value": 7},
    )
    feature = evaluate_feature_definition(config, row())["features"][0]
    assert (feature["value"], feature["status"], feature["error"]) == (
        expected,
        status,
        "Division by zero",
    )


@pytest.mark.parametrize("value", [True, "", "NaN", "Infinity", None, {}, []])
def test_invalid_numeric_inputs_are_never_coerced_to_zero(value):
    data = row()
    data["transaction"]["amount"] = value
    config = definition(
        [{"id": "numeric", "operation": "number"}],
        source="current",
        path="transaction.amount",
    )
    assert (
        evaluate_feature_definition(config, data)["features"][0]["status"] == "missing"
    )


@pytest.mark.parametrize(
    "op,expected",
    [
        ("count", 0),
        ("sum", 0),
        ("mean", None),
        ("min", None),
        ("max", None),
        ("median", None),
        ("recency", None),
    ],
)
def test_empty_history_semantics(op, expected):
    data = row()
    data["history"] = []
    assert (
        evaluate_feature_definition(
            definition([{"id": "aggregate", "operation": op, "path": "amount"}]), data
        )["values"]["feature"]
        == expected
    )


def test_overlap_duplicate_names_and_target_leakage_rejected():
    config = definition(
        [
            {
                "id": "category",
                "operation": "categorize",
                "rules": [
                    {"min": 0, "max": 10, "value": "a"},
                    {"min": 5, "max": 15, "value": "b"},
                ],
            }
        ],
        source="current",
        path="transaction.amount",
    )
    with pytest.raises(FeatureRecipeValidationError, match="Overlapping"):
        validate_feature_definition(config)
    config = definition()
    config["recipes"].append(deepcopy(config["recipes"][0]))
    with pytest.raises(FeatureRecipeValidationError, match="Duplicate"):
        validate_feature_definition(config)
    config = definition(
        [{"id": "select", "operation": "select", "path": "label"}],
        source="current",
        path="transaction",
    )
    with pytest.raises(FeatureRecipeValidationError, match="Target leakage"):
        validate_feature_definition(config, forbidden_paths=["transaction.label"])


def test_timezone_hour_and_ambiguous_naive_date():
    config = definition(
        [{"id": "hour", "operation": "hour"}], source="current", path="transaction.time"
    )
    config["mappings"]["timezone"] = "America/Bogota"
    assert evaluate_feature_definition(config, row())["values"]["feature"] == 19
    config["mappings"]["timezone"] = "America/New_York"
    data = row()
    data["transaction"]["time"] = "2026-11-01T01:30:00"
    assert (
        "Ambiguous" in evaluate_feature_definition(config, data)["features"][0]["error"]
    )


def test_no_input_mutation_and_disabled_features_omitted():
    config, data = definition(), row()
    before = deepcopy((config, data))
    evaluate_feature_definition(config, data)
    assert (config, data) == before
    config["recipes"][0]["enabled"] = False
    assert evaluate_feature_definition(config, data)["values"] == {}


def test_missing_history_is_distinct_from_empty_history():
    data = row()
    del data["history"]
    assert evaluate_feature_definition(definition(), data)["values"]["feature"] is None


def test_recency_uses_latest_matching_event():
    assert (
        evaluate_feature_definition(
            definition([{"id": "recency", "operation": "recency"}]), row()
        )["values"]["feature"]
        == 3600
    )


def test_disabled_steps_do_not_execute_or_contribute_target_paths():
    config = definition(
        [
            {"id": "number", "operation": "number"},
            {
                "id": "divide",
                "operation": "divide",
                "current_path": "target",
                "enabled": False,
            },
        ],
        source="current",
        path="transaction.amount",
    )
    validate_feature_definition(config, forbidden_paths=["target"])
    assert evaluate_feature_definition(config, row())["values"]["feature"] == 60


def test_disabled_steps_allow_incomplete_operation_configuration():
    config = definition(
        [
            {"id": "number", "operation": "number"},
            {"id": "select-draft", "operation": "select", "path": "", "enabled": False},
        ],
        source="current",
        path="transaction.amount",
    )
    validate_feature_definition(config)
    assert evaluate_feature_definition(config, row())["values"]["feature"] == 60


def test_nested_select_leakage_checks_allow_sibling_field():
    config = definition(
        [
            {"id": "select", "operation": "select", "path": "amount"},
            {"id": "number", "operation": "number"},
        ],
        source="current",
        path="transaction",
    )
    validate_feature_definition(config, forbidden_paths=["transaction.label"])
    with pytest.raises(FeatureRecipeValidationError, match="Target leakage"):
        validate_feature_definition(config, forbidden_paths=["transaction.amount"])


def test_json_encoded_csv_columns_and_history_entries():
    import json

    data = row()
    data["transaction"] = json.dumps(data["transaction"])
    data["history"] = json.dumps([json.dumps(item) for item in data["history"]])
    assert evaluate_feature_definition(definition(), data)["values"]["feature"] == 2
    config = definition(
        [{"id": "number", "operation": "number"}],
        source="current",
        path="transaction.amount",
    )
    assert evaluate_feature_definition(config, data)["values"]["feature"] == 60


@pytest.mark.parametrize(
    "path,select", [("$", "$.label"), ("$", "label"), ("", "$.label")]
)
def test_root_path_alias_cannot_bypass_target_check(path, select):
    config = definition(
        [{"id": "select", "operation": "select", "path": select}],
        source="current",
        path=path,
    )
    with pytest.raises(FeatureRecipeValidationError, match="Target leakage"):
        validate_feature_definition(config, forbidden_paths=["label"])


def test_history_mapping_and_date_reference_cannot_alias_target():
    config = definition()
    config["mappings"]["history"] = "label"
    with pytest.raises(FeatureRecipeValidationError, match="Target leakage"):
        validate_feature_definition(config, forbidden_paths=["label"])
    config = definition(
        [{"id": "elapsed", "operation": "elapsed_seconds"}],
        source="current",
        path="event",
    )
    config["mappings"]["reference_time"] = "label"
    with pytest.raises(FeatureRecipeValidationError, match="Target leakage"):
        validate_feature_definition(config, forbidden_paths=["label"])


def test_scalar_to_array_chain_rejected_before_execution():
    with pytest.raises(FeatureRecipeValidationError, match="expects an array"):
        validate_feature_definition(
            definition(
                [
                    {"id": "count", "operation": "count"},
                    {"id": "sum", "operation": "sum"},
                ]
            )
        )


def test_resource_bounds_and_trace_truncation():
    data = row()
    data["history"] = [data["history"][0]] * 101
    config = definition(
        [
            {
                "id": "filter",
                "operation": "filter",
                "conditions": [{"path": "customer", "operator": "eq", "value": "a"}],
            },
            {"id": "count", "operation": "count"},
        ]
    )
    result = evaluate_feature_definition(config, data)
    trace = result["features"][0]["trace"][0]
    assert (
        trace["truncated"] is True
        and trace["total_items"] == 101
        and len(trace["value"]) == 100
    )
    data["history"] *= 100
    assert "10000" in evaluate_feature_definition(config, data)["features"][0]["error"]


def test_invalid_operand_and_boundary_flags_rejected():
    with pytest.raises(FeatureRecipeValidationError, match="numeric operand"):
        validate_feature_definition(
            definition(
                [{"id": "add", "operation": "add", "value": {}}],
                source="current",
                path="amount",
            )
        )
    with pytest.raises(FeatureRecipeValidationError, match="boundary flags"):
        validate_feature_definition(
            definition(
                [
                    {
                        "id": "category",
                        "operation": "categorize",
                        "rules": [
                            {"min": 0, "max": 1, "include_min": "yes", "value": "a"}
                        ],
                    }
                ],
                source="current",
                path="amount",
            )
        )


def explicit_definition(steps=None):
    return {
        "schema_version": 2,
        "mappings": {"history": "history", "timezone": "UTC"},
        "recipes": [
            {
                "id": "f",
                "name": "total",
                "source": "history",
                "steps": steps
                or [
                    {"id": "count", "operation": "count"},
                ],
            }
        ],
    }


def test_explicit_history_has_no_implicit_time_window_or_entity_filter():
    result = evaluate_feature_definition(explicit_definition(), row())
    assert result["values"]["total"] == 7
    assert result["features"][0]["history"]["included"] == list(range(7))


def test_explicit_datetime_window_identity_and_serialized_history():
    import json

    config = explicit_definition(
        [
            {
                "id": "before",
                "operation": "filter",
                "conditions": [
                    {
                        "path": "time",
                        "operator": "lt",
                        "value_type": "datetime",
                        "current_path": "transaction.time",
                    },
                    {
                        "path": "time",
                        "operator": "gte",
                        "value_type": "datetime",
                        "current_path": "transaction.time",
                        "offset_seconds": -86400,
                    },
                    {
                        "path": "customer",
                        "operator": "eq",
                        "current_path": "transaction.customer",
                    },
                ],
            },
            {"id": "sum", "operation": "sum", "path": "amount"},
        ]
    )
    data = row()
    data["history"] = json.dumps([json.dumps(event) for event in data["history"][:-1]])
    result = evaluate_feature_definition(config, data)
    assert result["values"]["total"] == 40
    assert result["features"][0]["history"]["included"] == [0, 1]
    assert result["features"][0]["history"]["excluded"] == [
        {"index": index, "reason": "filter:before"} for index in [2, 3, 4, 5]
    ]


@pytest.mark.parametrize(
    "operator,expected",
    [("eq", 1), ("ne", 0), ("lt", 0), ("lte", 1), ("gt", 0), ("gte", 1)],
)
def test_datetime_comparison_uses_instants_and_configured_timezone(operator, expected):
    config = explicit_definition(
        [
            {
                "id": "date",
                "operation": "filter",
                "conditions": [
                    {
                        "path": "time",
                        "operator": operator,
                        "value_type": "datetime",
                        "value": "2026-05-09T22:20:09Z",
                    },
                ],
            },
            {"id": "count", "operation": "count"},
        ]
    )
    config["mappings"]["timezone"] = "America/Bogota"
    assert (
        evaluate_feature_definition(
            config, {"history": [{"time": "2026-05-09 17:20:09"}]}
        )["values"]["total"]
        == expected
    )


def test_explicit_invalid_date_reports_error_instead_of_lexical_comparison():
    config = explicit_definition(
        [
            {
                "id": "date",
                "operation": "filter",
                "conditions": [
                    {
                        "path": "time",
                        "operator": "lt",
                        "value_type": "datetime",
                        "value": "2026-05-09T00:00:00Z",
                    },
                ],
            },
            {"id": "count", "operation": "count"},
        ]
    )
    result = evaluate_feature_definition(config, {"history": [{"time": "invalid"}]})[
        "features"
    ][0]
    assert result["status"] == "missing"
    assert result["error"] == "Invalid ISO timestamp"


def test_explicit_recency_and_elapsed_reference_paths():
    config = explicit_definition(
        [
            {
                "id": "recent",
                "operation": "recency",
                "path": "time",
                "current_path": "transaction.time",
            }
        ]
    )
    data = row()
    data["history"] = data["history"][:2]
    assert evaluate_feature_definition(config, data)["values"]["total"] == 3600
    config["recipes"][0].update(
        source="current",
        path="transaction.time",
        steps=[
            {"id": "elapsed", "operation": "elapsed_seconds", "current_path": "later"},
        ],
    )
    data["later"] = "2026-01-02T01:00:00Z"
    assert evaluate_feature_definition(config, data)["values"]["total"] == 3600


@pytest.mark.parametrize(
    "condition",
    [
        {"value_type": "datetime", "offset_seconds": True},
        {"value_type": "datetime", "offset_seconds": 1e20},
        {"offset_seconds": 10},
        {"value_type": "datetime", "operator": "contains"},
        {"value_type": "unknown"},
    ],
)
def test_invalid_datetime_conditions_rejected(condition):
    config = explicit_definition(
        [
            {
                "id": "date",
                "operation": "filter",
                "conditions": [
                    {
                        "path": "time",
                        "operator": "lt",
                        "value": "2026-05-09",
                        **condition,
                    },
                ],
            }
        ]
    )
    with pytest.raises(FeatureRecipeValidationError):
        validate_feature_definition(config)


def test_explicit_version_rejects_hidden_filters_and_requires_references():
    config = explicit_definition()
    config["recipes"][0]["window_seconds"] = 60
    with pytest.raises(FeatureRecipeValidationError, match="explicit datetime filter"):
        validate_feature_definition(config)
    config = explicit_definition()
    config["mappings"]["entity"] = "customer"
    with pytest.raises(FeatureRecipeValidationError, match="Unknown mapping"):
        validate_feature_definition(config)
    config = explicit_definition(
        [{"id": "recent", "operation": "recency", "path": "time"}]
    )
    with pytest.raises(FeatureRecipeValidationError, match="current_path"):
        validate_feature_definition(config)


def test_explicit_filter_current_reference_is_checked_for_target_leakage():
    config = explicit_definition(
        [
            {
                "id": "date",
                "operation": "filter",
                "conditions": [
                    {
                        "path": "time",
                        "operator": "lt",
                        "value_type": "datetime",
                        "current_path": "target",
                    },
                ],
            },
            {"id": "count", "operation": "count"},
        ]
    )
    with pytest.raises(FeatureRecipeValidationError, match="Target leakage"):
        validate_feature_definition(config, ["target"])


def test_explicit_sequential_filters_track_original_indices_and_disabled_steps():
    config = explicit_definition(
        [
            {
                "id": "account",
                "operation": "filter",
                "conditions": [{"path": "customer", "operator": "eq", "value": "a"}],
            },
            {
                "id": "disabled",
                "operation": "filter",
                "enabled": False,
                "conditions": [{"path": "amount", "operator": "gt", "value": 1000}],
            },
            {
                "id": "amount",
                "operation": "filter",
                "conditions": [{"path": "amount", "operator": "gte", "value": 30}],
            },
            {"id": "count", "operation": "count"},
        ]
    )
    feature = evaluate_feature_definition(config, row())["features"][0]
    assert feature["value"] == 5
    assert feature["history"]["included"] == [1, 2, 3, 4, 6]
    assert feature["history"]["excluded"] == [
        {"index": 5, "reason": "filter:account"},
        {"index": 0, "reason": "filter:amount"},
    ]


def test_to_array_splits_plain_delimited_text_and_passes_through_json_arrays():
    data = row()
    data["transaction"]["reasons"] = "FRAUD, DUPLICATE, FRAUD"
    config = definition(
        [
            {"id": "split", "operation": "to_array"},
            {"id": "count", "operation": "count"},
        ],
        source="current",
        path="transaction.reasons",
    )
    assert evaluate_feature_definition(config, data)["values"]["feature"] == 3
    data["transaction"]["reasons"] = (
        '["A", "B"]'  # already parsed to a list by _json_container - to_array passes it through
    )
    assert evaluate_feature_definition(config, data)["values"]["feature"] == 2


def test_to_array_custom_delimiter():
    data = row()
    data["transaction"]["reasons"] = "A;B;C"
    config = definition(
        [
            {"id": "split", "operation": "to_array", "delimiter": ";"},
            {"id": "count", "operation": "count"},
        ],
        source="current",
        path="transaction.reasons",
    )
    assert evaluate_feature_definition(config, data)["values"]["feature"] == 3


def test_filter_accepts_primitive_array_members_without_a_path():
    data = row()
    data["transaction"]["reasons"] = '["FRAUD", "DUPLICATE", "FRAUD"]'
    config = definition(
        [
            {
                "id": "only-fraud",
                "operation": "filter",
                "conditions": [{"operator": "eq", "value": "FRAUD"}],
            },
            {"id": "count", "operation": "count"},
        ],
        source="current",
        path="transaction.reasons",
    )
    assert evaluate_feature_definition(config, data)["values"]["feature"] == 2


def test_to_array_normalizes_bracketed_primitive_text_before_filtering():
    data = row()
    data["transaction"]["reasons"] = "[FRAUD, DUPLICATE, FRAUD]"
    config = definition(
        [
            {"id": "split", "operation": "to_array"},
            {
                "id": "only-fraud",
                "operation": "filter",
                "conditions": [{"operator": "eq", "value": "FRAUD"}],
            },
            {"id": "count", "operation": "count"},
        ],
        source="current",
        path="transaction.reasons",
    )
    assert evaluate_feature_definition(config, data)["values"]["feature"] == 2


def test_fill_missing_accepts_an_empty_primitive_list_before_to_array():
    config = definition(
        [
            {"id": "fill", "operation": "fill_missing", "value": []},
            {"id": "split", "operation": "to_array"},
            {"id": "count", "operation": "count"},
        ],
        source="current",
        path="transaction.reasons",
    )
    assert evaluate_feature_definition(config, row())["values"]["feature"] == 0


def test_to_array_rejects_raw_array_input_and_empty_delimiter():
    with pytest.raises(FeatureRecipeValidationError, match="to_array expects a scalar"):
        validate_feature_definition(
            definition([{"id": "split", "operation": "to_array"}])
        )
    with pytest.raises(
        FeatureRecipeValidationError, match="delimiter must be a nonempty string"
    ):
        validate_feature_definition(
            definition(
                [{"id": "split", "operation": "to_array", "delimiter": ""}],
                source="current",
                path="transaction.reasons",
            )
        )


def test_to_boolean_numeric_truthiness():
    config = definition(
        [
            {"id": "count", "operation": "count"},
            {"id": "flag", "operation": "to_boolean"},
        ],
        output_type="boolean",
    )
    assert evaluate_feature_definition(config, row())["values"]["feature"] is True
    data = row()
    data["history"] = []
    assert evaluate_feature_definition(config, data)["values"]["feature"] is False


def test_to_boolean_truthy_values_matches_string_scalars():
    config = definition(
        [{"id": "flag", "operation": "to_boolean", "truthy_values": ["bank"]}],
        source="current",
        path="transaction.destination",
        output_type="boolean",
    )
    assert evaluate_feature_definition(config, row())["values"]["feature"] is True
    data = row()
    data["transaction"]["destination"] = "other"
    assert evaluate_feature_definition(config, data)["values"]["feature"] is False


def test_to_boolean_rejects_raw_array_input_and_invalid_truthy_values():
    with pytest.raises(
        FeatureRecipeValidationError, match="to_boolean expects a scalar"
    ):
        validate_feature_definition(
            definition([{"id": "flag", "operation": "to_boolean"}])
        )
    with pytest.raises(
        FeatureRecipeValidationError, match="truthy_values must contain"
    ):
        validate_feature_definition(
            definition(
                [{"id": "flag", "operation": "to_boolean", "truthy_values": []}],
                source="current",
                path="transaction.destination",
            )
        )
    with pytest.raises(
        FeatureRecipeValidationError, match="truthy_values must be scalars"
    ):
        validate_feature_definition(
            definition(
                [{"id": "flag", "operation": "to_boolean", "truthy_values": [{}]}],
                source="current",
                path="transaction.destination",
            )
        )


def test_describe_capabilities_lists_every_operation_with_valid_type_metadata():
    capabilities = describe_capabilities()
    assert capabilities["output_types"] == ["number", "string", "boolean"]
    operations = {op["id"]: op for op in capabilities["operations"]}
    assert operations == {op["id"]: op for op in describe_operations()}
    assert {
        "to_array",
        "to_boolean",
        "filter",
        "select",
        "categorize",
        "count",
    } <= operations.keys()
    assert operations["to_array"] == {
        "id": "to_array",
        "consumes": "scalar",
        "produces": "array",
        "skips_on_missing_input": True,
    }
    assert operations["to_boolean"] == {
        "id": "to_boolean",
        "consumes": "scalar",
        "produces": "unknown",
        "skips_on_missing_input": True,
    }
    assert operations["filter"] == {
        "id": "filter",
        "consumes": "array",
        "produces": "array",
        "skips_on_missing_input": False,
    }
    assert operations["select"] == {
        "id": "select",
        "consumes": "array",
        "produces": "unknown",
        "skips_on_missing_input": False,
    }
    assert operations["fill_missing"]["skips_on_missing_input"] is False
    for op in operations.values():
        assert op["consumes"] in ("array", "scalar")
        assert op["produces"] in ("array", "scalar", "unknown")
        assert isinstance(op["skips_on_missing_input"], bool)


def test_trace_flags_steps_skipped_because_their_input_was_missing():
    config = definition(
        [
            {"id": "to_bool", "operation": "to_boolean"},
        ],
        source="current",
        path="transaction.flag",
        output_type="boolean",
    )
    result = evaluate_feature_definition(config, {"transaction": {}})
    trace = result["features"][0]["trace"]
    assert trace[0]["skipped"] is False  # the synthetic _input entry is never "skipped"
    assert trace[1]["step_id"] == "to_bool" and trace[1]["skipped"] is True


def test_trace_does_not_flag_fill_missing_or_a_step_that_ran_on_a_real_value():
    config = definition(
        [
            {"id": "fill", "operation": "fill_missing", "value": False},
            {"id": "to_bool", "operation": "to_boolean"},
        ],
        source="current",
        path="transaction.flag",
        output_type="boolean",
    )
    missing_row = evaluate_feature_definition(config, {"transaction": {}})
    present_row = evaluate_feature_definition(config, {"transaction": {"flag": 1}})
    for result in (missing_row, present_row):
        trace = result["features"][0]["trace"]
        assert trace[1]["step_id"] == "fill" and trace[1]["skipped"] is False
        assert trace[2]["step_id"] == "to_bool" and trace[2]["skipped"] is False


def test_to_array_and_to_boolean_propagate_missing_value():
    config_array = definition(
        [{"id": "split", "operation": "to_array"}],
        source="current",
        path="transaction.missing_field",
    )
    assert (
        evaluate_feature_definition(config_array, row())["features"][0]["status"]
        == "missing"
    )
    config_bool = definition(
        [{"id": "flag", "operation": "to_boolean"}],
        source="current",
        path="transaction.missing_field",
        output_type="boolean",
    )
    assert (
        evaluate_feature_definition(config_bool, row())["features"][0]["status"]
        == "missing"
    )
