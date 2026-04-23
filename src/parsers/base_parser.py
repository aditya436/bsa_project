from abc import ABC, abstractmethod
from typing import List
from src.models.transaction import Transaction

class BaseParser(ABC):
    @abstractmethod
    def parse(self, file_path: str) -> List[Transaction]:
        pass