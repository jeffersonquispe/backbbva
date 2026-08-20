from __future__ import annotations

from src.application.use_cases.datasets.field_extraction import (
    ANALYSIS_FIELDS,
    compute_distributions,
    extract_fields,
    split_list_value,
)


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
