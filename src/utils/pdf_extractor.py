"""
Robust PDF text extraction utilities with fallback mechanisms.

This module provides multiple PDF parsing approaches to handle different PDF types
and overcome limitations of individual libraries.
"""

import logging
from typing import Optional, List

logger = logging.getLogger(__name__)

class PDFExtractor:
    """
    Robust PDF text extractor with multiple fallback libraries.

    Priority order:
    1. pdfplumber - Best for structured text and tables
    2. PyMuPDF (fitz) - Very robust, handles complex PDFs well
    3. pdfminer.six - Good for text-heavy PDFs
    4. pypdf - Basic fallback for simple PDFs
    """

    @staticmethod
    def extract_text_fallback(file_path: str) -> Optional[str]:
        """
        Extract text from PDF using multiple libraries with fallback.

        Returns the text from the first successful extraction method.
        """
        extractors = [
            PDFExtractor._extract_with_pdfplumber,
            PDFExtractor._extract_with_pymupdf,
            PDFExtractor._extract_with_pdfminer,
            PDFExtractor._extract_with_pypdf,
        ]

        for extractor in extractors:
            try:
                text = extractor(file_path)
                if text and text.strip():
                    logger.info(f"Successfully extracted text using {extractor.__name__}")
                    return text
            except KeyboardInterrupt:
                logger.warning(f"{extractor.__name__} interrupted (KeyboardInterrupt) - trying next library")
                continue
            except Exception as e:
                logger.warning(f"{extractor.__name__} failed: {str(e)}")
                continue

        logger.error(f"All PDF extraction methods failed for {file_path}")
        return None

    @staticmethod
    def extract_pages_fallback(file_path: str) -> Optional[List[str]]:
        """
        Extract text from each page as separate strings.

        Returns list of page texts, one per page.
        """
        extractors = [
            PDFExtractor._extract_pages_with_pdfplumber,
            PDFExtractor._extract_pages_with_pymupdf,
            PDFExtractor._extract_pages_with_pdfminer,
            PDFExtractor._extract_pages_with_pypdf,
        ]

        for extractor in extractors:
            try:
                pages = extractor(file_path)
                if pages and any(page.strip() for page in pages):
                    logger.info(f"Successfully extracted pages using {extractor.__name__}")
                    return pages
            except KeyboardInterrupt:
                logger.warning(f"{extractor.__name__} interrupted (KeyboardInterrupt) - trying next library")
                continue
            except Exception as e:
                logger.warning(f"{extractor.__name__} failed: {str(e)}")
                continue

        logger.error(f"All PDF page extraction methods failed for {file_path}")
        return None

    @staticmethod
    def _extract_with_pdfplumber(file_path: str) -> Optional[str]:
        """Extract text using pdfplumber."""
        import pdfplumber

        with pdfplumber.open(file_path) as pdf:
            text = ""
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            return text.strip()

    @staticmethod
    def _extract_with_pymupdf(file_path: str) -> Optional[str]:
        """Extract text using PyMuPDF (fitz)."""
        import fitz

        doc = fitz.open(file_path)
        text = ""
        for page in doc:
            page_text = page.get_text()
            if page_text:
                text += page_text + "\n"
        doc.close()
        return text.strip()

    @staticmethod
    def _extract_with_pdfminer(file_path: str) -> Optional[str]:
        """Extract text using pdfminer.six."""
        from pdfminer.high_level import extract_text

        return extract_text(file_path)

    @staticmethod
    def _extract_with_pypdf(file_path: str) -> Optional[str]:
        """Extract text using pypdf."""
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text.strip()

    @staticmethod
    def _extract_pages_with_pdfplumber(file_path: str) -> Optional[List[str]]:
        """Extract pages using pdfplumber."""
        import pdfplumber

        with pdfplumber.open(file_path) as pdf:
            pages = []
            for page in pdf.pages:
                page_text = page.extract_text()
                pages.append(page_text or "")
            return pages

    @staticmethod
    def _extract_pages_with_pymupdf(file_path: str) -> Optional[List[str]]:
        """Extract pages using PyMuPDF (fitz)."""
        import fitz

        doc = fitz.open(file_path)
        pages = []
        for page in doc:
            page_text = page.get_text()
            pages.append(page_text or "")
        doc.close()
        return pages

    @staticmethod
    def _extract_pages_with_pdfminer(file_path: str) -> Optional[List[str]]:
        """Extract pages using pdfminer.six."""
        # pdfminer doesn't have direct page-by-page extraction
        # Extract all text and split by page breaks (approximation)
        text = PDFExtractor._extract_with_pdfminer(file_path)
        if text:
            # This is a rough approximation - pdfminer doesn't preserve page boundaries well
            pages = text.split('\f')  # Form feed character sometimes separates pages
            return pages if len(pages) > 1 else [text]
        return None

    @staticmethod
    def _extract_pages_with_pypdf(file_path: str) -> Optional[List[str]]:
        """Extract pages using pypdf."""
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        pages = []
        for page in reader.pages:
            page_text = page.extract_text()
            pages.append(page_text or "")
        return pages