from abc import ABC, abstractmethod


class BackupTaskDispatcher(ABC):
    @abstractmethod
    def dispatch(self, backup_id: str) -> None:
        raise NotImplementedError
