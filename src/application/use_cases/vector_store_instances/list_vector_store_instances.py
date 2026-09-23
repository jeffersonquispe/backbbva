from src.application.ports.vector_store_instance_port import VectorStoreInstanceRepository


class ListVectorStoreInstancesUseCase:
    def __init__(self, repository: VectorStoreInstanceRepository) -> None:
        self._repository = repository

    def execute(self):
        return self._repository.list()
