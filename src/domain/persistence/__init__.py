from __future__ import annotations

import abc
from typing import Any, List, Optional
from langchain.schema import BaseRetriever
from langchain_core.documents import Document


class AbstractPersistenceUnitOfWork(abc.ABC):
    _storage_connection: Any

    def __enter__(self) -> AbstractPersistenceUnitOfWork:
        return self

    def __exit__(self, *args):
        self.close()

    @abc.abstractmethod
    def get_connection(self):
        raise NotImplementedError

    @abc.abstractmethod
    def get_as_parent_retriever(
        self,
        source_filter: str | None = None,
    ) -> BaseRetriever:
        raise NotImplementedError

    @abc.abstractmethod
    def search_conceptual(
        self, question: str, source_filter: Optional[str] = None, k: int = 4
    ) -> List[Document]:
        """Hybrid search biased toward high-level ideas."""
        raise NotImplementedError

    @abc.abstractmethod
    def search_technical(
        self, question: str, source_filter: Optional[str] = None, k: int = 4
    ) -> List[Document]:
        """Hybrid search biased toward IDs / specific terms."""
        raise NotImplementedError

    @abc.abstractmethod
    def search_precision(
        self, question: str, source_filter: Optional[str] = None, k: int = 4
    ) -> List[Document]:
        """Hybrid search with exact match emphasis."""
        raise NotImplementedError

    @abc.abstractmethod
    def search_narrative(
        self, question: str, source_filter: Optional[str] = None, k: int = 4
    ) -> List[Document]:
        """Hybrid search biased toward natural / narrative context."""
        raise NotImplementedError

    @abc.abstractmethod
    def close(self):
        raise NotImplementedError
    
