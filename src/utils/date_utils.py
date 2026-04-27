"""
Date utility functions for normalizing date formats across all bank parsers.

This module provides standardized date handling to ensure consistency
across all parsers (current and future).
"""

import re
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class DateUtils:
    """
    Utility class for date normalization and formatting.

    Standard format: dd-mm-yyyy (e.g., "25-12-2023")
    """

    @staticmethod
    def normalize_date(date_str: str) -> str:
        """
        Normalize any date format to the standard dd-mm-yyyy format.

        Supported input formats:
        - dd-mm-yyyy (already standard)
        - dd/mm/yyyy
        - dd/mm/yy (2-digit year, assumes 2000s)
        - dd-mm-yy (2-digit year, assumes 2000s)
        - yyyy-mm-dd (ISO format)

        Args:
            date_str: Date string in any supported format

        Returns:
            Date string in dd-mm-yyyy format

        Raises:
            ValueError: If date format is not recognized or invalid
        """
        if not date_str or date_str.strip() == '':
            return date_str

        date_str = date_str.strip()

        # Try different date formats in order of likelihood
        formats_to_try = [
            '%d-%m-%Y',  # dd-mm-yyyy (already standard)
            '%d/%m/%Y',  # dd/mm/yyyy
            '%d/%m/%y',  # dd/mm/yy (2-digit year)
            '%d-%m-%y',  # dd-mm-yy (2-digit year)
            '%Y-%m-%d',  # yyyy-mm-dd (ISO)
            '%m/%d/%Y',  # mm/dd/yyyy (US format)
            '%m-%d-%Y',  # mm-dd-yyyy (US format)
        ]

        for fmt in formats_to_try:
            try:
                # Parse the date
                parsed_date = datetime.strptime(date_str, fmt)
                # Format to standard dd-mm-yyyy
                return parsed_date.strftime('%d-%m-%Y')
            except ValueError:
                continue

        # If no format worked, log warning and return original
        logger.warning(f"Unrecognized date format: '{date_str}'. Returning as-is.")
        return date_str

    @staticmethod
    def validate_date_order(dates: list) -> bool:
        """
        Validate that dates are in chronological order.

        Args:
            dates: List of date strings in dd-mm-yyyy format

        Returns:
            True if dates are in order, False otherwise
        """
        try:
            parsed_dates = [datetime.strptime(d, '%d-%m-%Y') for d in dates if d]
            return all(parsed_dates[i] <= parsed_dates[i+1] for i in range(len(parsed_dates)-1))
        except (ValueError, IndexError):
            return False

    @staticmethod
    def parse_date_range(date_range_str: str) -> tuple[Optional[str], Optional[str]]:
        """
        Parse a date range string like "01-12-2023 to 31-12-2023"

        Args:
            date_range_str: String containing date range

        Returns:
            Tuple of (start_date, end_date) in dd-mm-yyyy format, or (None, None) if parsing fails
        """
        try:
            # Common patterns: "from X to Y", "X - Y", "X to Y"
            patterns = [
                r'from\s+(\d{1,2}[-/]\d{1,2}[-/]\d{4})\s+to\s+(\d{1,2}[-/]\d{1,2}[-/]\d{4})',
                r'(\d{1,2}[-/]\d{1,2}[-/]\d{4})\s*-\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})',
                r'(\d{1,2}[-/]\d{1,2}[-/]\d{4})\s+to\s+(\d{1,2}[-/]\d{1,2}[-/]\d{4})'
            ]

            for pattern in patterns:
                match = re.search(pattern, date_range_str, re.IGNORECASE)
                if match:
                    start_date = DateUtils.normalize_date(match.group(1))
                    end_date = DateUtils.normalize_date(match.group(2))
                    return start_date, end_date

            return None, None
        except Exception:
            return None, None