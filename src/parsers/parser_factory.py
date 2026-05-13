import logging
from typing import Optional
from src.parsers.base_parser import BaseParser
from src.parsers.hdfc_parser import HDFCParser
from src.parsers.icici_parser import ICICIParser
from src.parsers.axis_parser import AxisParser

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


class ParserFactory:
    """
    Factory class to select the appropriate bank parser.
    
    Supports:
    - Explicit bank selection via get_parser(bank_name)
    - Auto-detection via detect_bank(file_path)
    """
    
    # Mapping of bank names to parser classes
    PARSERS = {
        'hdfc': HDFCParser,
        'icici': ICICIParser,
        'axis': AxisParser,
    }
    
    @staticmethod
    def get_parser(bank_name: str) -> BaseParser:
        """
        Get a parser instance for a specific bank.
        
        Args:
            bank_name: Bank name (case-insensitive). Supported: 'hdfc', 'icici'
            
        Returns:
            Parser instance for the specified bank
            
        Raises:
            ValueError: If bank is not supported
        """
        bank_name_lower = bank_name.lower().strip()
        
        if bank_name_lower not in ParserFactory.PARSERS:
            supported = ', '.join(ParserFactory.PARSERS.keys())
            raise ValueError(f"Bank '{bank_name}' is not supported. Supported banks: {supported}")
        
        parser_class = ParserFactory.PARSERS[bank_name_lower]
        return parser_class()
    
    @staticmethod
    def detect_bank(file_path: str) -> Optional[str]:
        """
        Auto-detect the bank based on PDF format.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            Bank name if detected, None otherwise
        """
        for bank_name, parser_class in ParserFactory.PARSERS.items():
            parser = parser_class()
            try:
                if parser.validate_format(file_path):
                    logging.info(f"Detected bank format: {bank_name.upper()}")
                    return bank_name
            except Exception as e:
                logging.debug(f"Error validating {bank_name} format: {str(e)}")
                continue
        
        logging.warning("Could not detect bank format. Please specify bank explicitly with --bank flag.")
        return None
    
    @staticmethod
    def get_supported_banks():
        """Get list of supported banks."""
        return list(ParserFactory.PARSERS.keys())
