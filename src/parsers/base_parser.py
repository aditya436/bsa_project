from abc import ABC, abstractmethod
from typing import List, Dict
from src.models.transaction import Transaction


class BaseParser(ABC):
    """
    Abstract base class for all bank statement parsers.
    
    Each bank parser should implement the parse and parse_metadata methods
    to extract transactions and account metadata from their specific PDF format.
    """
    
    @abstractmethod
    def parse(self, file_path: str) -> List[Transaction]:
        """
        Parse transactions from a bank statement PDF.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            List of Transaction objects
        """
        pass
    
    @abstractmethod
    def parse_metadata(self, file_path: str) -> Dict[str, str]:
        """
        Parse account metadata from a bank statement PDF.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            Dictionary containing metadata like account number, account holder name, etc.
        """
        pass
    
    @abstractmethod
    def validate_format(self, file_path: str) -> bool:
        """
        Validate if the PDF is from this bank's format.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            True if the PDF format matches this bank's format, False otherwise
        """
        pass

