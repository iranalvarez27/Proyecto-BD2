from abc import ABC, abstractmethod
from typing import Any

from common.types import RID


class Index(ABC):
    
    @abstractmethod
    def insert(self, key: Any, rid: RID) -> None: ...

    @abstractmethod
    def search(self, key: Any) -> list[RID]: ...

    @abstractmethod
    def range_search(self, low: Any, high: Any) -> list[RID]:
        """Inclusive [low, high]. Not implemented by ExtendibleHash: hashing
        destroys key ordering, so a range would require scanning every
        bucket (worse than a linear scan)."""
        ...

    @abstractmethod
    def delete(self, key: Any, rid: RID) -> bool: ...
