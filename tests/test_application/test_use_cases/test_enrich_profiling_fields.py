from src.application.use_cases.alerts.enrich_profiling_fields import (
    EnrichProfilingFieldsUseCase,
)


def configuration(**overrides):
    return {
        "schema_version": 2,
        "mappings": {"timezone": "America/Bogota", "history": "history"},
        "recipes": [
            {
                "id": "r1",
                "name": "saldo_enriquecido",
                "enabled": True,
                "output_type": "number",
                "source": "current",
                "path": "saldo",
                "missing": {"policy": "missing"},
                "steps": [],
            }
        ],
        **overrides,
    }


def test_no_recipes_short_circuits_without_validating():
    use_case = EnrichProfilingFieldsUseCase()
    # The default/untouched state for a segment (see configuration_port.py's
    # _default_field_enrichment) - validate_feature_definition itself
    # requires 1-200 recipes, so this must not raise.
    empty = {
        "schema_version": 2,
        "mappings": {"timezone": "America/Bogota"},
        "recipes": [],
    }

    assert use_case.execute(empty, current={}, history=[]) == {}


def test_evaluates_a_current_field_recipe():
    use_case = EnrichProfilingFieldsUseCase()

    result = use_case.execute(configuration(), current={"saldo": 1200.5}, history=[])

    assert result == {"saldo_enriquecido": 1200.5}


def test_evaluates_a_history_aggregation_recipe():
    use_case = EnrichProfilingFieldsUseCase()
    config = configuration(
        recipes=[
            {
                "id": "r1",
                "name": "conteo_historial",
                "enabled": True,
                "output_type": "number",
                "source": "history",
                "missing": {"policy": "missing"},
                "steps": [{"id": "s1", "operation": "count"}],
            }
        ]
    )

    result = use_case.execute(
        config, current={"saldo": 100}, history=[{"amount": 10}, {"amount": 20}]
    )

    assert result == {"conteo_historial": 2}


def test_uses_the_configuration_mappings_history_key_when_set():
    use_case = EnrichProfilingFieldsUseCase()
    config = configuration(
        mappings={"timezone": "America/Bogota", "history": "eventos"},
        recipes=[
            {
                "id": "r1",
                "name": "conteo_historial",
                "enabled": True,
                "output_type": "number",
                "source": "history",
                "missing": {"policy": "missing"},
                "steps": [{"id": "s1", "operation": "count"}],
            }
        ],
    )

    result = use_case.execute(config, current={}, history=[{"amount": 1}])

    assert result == {"conteo_historial": 1}


def test_missing_field_resolves_per_the_recipe_missing_policy():
    use_case = EnrichProfilingFieldsUseCase()
    config = configuration(
        recipes=[
            {
                "id": "r1",
                "name": "saldo_enriquecido",
                "enabled": True,
                "output_type": "number",
                "source": "current",
                "path": "saldo",
                "missing": {"policy": "constant", "value": 0},
                "steps": [],
            }
        ]
    )

    result = use_case.execute(config, current={}, history=[])

    assert result == {"saldo_enriquecido": 0}
