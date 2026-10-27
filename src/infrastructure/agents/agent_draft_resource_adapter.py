from __future__ import annotations

import re
from typing import Any

from src.application.dtos.dataset_dtos import CreateEmptyDatasetInput
from src.application.ports.agent_draft_resource_port import AgentDraftResourcePort
from src.application.ports.channel_library_port import ChannelLibraryRepository
from src.application.ports.tag_catalog_port import TagCatalogRepository
from src.application.use_cases.channel_library.create_channel_library_entry import (
    CreateChannelLibraryEntryUseCase,
)
from src.application.use_cases.datasets.create_empty_dataset import (
    CreateEmptyDatasetUseCase,
)
from src.application.use_cases.tag_catalog.create_tag import CreateTagUseCase
from src.application.use_cases.test_runs.list_datasets import ListDatasetsUseCase
from src.domain.configurations.entities import TagCategory


class AgentDraftResourceAdapter(AgentDraftResourcePort):
    """Infrastructure bridge to existing library/catalog/dataset use cases."""

    def __init__(
        self,
        *,
        channels: ChannelLibraryRepository,
        tags: TagCatalogRepository,
        datasets: ListDatasetsUseCase,
        create_channel: CreateChannelLibraryEntryUseCase,
        create_tag: CreateTagUseCase,
        create_dataset: CreateEmptyDatasetUseCase,
    ) -> None:
        self._channels, self._tags, self._datasets = channels, tags, datasets
        self._create_channel, self._create_tag, self._create_dataset = (
            create_channel,
            create_tag,
            create_dataset,
        )

    def context(self, resource: str) -> dict[str, Any]:
        if resource == "channel":
            return {
                "existing_channels": [
                    {"code": row.code, "name": row.name, "description": row.description}
                    for row in self._channels.list()[:50]
                ]
            }
        if resource == "catalog_entry":
            return {
                "categories": [category.value for category in TagCategory],
                "existing_entries": {
                    category.value: [
                        row.value
                        for row in self._tags.list_by_category(
                            category, active_only=True
                        )[:50]
                    ]
                    for category in TagCategory
                },
            }
        if resource == "dataset_empty":
            return {
                "existing_datasets": [
                    row.name for row in self._datasets.execute()[:50]
                ],
                "dataset_kind": "empty dataset metadata only; data upload stays in the dataset UI",
            }
        raise ValueError("unsupported draft resource")

    def verify(
        self, resource: str, draft: dict[str, Any]
    ) -> list[tuple[str, str, str | None]]:
        if resource == "channel":
            code, name, description = (
                draft.get(key) for key in ("code", "name", "description")
            )
            valid = (
                isinstance(code, str)
                and re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", code.strip())
                and isinstance(name, str)
                and 1 <= len(name.strip()) <= 200
                and isinstance(description, str)
                and len(description) <= 1000
            )
            duplicate = bool(
                valid
                and any(
                    row.code.casefold() == code.strip().casefold()
                    for row in self._channels.list()
                )
            )
            return _checks(valid, duplicate)
        if resource == "catalog_entry":
            category_raw, value = draft.get("category"), draft.get("value")
            try:
                category = (
                    TagCategory(category_raw) if isinstance(category_raw, str) else None
                )
            except ValueError:
                category = None
            valid = (
                category is not None
                and isinstance(value, str)
                and 1 <= len(value.strip()) <= 200
            )
            duplicate = bool(
                valid
                and category
                and any(
                    row.value.casefold() == value.strip().casefold()
                    for row in self._tags.list_by_category(category)
                )
            )
            return _checks(valid, duplicate)
        if resource == "dataset_empty":
            name, fields = draft.get("name"), draft.get("fields")
            existing = {row.name.casefold() for row in self._datasets.execute()}
            valid = (
                isinstance(name, str)
                and 1 <= len(name.strip()) <= 184
                and isinstance(fields, list)
                and 1 <= len(fields) <= 100
                and all(
                    isinstance(field, str) and 1 <= len(field.strip()) <= 200
                    for field in fields
                )
                and len(
                    {
                        field.strip().casefold()
                        for field in fields
                        if isinstance(field, str)
                    }
                )
                == len(fields)
            )
            duplicate = bool(
                isinstance(name, str) and name.strip().casefold() in existing
            )
            return _checks(valid, duplicate)
        return [("resource", "FAIL", "UNSUPPORTED_RESOURCE")]

    def create(self, resource: str, draft: dict[str, Any]) -> str:
        checks = self.verify(resource, draft)
        if any(status != "PASS" for _, status, _ in checks):
            raise ValueError("resource draft failed final validation")
        if resource == "channel":
            row = self._create_channel.execute(
                draft["code"].strip(),
                draft["name"].strip(),
                draft["description"].strip(),
            )
            return row.id
        if resource == "catalog_entry":
            row = self._create_tag.execute(
                TagCategory(draft["category"]), draft["value"].strip()
            )
            return row.id
        if resource == "dataset_empty":
            result = self._create_dataset.execute(
                CreateEmptyDatasetInput(
                    name=draft["name"].strip(),
                    fields=[field.strip() for field in draft["fields"]],
                )
            )
            return result.name
        raise ValueError("unsupported draft resource")


def _checks(valid: bool, duplicate: bool) -> list[tuple[str, str, str | None]]:
    return [
        (
            "schema",
            "PASS" if valid else "FAIL",
            None if valid else "DRAFT_SCHEMA_INVALID",
        ),
        (
            "duplicates",
            "FAIL" if duplicate else "PASS",
            "DUPLICATE_RESOURCE" if duplicate else None,
        ),
    ]
