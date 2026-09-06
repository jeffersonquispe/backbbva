from __future__ import annotations

from src.application.use_cases.datasets.field_extraction import (
    ANALYSIS_FIELDS,
    compute_distributions,
    discover_fields,
    extract_fields,
    select_profiling_fields,
    split_list_value,
)


def test_discover_fields_returns_complete_ordered_catalog() -> None:
    rows = [
        {
            "reviewstatus_first": "risk-suspected",
            "channel": "GL",
            "biocatch": {"score": "258", "isRat": "False"},
        },
        {
            "channel": "OM",
            "Model_score": "0.27087",
            "transactionid": "tx-1",
        },
    ]

    assert discover_fields(rows) == [
        "reviewstatus_first",
        "channel",
        "biocatch.score",
        "biocatch.isRat",
        "Model_score",
        "transactionid",
    ]


def test_extract_fields_reads_exact_column_names() -> None:
    row = {
        "razon_marcacion": "[NF___ANLISIS]",
        "marcacion_final": "no-risk",
        "integrationpoint": "00 - Compra",
        "tipo": "NoFraude",
        "triggered_rules": "[CUSTOMER - Score1000Net]",
    }

    assert extract_fields(row) == {
        "razon_marcacion": "[NF___ANLISIS]",
        "marcacion_final": "no-risk",
        "integration_point": "00 - Compra",
        "tipo": "NoFraude",
        "triggered_rules": "[CUSTOMER - Score1000Net]",
    }


def test_extract_fields_prefers_canonical_alias_over_others() -> None:
    row = {"integration_point": "canonical", "integrationPoint": "camel"}

    assert extract_fields(row)["integration_point"] == "canonical"


def test_extract_fields_missing_or_blank_values_are_none() -> None:
    row = {"marcacion_final": "", "tipo": None}

    extracted = extract_fields(row)

    assert extracted["marcacion_final"] is None
    assert extracted["tipo"] is None
    assert extracted["razon_marcacion"] is None
    assert extracted["integration_point"] is None
    assert extracted["triggered_rules"] is None


def test_split_list_value_parses_bracketed_comma_separated_values() -> None:
    assert split_list_value("[FR___ESTAFA, RECLAMO]") == ["FR___ESTAFA", "RECLAMO"]
    assert split_list_value("[CUSTOMER - Score1000Net]") == ["CUSTOMER - Score1000Net"]
    assert split_list_value("[]") == []
    assert split_list_value("") == []
    # Defensive: a value with no brackets (unexpected export shape) is kept
    # as a single item rather than dropped.
    assert split_list_value("RECLAMO") == ["RECLAMO"]


def test_compute_distributions_counts_values_per_field_including_unknown() -> None:
    rows = [
        {"marcacion_final": "no-risk", "tipo": "NoFraude"},
        {"marcacion_final": "no-risk", "tipo": "Fraude"},
        {"marcacion_final": "risk"},
    ]

    distributions = compute_distributions(rows, fields=("marcacion_final", "tipo"))

    assert distributions == {
        "marcacion_final": {"no-risk": 2, "risk": 1},
        "tipo": {"NoFraude": 1, "Fraude": 1, "unknown": 1},
    }


def test_compute_distributions_splits_multi_value_fields_per_member() -> None:
    rows = [
        {"razon_marcacion": "[FR___ESTAFA, RECLAMO]"},
        {"razon_marcacion": "[NF___ANLISIS]"},
        {"razon_marcacion": "[RECLAMO]"},
        {"razon_marcacion": ""},
    ]

    distributions = compute_distributions(rows, fields=("razon_marcacion",))

    # RECLAMO appears in 2 rows even though it never appears alone with
    # FR___ESTAFA and once on its own - each member is counted per row it
    # appears in, not per unique combined string.
    assert distributions["razon_marcacion"] == {
        "FR___ESTAFA": 1,
        "RECLAMO": 2,
        "NF___ANLISIS": 1,
        "unknown": 1,
    }


def test_compute_distributions_defaults_to_all_analysis_fields() -> None:
    distributions = compute_distributions([{"tipo": "Fraude"}])

    assert set(distributions.keys()) == set(ANALYSIS_FIELDS)


def test_extract_fields_supports_arbitrary_non_aria_field() -> None:
    # "canal" is not one of the 5 ANALYSIS_FIELDS/_ALIASES entries - before
    # the fix, extract_fields always extracted exactly the 5 hardcoded keys
    # and this would KeyError instead of resolving via get_nested_value.
    row = {"canal": "APP", "tipo": "Fraude"}

    extracted = extract_fields(row, fields=("canal", "tipo"))

    assert extracted == {"canal": "APP", "tipo": "Fraude"}


def test_extract_fields_arbitrary_field_missing_or_blank_is_none() -> None:
    row = {"canal": ""}

    extracted = extract_fields(row, fields=("canal", "other_missing"))

    assert extracted["canal"] is None
    assert extracted["other_missing"] is None


def test_extract_fields_aria_fields_unaffected_when_mixed_with_custom_field() -> None:
    # The 5 special-cased ARIA fields keep their alias-resolution behavior
    # exactly as before even when passed alongside a non-ARIA field.
    row = {"integrationPoint": "camel", "canal": "WEB"}

    extracted = extract_fields(row, fields=("integration_point", "canal"))

    assert extracted == {"integration_point": "camel", "canal": "WEB"}


def test_compute_distributions_with_non_aria_field_no_longer_raises_keyerror() -> None:
    rows = [
        {"canal": "APP"},
        {"canal": "APP"},
        {"canal": "WEB"},
        {"canal": ""},
    ]

    distributions = compute_distributions(rows, fields=("canal",))

    assert distributions == {"canal": {"APP": 2, "WEB": 1, "unknown": 1}}


def test_compute_distributions_mixes_aria_and_custom_fields() -> None:
    rows = [
        {"tipo": "Fraude", "canal": "APP"},
        {"tipo": "NoFraude", "canal": "APP"},
    ]

    distributions = compute_distributions(rows, fields=("tipo", "canal"))

    assert distributions == {
        "tipo": {"Fraude": 1, "NoFraude": 1},
        "canal": {"APP": 2},
    }


def test_select_profiling_fields_always_includes_aria_fields_even_if_absent() -> None:
    # An empty/extracted-style dataset with none of the 5 ARIA columns -
    # they must still appear in the result for backward-compatible UI
    # labeling, even though they're absent from available_fields.
    rows = [
        {"foo": "a", "bar": "x", "id": "1"},
        {"foo": "a", "bar": "y", "id": "2"},
        {"foo": "b", "bar": "x", "id": "3"},
    ]
    available_fields = ["foo", "bar", "id"]

    selected = select_profiling_fields(rows, available_fields, cardinality_limit=2)

    for field_name in ANALYSIS_FIELDS:
        assert field_name in selected


def test_select_profiling_fields_excludes_high_cardinality_includes_low() -> None:
    rows = [
        {"foo": "a", "bar": "x", "id": "1"},
        {"foo": "a", "bar": "y", "id": "2"},
        {"foo": "b", "bar": "x", "id": "3"},
    ]
    available_fields = ["foo", "bar", "id"]

    # foo has 2 distinct values, bar has 2 distinct values, id has 3 (unique
    # per row) - with a limit of 2, id must be excluded, foo/bar included.
    selected = select_profiling_fields(rows, available_fields, cardinality_limit=2)

    assert "foo" in selected
    assert "bar" in selected
    assert "id" not in selected
    # Order: ANALYSIS_FIELDS first, then the qualifying extras in
    # available_fields order.
    assert selected == tuple(list(ANALYSIS_FIELDS) + ["foo", "bar"])


def test_select_profiling_fields_skips_fields_already_in_analysis_fields() -> None:
    rows = [{"tipo": "Fraude"}]
    available_fields = ["tipo", "canal"]

    selected = select_profiling_fields(rows, available_fields)

    # "tipo" is not duplicated even though it's also in available_fields.
    assert selected.count("tipo") == 1
    assert "canal" in selected
