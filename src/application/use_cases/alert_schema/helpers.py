from __future__ import annotations

from dataclasses import asdict

from src.application.dtos.alert_schema_dtos import AlertSchemaComparison
from src.application.ports.alert_schema_port import AlertSchemaVersion


def compare_schema(candidate: AlertSchemaVersion, active: AlertSchemaVersion | None) -> AlertSchemaComparison:
    old = {field.id: field for field in active.fields} if active else {}
    new = {field.id: field for field in candidate.fields}
    added = [asdict(new[key]) for key in sorted(new.keys() - old.keys())]
    removed = [asdict(old[key]) for key in sorted(old.keys() - new.keys())]
    changed = []
    for key in sorted(new.keys() & old.keys()):
        before, after = asdict(old[key]), asdict(new[key])
        attributes = {
            name: {"before": before[name], "after": after[name]}
            for name in before
            if before[name] != after[name]
        }
        if attributes:
            changed.append({"field_id": key, "field": after["field"], "attributes": attributes})
    previous_roles = active.field_roles if active else {}
    roles = [
        {"role": role, "before": previous_roles.get(role), "after": candidate.field_roles.get(role)}
        for role in sorted(set(previous_roles) | set(candidate.field_roles))
        if previous_roles.get(role) != candidate.field_roles.get(role)
    ]
    return AlertSchemaComparison(added, changed, removed, roles)


def field_names(comparison: AlertSchemaComparison) -> set[str]:
    names = {item["field"] for item in comparison.added + comparison.removed}
    names.update(item["field_id"] for item in comparison.changed)
    names.update(item["before"] for item in comparison.role_reassignments if item["before"])
    names.update(item["after"] for item in comparison.role_reassignments if item["after"])
    return names

