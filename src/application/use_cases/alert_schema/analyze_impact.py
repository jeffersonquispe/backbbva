from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from src.application.dtos.alert_schema_dtos import AlertSchemaComparison
from src.application.ports.configuration_port import ConfigurationRepository
from src.application.ports.model_port import ModelRepository


def _contains(value: Any, names: set[str]) -> bool:
    if isinstance(value, str):
        return value in names or any(
            part in names for part in value.replace("$.", "").split(".")
        )
    if isinstance(value, dict):
        return any(
            _contains(key, names) or _contains(item, names)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set)):
        return any(_contains(item, names) for item in value)
    if is_dataclass(value) and not isinstance(value, type):
        return _contains(asdict(value), names)
    if isinstance(value, Enum):
        return _contains(value.value, names)
    return False


class AlertSchemaImpactAnalyzer:
    def __init__(
        self, configurations: ConfigurationRepository, models: ModelRepository
    ) -> None:
        self._configurations, self._models = configurations, models

    def __call__(self, comparison: AlertSchemaComparison) -> list[dict[str, object]]:
        names = {item["field"] for item in comparison.added + comparison.removed}
        names.update(item["field_id"] for item in comparison.changed)
        names.update(item["field"] for item in comparison.changed)
        names.update(
            item["before"] for item in comparison.role_reassignments if item["before"]
        )
        names.update(
            item["after"] for item in comparison.role_reassignments if item["after"]
        )
        result: list[dict[str, object]] = []
        configuration = self._configurations.get_active()
        if configuration is not None and _contains(configuration, names):
            result.append(
                {
                    "kind": "configuration",
                    "id": configuration.configuration_id,
                    "version": configuration.version,
                }
            )
        model = self._models.get_active()
        if model is not None and _contains(model, names):
            result.append(
                {"kind": "xgboost_model", "id": str(model.id), "tag": model.tag}
            )
        return result
