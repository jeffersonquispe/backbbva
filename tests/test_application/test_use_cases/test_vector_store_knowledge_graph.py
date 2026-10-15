from dataclasses import dataclass

from src.application.ports.vector_store_instance_port import (
    KnowledgeAssetType,
    VectorStoreInstanceAsset,
)
from src.application.use_cases.vector_store_instances.knowledge_graph import (
    KnowledgeGraphService,
)
from src.domain.configurations.entities import (
    FlagType,
)


@dataclass
class Taxonomy:
    id: str
    embedding: list[float] | None = None


@dataclass
class MO:
    id: str
    taxonomy_library_id: str
    embedding: list[float] | None = None


@dataclass
class Case:
    id: str
    modus_operandi_library_id: str
    embedding: list[float] | None = None


@dataclass
class Flag:
    id: str
    flag_type: FlagType
    modus_operandi_library_ids: list[str]
    embedding: list[float] | None = None


class Catalog:
    def __init__(self, values):
        self.values = values

    def get(self, key):
        return next((value for value in self.values if value.id == key), None)

    def list(self):
        return self.values


class Relations:
    def __init__(self):
        self.assets = []
        self.instances = [type("I", (), {"id": "instance-1"})()]

    def list_assets(self, instance_id):
        return [
            asset
            for asset in self.assets
            if asset.vector_store_instance_id == instance_id
        ]

    def add_asset(self, asset):
        self.assets.append(asset)
        return asset

    def remove_asset(self, instance_id, relation_id):
        self.assets = [
            asset
            for asset in self.assets
            if not (
                asset.vector_store_instance_id == instance_id
                and asset.relation_id == relation_id
            )
        ]

    def list(self):
        return self.instances


def test_taxonomy_expansion_adds_modus_cases_and_both_flag_types() -> None:
    relations = Relations()
    graph = KnowledgeGraphService(
        instances=relations,
        taxonomies=Catalog([Taxonomy("tax-1")]),
        modus_operandi=Catalog([MO("mo-1", "tax-1")]),
        similar_cases=Catalog([Case("case-1", "mo-1")]),
        flags=Catalog(
            [
                Flag("yellow-1", FlagType.YELLOW, ["mo-1"]),
                Flag("red-1", FlagType.RED, ["mo-1"]),
            ]
        ),
    )

    created = graph.attach("instance-1", KnowledgeAssetType.TAXONOMY, "tax-1")

    assert {(item.asset_type, item.asset_id) for item in created} == {
        (KnowledgeAssetType.TAXONOMY, "tax-1"),
        (KnowledgeAssetType.MODUS_OPERANDI, "mo-1"),
        (KnowledgeAssetType.SIMILAR_CASE, "case-1"),
        (KnowledgeAssetType.YELLOW_FLAG, "yellow-1"),
        (KnowledgeAssetType.RED_FLAG, "red-1"),
    }
    assert graph.preview_add("instance-1", KnowledgeAssetType.TAXONOMY, "tax-1") == []


def test_attaching_modus_operandi_directly_also_pulls_in_its_taxonomy() -> None:
    # A modus operandi belongs to exactly one taxonomy, and promotion hard-
    # requires that parent to already be indexed - attaching the MO alone
    # (not via its taxonomy) must still bring the taxonomy in.
    relations = Relations()
    graph = KnowledgeGraphService(
        instances=relations,
        taxonomies=Catalog([Taxonomy("tax-1")]),
        modus_operandi=Catalog([MO("mo-1", "tax-1")]),
        similar_cases=Catalog([]),
        flags=Catalog([]),
    )

    created = graph.attach("instance-1", KnowledgeAssetType.MODUS_OPERANDI, "mo-1")

    assert {(item.asset_type, item.asset_id) for item in created} == {
        (KnowledgeAssetType.TAXONOMY, "tax-1"),
        (KnowledgeAssetType.MODUS_OPERANDI, "mo-1"),
    }


def test_new_taxonomy_is_propagated_to_every_managed_instance() -> None:
    relations = Relations()
    relations.instances.append(type("I", (), {"id": "instance-2"})())
    graph = KnowledgeGraphService(
        instances=relations,
        taxonomies=Catalog([Taxonomy("tax-1")]),
        modus_operandi=Catalog([]),
        flags=Catalog([]),
        similar_cases=Catalog([]),
    )

    assert graph.synchronize_new_asset(KnowledgeAssetType.TAXONOMY, "tax-1") == [
        "instance-1",
        "instance-2",
    ]
    assert {item.vector_store_instance_id for item in relations.assets} == {
        "instance-1",
        "instance-2",
    }


def test_new_flag_propagates_only_to_instances_following_its_modus_operandi() -> None:
    relations = Relations()
    relations.instances.append(type("I", (), {"id": "instance-2"})())
    relations.add_asset(
        VectorStoreInstanceAsset(
            "instance-1", KnowledgeAssetType.MODUS_OPERANDI, "mo-1", 1
        )
    )
    relations.add_asset(
        VectorStoreInstanceAsset(
            "instance-2",
            KnowledgeAssetType.MODUS_OPERANDI,
            "mo-1",
            1,
            follow_source_updates=False,
        )
    )
    graph = KnowledgeGraphService(
        instances=relations,
        taxonomies=Catalog([]),
        modus_operandi=Catalog([MO("mo-1", "tax-1")]),
        similar_cases=Catalog([]),
        flags=Catalog([Flag("yellow-1", FlagType.YELLOW, ["mo-1"])]),
    )

    assert graph.synchronize_new_asset(KnowledgeAssetType.YELLOW_FLAG, "yellow-1") == [
        "instance-1"
    ]
    assert {
        (item.vector_store_instance_id, item.asset_id) for item in relations.assets
    } == {
        ("instance-1", "mo-1"),
        ("instance-2", "mo-1"),
        ("instance-1", "yellow-1"),
    }


def test_retiring_taxonomy_removes_its_entire_relation_tree_from_every_instance() -> (
    None
):
    relations = Relations()
    graph = KnowledgeGraphService(
        instances=relations,
        taxonomies=Catalog([Taxonomy("tax-1")]),
        modus_operandi=Catalog([MO("mo-1", "tax-1")]),
        similar_cases=Catalog([Case("case-1", "mo-1")]),
        flags=Catalog([Flag("yellow-1", FlagType.YELLOW, ["mo-1"])]),
    )
    graph.attach("instance-1", KnowledgeAssetType.TAXONOMY, "tax-1")

    assert graph.detach_tree_from_all_instances(
        KnowledgeAssetType.TAXONOMY, "tax-1"
    ) == ["instance-1"]
    assert relations.assets == []


def test_retiring_taxonomy_keeps_flag_shared_with_a_surviving_taxonomy() -> None:
    relations = Relations()
    graph = KnowledgeGraphService(
        instances=relations,
        taxonomies=Catalog([Taxonomy("tax-1"), Taxonomy("tax-2")]),
        modus_operandi=Catalog([MO("mo-1", "tax-1"), MO("mo-2", "tax-2")]),
        similar_cases=Catalog([]),
        flags=Catalog([Flag("red-1", FlagType.RED, ["mo-1", "mo-2"])]),
    )
    graph.attach("instance-1", KnowledgeAssetType.TAXONOMY, "tax-1")
    graph.attach("instance-1", KnowledgeAssetType.TAXONOMY, "tax-2")

    graph.detach_tree_from_all_instances(KnowledgeAssetType.TAXONOMY, "tax-1")

    assert {
        (item.asset_type, item.asset_id) for item in relations.list_assets("instance-1")
    } == {
        (KnowledgeAssetType.TAXONOMY, "tax-2"),
        (KnowledgeAssetType.MODUS_OPERANDI, "mo-2"),
        (KnowledgeAssetType.RED_FLAG, "red-1"),
    }
