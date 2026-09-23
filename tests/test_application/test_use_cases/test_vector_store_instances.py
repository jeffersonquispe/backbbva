from src.application.ports.vector_store_instance_port import (
    KnowledgeAssetType,
    VectorStoreInstance,
    VectorStoreInstanceAsset,
)
from src.application.use_cases.vector_store_instances.create_vector_store_instance import (
    CreateVectorStoreInstanceUseCase,
)
from src.application.use_cases.vector_store_instances.manage_vector_store_instance import (
    AddVectorStoreDocumentUseCase, RemoveVectorStoreDocumentUseCase,
)


class InMemoryInstances:
    def __init__(self) -> None:
        self.instances: list[VectorStoreInstance] = []
        self.assets: list[VectorStoreInstanceAsset] = []

    def create(self, instance, assets):
        self.instances.append(instance)
        self.assets.extend(assets)
        return instance

    def list(self):
        return self.instances

    def get(self, instance_id):
        return next((item for item in self.instances if item.id == instance_id), None)

    def update(self, instance):
        self.instances = [instance if item.id == instance.id else item for item in self.instances]
        return instance

    def list_assets(self, instance_id):
        return [asset for asset in self.assets if asset.vector_store_instance_id == instance_id]

    def add_asset(self, asset):
        self.assets.append(asset)
        return asset

    def remove_asset(self, instance_id, relation_id):
        self.assets = [asset for asset in self.assets if not (asset.vector_store_instance_id == instance_id and asset.relation_id == relation_id)]


def test_vector_store_instance_is_numbered_and_keeps_asset_embedding_snapshot() -> None:
    repository = InMemoryInstances()
    use_case = CreateVectorStoreInstanceUseCase(repository)
    source = VectorStoreInstanceAsset(
        vector_store_instance_id="ignored",
        asset_type=KnowledgeAssetType.MODUS_OPERANDI,
        asset_id="modus_operandi_id00001",
        asset_version=1,
        embedding=[0.1, 0.2],
    )

    created = use_case.execute(
        name="Producción inicial", description="Primera carga", created_by="david", assets=[source]
    )
    source.embedding[0] = 99

    assert created.id == "vector-store-v1"
    assert created.name == "Producción inicial"
    assert created.created_by == "david"
    assert repository.assets[0].relation_id == "v1:modus_operandi:modus_operandi_id00001"
    assert repository.assets[0].embedding == [0.1, 0.2]


def test_adding_and_removing_document_only_changes_instance_relation() -> None:
    repository = InMemoryInstances()
    instance = CreateVectorStoreInstanceUseCase(repository).execute(
        name="Producción", description="", created_by="david", assets=[]
    )
    added = AddVectorStoreDocumentUseCase(repository).execute(
        instance.id, asset_type=KnowledgeAssetType.TAXONOMY, asset_id="taxonomy-1", actor="david"
    )

    assert added.embedding is None
    assert repository.list_assets(instance.id) == [added]
    assert repository.get(instance.id).updated_by == "david"

    RemoveVectorStoreDocumentUseCase(repository).execute(instance.id, added.relation_id, actor="david")

    assert repository.list_assets(instance.id) == []
