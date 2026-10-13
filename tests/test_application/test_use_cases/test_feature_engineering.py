from copy import deepcopy

import pytest

from src.application.dtos.model_dtos import CreateModelInput
from src.application.use_cases.models.create_model import CreateModelUseCase
from src.application.use_cases.models.feature_engineering import (
    FeatureTemplatesUseCase,
    PreviewFeaturesUseCase,
)


def configuration():
    return {"schema_version": 1, "mappings": {}, "recipes": [{"id": "amount", "name": "amount_numeric", "source": "current", "path": "transaction.amount", "output_type": "number", "steps": []}]}


class InMemoryTemplates:
    def __init__(self):
        self.items = {}

    def create(self, item):
        self.items[item.id] = deepcopy(item)
        return deepcopy(item)

    def list(self):
        return deepcopy(list(self.items.values()))

    def delete(self, identifier):
        self.items.pop(identifier, None)


class InMemoryModels:
    def create(self, model):
        self.saved = model
        return model


def test_template_lifecycle_is_independent_of_input_mutations():
    repository = InMemoryTemplates()
    use_case = FeatureTemplatesUseCase(repository)
    config = configuration()
    saved = use_case.create("  Amount recipe  ", "Reusable", config)
    config["recipes"][0]["path"] = "label"
    assert saved.name == "Amount recipe"
    assert use_case.list()[0].configuration["recipes"][0]["path"] == "transaction.amount"
    use_case.delete(saved.id)
    assert use_case.list() == []


def test_preview_has_values_and_enforces_sample_limits():
    use_case = PreviewFeaturesUseCase()
    result = use_case.execute(configuration(), [{"transaction": {"amount": "12.5"}}])
    assert result["rows"][0]["values"] == {"amount_numeric": 12.5}
    for rows in ([], [{}] * 101, [{"payload": "x" * 2_000_001}]):
        with pytest.raises(ValueError):
            use_case.execute(configuration(), rows)


def test_model_definition_is_a_snapshot_and_rejects_target_paths():
    repository = InMemoryModels()
    use_case = CreateModelUseCase(repository)
    config = configuration()
    arguments = dict(tag="v1", description="", dataset_name="sample", target_field="label", positive_labels=["risk"])
    output = use_case.execute(CreateModelInput(**arguments, feature_configuration=config))
    config["recipes"][0]["path"] = "label"
    output.feature_configuration["recipes"][0]["name"] = "changed"
    assert repository.saved.feature_configuration["recipes"][0]["path"] == "transaction.amount"
    assert repository.saved.feature_configuration["recipes"][0]["name"] == "amount_numeric"
    with pytest.raises(ValueError):
        use_case.execute(CreateModelInput(**arguments, feature_configuration=config))
