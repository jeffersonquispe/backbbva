from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta

from src.application.ports.clock_port import Clock
from src.application.ports.object_storage_port import ObjectStoragePort
from src.application.ports.protected_object_keys_port import (
    ProtectedObjectKeysPort,
)


@dataclass(frozen=True)
class RetentionRule:
    """Delete objects under ``prefix`` in ``store`` older than ``max_age_days``."""

    store: str
    prefix: str
    max_age_days: int

    def __post_init__(self) -> None:
        # An empty prefix would wipe the whole store: refuse it outright.
        if not self.prefix.strip():
            raise ValueError("Retention rule needs a non-empty prefix")
        if self.max_age_days < 1:
            raise ValueError("Retention rule max_age_days must be >= 1")


@dataclass(frozen=True)
class RetentionRuleResult:
    rule: RetentionRule
    matched: int
    deleted: int
    bytes_matched: int
    failed: int = 0
    # Expired objects kept because a legal hold still needs them.
    protected: int = 0


@dataclass(frozen=True)
class ApplyRetentionOutput:
    dry_run: bool
    results: list[RetentionRuleResult]

    @property
    def deleted(self) -> int:
        return sum(r.deleted for r in self.results)


class ApplyObjectStorageRetentionUseCase:
    """Apply age-based retention rules across the configured object stores."""

    def __init__(
        self,
        stores: Mapping[str, ObjectStoragePort],
        clock: Clock,
        protected: ProtectedObjectKeysPort | None = None,
    ) -> None:
        self._stores = stores
        self._clock = clock
        self._protected = protected

    def execute(
        self, rules: Sequence[RetentionRule], dry_run: bool = True
    ) -> ApplyRetentionOutput:
        now = self._clock.now()
        results: list[RetentionRuleResult] = []
        protected = (
            self._protected.protected_object_keys() if self._protected else frozenset()
        )
        for rule in rules:
            store = self._stores.get(rule.store)
            if store is None:
                raise ValueError(
                    f"Unknown object store in retention rule: {rule.store}"
                )
            cutoff = now - timedelta(days=rule.max_age_days)
            old = [
                obj
                for obj in store.list_objects(rule.prefix)
                if obj.last_modified < cutoff
            ]
            expired = [obj for obj in old if obj.key not in protected]
            deleted = failed = 0
            if not dry_run:
                for obj in expired:
                    # One bad object must not stop the rest of the sweep.
                    try:
                        store.delete(obj.key)
                        deleted += 1
                    except Exception:  # noqa: BLE001
                        failed += 1
            results.append(
                RetentionRuleResult(
                    rule=rule,
                    matched=len(expired),
                    deleted=deleted,
                    bytes_matched=sum(obj.size for obj in expired),
                    failed=failed,
                    protected=len(old) - len(expired),
                )
            )
        return ApplyRetentionOutput(dry_run=dry_run, results=results)
