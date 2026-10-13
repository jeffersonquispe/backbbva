"""Knowledge-library dependency expansion and instance synchronization.

This service deliberately operates on relation records only.  It never asks
for an embedding, so adding descendants is safe while an instance is being
prepared in DynamoDB.  Promotion is the only workflow that indexes it.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.application.ports.vector_store_instance_port import (
    KnowledgeAssetType,
    VectorStoreInstanceAsset,
    VectorStoreInstanceRepository,
)


@dataclass(frozen=True)
class KnowledgeGraphImpact:
    asset_type: KnowledgeAssetType
    asset_id: str
    origin: str


class KnowledgeGraphService:
    def __init__(
        self,
        *,
        instances: VectorStoreInstanceRepository,
        taxonomies,
        modus_operandi,
        flags,
        similar_cases,
    ) -> None:
        self._instances = instances
        self._taxonomies = taxonomies
        self._modus_operandi = modus_operandi
        self._flags = flags
        self._similar_cases = similar_cases

    def expansion(
        self, asset_type: KnowledgeAssetType, asset_id: str
    ) -> list[KnowledgeGraphImpact]:
        """Returns the selected asset and all required descendants, de-duped."""
        result: list[KnowledgeGraphImpact] = []
        seen: set[tuple[KnowledgeAssetType, str]] = set()

        def add(kind: KnowledgeAssetType, identifier: str, origin: str) -> None:
            if (kind, identifier) not in seen:
                seen.add((kind, identifier))
                result.append(KnowledgeGraphImpact(kind, identifier, origin))

        if asset_type == KnowledgeAssetType.TAXONOMY:
            if self._taxonomies.get(asset_id) is None:
                raise ValueError(f"taxonomy {asset_id} does not exist")
            add(asset_type, asset_id, "manual")
            for mo in self._modus_operandi.list():
                if mo.taxonomy_library_id == asset_id:
                    self._add_modus_operandi_tree(add, mo.id, "inherited_from_taxonomy")
        elif asset_type == KnowledgeAssetType.MODUS_OPERANDI:
            mo = self._modus_operandi.get(asset_id)
            if mo is None:
                raise ValueError(f"modus_operandi {asset_id} does not exist")
            # A modus operandi belongs to exactly one taxonomy - promotion
            # (IngestModusOperandiUseCase) hard-requires that parent to
            # already be indexed, so attaching a MO directly must also pull
            # its taxonomy in, not just its own children.
            if self._taxonomies.get(mo.taxonomy_library_id) is not None:
                add(
                    KnowledgeAssetType.TAXONOMY,
                    mo.taxonomy_library_id,
                    "required_by_modus_operandi",
                )
            self._add_modus_operandi_tree(add, asset_id, "manual")
        elif asset_type in (
            KnowledgeAssetType.RED_FLAG,
            KnowledgeAssetType.YELLOW_FLAG,
        ):
            flag = self._flags.get(asset_id)
            if flag is None:
                raise ValueError(f"flag {asset_id} does not exist")
            expected = (
                KnowledgeAssetType.RED_FLAG
                if flag.flag_type.value == "red"
                else KnowledgeAssetType.YELLOW_FLAG
            )
            if asset_type != expected:
                raise ValueError("flag type does not match asset")
            add(asset_type, asset_id, "manual")
        elif asset_type == KnowledgeAssetType.SIMILAR_CASE:
            if self._similar_cases.get(asset_id) is None:
                raise ValueError(f"similar_case {asset_id} does not exist")
            add(asset_type, asset_id, "manual")
        return result

    def preview_add(
        self, instance_id: str, asset_type: KnowledgeAssetType, asset_id: str
    ) -> list[KnowledgeGraphImpact]:
        existing = {
            (item.asset_type, item.asset_id)
            for item in self._instances.list_assets(instance_id)
        }
        return [
            item
            for item in self.expansion(asset_type, asset_id)
            if (item.asset_type, item.asset_id) not in existing
        ]

    def attach(
        self, instance_id: str, asset_type: KnowledgeAssetType, asset_id: str
    ) -> list[VectorStoreInstanceAsset]:
        root_type, root_id = asset_type, asset_id
        created: list[VectorStoreInstanceAsset] = []
        for item in self.preview_add(instance_id, asset_type, asset_id):
            relation = VectorStoreInstanceAsset(
                vector_store_instance_id=instance_id,
                asset_type=item.asset_type,
                asset_id=item.asset_id,
                asset_version=1,
                origin=item.origin,
                root_asset_type=root_type,
                root_asset_id=root_id,
                embedding=self._cached_embedding(item.asset_type, item.asset_id),
            )
            self._instances.add_asset(relation)
            created.append(relation)
        return created

    def affected_instances_for_new_asset(
        self, asset_type: KnowledgeAssetType, asset_id: str
    ) -> list[str]:
        """Instances whose inherited closure must gain a newly created asset."""
        if asset_type == KnowledgeAssetType.TAXONOMY:
            # A new taxonomy is a new root of the managed knowledge base, so
            # it belongs to every administrable instance by policy.
            return [instance.id for instance in self._instances.list()]
        result: list[str] = []
        for instance in self._instances.list():
            relations = self._instances.list_assets(instance.id)
            relation_keys = {(item.asset_type, item.asset_id) for item in relations}
            if (asset_type, asset_id) in relation_keys:
                continue
            followed_parent_keys = {
                (item.asset_type, item.asset_id)
                for item in relations
                if item.follow_source_updates
            }
            if self._belongs_to_selected_ancestor(
                asset_type, asset_id, followed_parent_keys
            ):
                result.append(instance.id)
        return result

    def synchronize_new_asset(
        self, asset_type: KnowledgeAssetType, asset_id: str
    ) -> list[str]:
        """Propagates a newly created descendant into every eligible instance.

        A new taxonomy is a root and is propagated to every administrable
        instance. Descendants inherit their parent's instance membership.
        """
        affected = self.affected_instances_for_new_asset(asset_type, asset_id)
        for instance_id in affected:
            self.attach(instance_id, asset_type, asset_id)
        return affected

    def detach_tree_from_all_instances(
        self, asset_type: KnowledgeAssetType, asset_id: str
    ) -> list[str]:
        """Removes relation rows for a retired root and all of its descendants."""
        targets = {
            (item.asset_type, item.asset_id)
            for item in self.expansion(asset_type, asset_id)
        }
        affected: list[str] = []
        for instance in self._instances.list():
            removed = False
            for relation in self._instances.list_assets(instance.id):
                if (relation.asset_type, relation.asset_id) in targets:
                    self._instances.remove_asset(instance.id, relation.relation_id)
                    removed = True
            if removed:
                affected.append(instance.id)
        return affected

    def _belongs_to_selected_ancestor(
        self, asset_type, asset_id, relation_keys
    ) -> bool:
        if asset_type == KnowledgeAssetType.MODUS_OPERANDI:
            mo = self._modus_operandi.get(asset_id)
            return bool(
                mo
                and (KnowledgeAssetType.TAXONOMY, mo.taxonomy_library_id)
                in relation_keys
            )
        if asset_type == KnowledgeAssetType.SIMILAR_CASE:
            case = self._similar_cases.get(asset_id)
            return bool(
                case
                and (KnowledgeAssetType.MODUS_OPERANDI, case.modus_operandi_library_id)
                in relation_keys
            )
        if asset_type in (KnowledgeAssetType.RED_FLAG, KnowledgeAssetType.YELLOW_FLAG):
            flag = self._flags.get(asset_id)
            return bool(
                flag
                and any(
                    (KnowledgeAssetType.MODUS_OPERANDI, mo_id) in relation_keys
                    for mo_id in flag.modus_operandi_library_ids
                )
            )
        return False

    def _add_modus_operandi_tree(
        self, add, modus_operandi_id: str, origin: str
    ) -> None:
        add(KnowledgeAssetType.MODUS_OPERANDI, modus_operandi_id, origin)
        for case in self._similar_cases.list():
            if case.modus_operandi_library_id == modus_operandi_id:
                add(
                    KnowledgeAssetType.SIMILAR_CASE,
                    case.id,
                    "inherited_from_modus_operandi",
                )
        for flag in self._flags.list():
            if modus_operandi_id in flag.modus_operandi_library_ids:
                kind = (
                    KnowledgeAssetType.RED_FLAG
                    if flag.flag_type.value == "red"
                    else KnowledgeAssetType.YELLOW_FLAG
                )
                add(kind, flag.id, "inherited_from_modus_operandi")

    def _cached_embedding(
        self, asset_type: KnowledgeAssetType, asset_id: str
    ) -> list[float] | None:
        # Recycles whatever the Library entry already has cached (computed
        # on its own create/update) instead of embedding again here -
        # PromoteVectorStoreInstanceUseCase reads this straight off the
        # relation row.
        if asset_type == KnowledgeAssetType.TAXONOMY:
            entry = self._taxonomies.get(asset_id)
        elif asset_type == KnowledgeAssetType.MODUS_OPERANDI:
            entry = self._modus_operandi.get(asset_id)
        elif asset_type in (
            KnowledgeAssetType.RED_FLAG,
            KnowledgeAssetType.YELLOW_FLAG,
        ):
            entry = self._flags.get(asset_id)
        else:
            entry = self._similar_cases.get(asset_id)
        return entry.embedding if entry is not None else None
