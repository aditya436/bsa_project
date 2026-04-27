# Bank Statement Parser - Architecture Guide

## Overview

This document explains the architecture of the Bank Statement Parser project and how to extend it with new bank support.

## Architecture Diagram

```
┌─────────────────────────────────────────────────┐
│                   main.py                       │
│            (CLI Entry Point)                    │
│  - Handles command-line arguments               │
│  - Selects appropriate parser                   │
│  - Displays results                             │
└────────────────┬────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────┐
│            ParserFactory                        │
│      (Parser Selection & Management)            │
│  - get_parser(bank_name)                        │
│  - detect_bank(file_path)                       │
│  - get_supported_banks()                        │
└────────┬─────────────┬──────────┬───────────────┘
         │             │          │
         ▼             ▼          ▼
    ┌────────┐  ┌────────┐  ┌──────────┐
    │BaseParser│  (Abstract Base Class)    │
    │ - parse()│  │      - parse_metadata() │
    │ - parse_ │  │      - validate_format()│
    │  metadata│  │                        │
    │ - valida │  │                        │
    │  te_for  │  │                        │
    │   mat()  │  │                        │
    └────────┘  └────────┘  └──────────┘
        │           │            │
        ▼           ▼            ▼
    ┌───────────────────────────────────────┐
    │        Bank-Specific Parsers          │
    ├───────────────────────────────────────┤
    │ HDFCParser   ✓ Fully Implemented      │
    │ ICICIParser  ⊗ Template (Ready)       │
    │ AxisParser   📋 Future                │
    │ YBankParser  📋 Future                │
    └───────────────────────────────────────┘
        │           │            │
        ▼           ▼            ▼
    ┌──────────────────────────────────────┐
    │     Transaction Model                │
    │  (dataclass)                         │
    │  - date, narration, chq_ref_no       │
    │  - value_dt, withdrawal/deposit amt  │
    │  - closing_balance                   │
    └──────────────────────────────────────┘
```

## Core Components

### 1. BaseParser (src/parsers/base_parser.py)

Abstract base class that all bank parsers must inherit from.

**Methods:**
- `parse(file_path: str) -> List[Transaction]`
  - Main method to extract transactions from PDF
  - Returns list of Transaction objects
  
- `parse_metadata(file_path: str) -> Dict[str, str]`
  - Extract account details, statement period, etc.
  - Returns dictionary with metadata
  
- `validate_format(file_path: str) -> bool`
  - Validates if PDF matches this bank's format
  - Used for auto-detection

### 2. HDFCParser (src/parsers/hdfc_parser.py)

Full implementation for HDFC Bank statements.

**Key Features:**
- Extracts 7-column transactions (Date, Narration, Chq/Ref No., Value Date, Withdrawal, Deposit, Closing Balance)
- Balance-based debit/credit inference
- Comprehensive validation (chronological order, balance consistency, amount verification)
- Metadata extraction (account holder, IFSC, account open date, statement period)
- Statement summary parsing (opening/closing balance, debit/credit counts)

**Implementation Details:**
- Date format: DD/MM/YY
- Amount format: 1,000.00
- PDF extraction via `pdfplumber`
- Multi-line transaction handling for long narrations

### 3. ICICIParser (src/parsers/icici_parser.py)

Template/skeleton for ICICI Bank support.

**Status:** Ready for implementation
**TODO:**
- Determine ICICI PDF format and column layout
- Implement transaction parsing logic
- Implement metadata extraction
- Test with sample ICICI statements

### 4. ParserFactory (src/parsers/parser_factory.py)

Factory pattern implementation for parser selection.

**Methods:**
- `get_parser(bank_name: str) -> BaseParser`
  - Returns parser instance for given bank
  - Raises ValueError if bank not supported
  
- `detect_bank(file_path: str) -> Optional[str]`
  - Analyzes PDF to auto-detect bank format
  - Returns bank name or None
  
- `get_supported_banks() -> List[str]`
  - Returns list of supported bank names

**Parser Registry:**
```python
PARSERS = {
    'hdfc': HDFCParser,
    'icici': ICICIParser,
    # Add new banks here
}
```

## Data Flow

### 1. User Input
```bash
python main.py --file data/statement.pdf --bank hdfc
```

### 2. Parser Selection
```
main.py
  ↓
  ParserFactory.get_parser('hdfc')
  ↓
  HDFCParser instance
```

### 3. PDF Processing
```
HDFCParser.parse(file_path)
  ↓
  pdfplumber.open(file_path)
  ↓
  Extract text and parse transactions
  ↓
  List[Transaction]
```

### 4. Output Generation
```
Transaction objects
  ↓
  pandas.DataFrame
  ↓
  Display with metadata
```

## Adding a New Bank Parser

### Step-by-Step Guide

#### 1. Create Parser File
Create `src/parsers/<bank_name>_parser.py`:

```python
from src.parsers.base_parser import BaseParser
from src.models.transaction import Transaction
from typing import List, Dict
import pdfplumber
import re
import logging

class YourBankParser(BaseParser):
    """Parser for YourBank statement PDFs."""
    
    def parse(self, file_path: str) -> List[Transaction]:
        """Extract transactions from YourBank statement."""
        transactions = []
        # Implement your bank's specific parsing logic
        # 1. Open PDF with pdfplumber
        # 2. Extract text from pages
        # 3. Identify and parse transaction lines
        # 4. Create Transaction objects
        # 5. Apply validation
        return transactions
    
    def parse_metadata(self, file_path: str) -> Dict[str, str]:
        """Extract account metadata."""
        metadata = {
            'Bank': 'YourBank',
            'Account Number': '',
            'Account Holder': '',
            # Add relevant fields
        }
        # Extract from PDF
        return metadata
    
    def validate_format(self, file_path: str) -> bool:
        """Check if PDF is from YourBank."""
        try:
            with pdfplumber.open(file_path) as pdf:
                first_page_text = pdf.pages[0].extract_text()
                # Look for bank-specific markers
                markers = ['YourBank', 'Account Statement']
                return sum(1 for m in markers if m in first_page_text) >= 1
        except:
            return False
```

#### 2. Register in ParserFactory
Edit `src/parsers/parser_factory.py`:

```python
from src.parsers.yourbank_parser import YourBankParser

class ParserFactory:
    PARSERS = {
        'hdfc': HDFCParser,
        'icici': ICICIParser,
        'yourbank': YourBankParser,  # Add this line
    }
```

#### 3. Test the Parser
```bash
python main.py --file data/yourbank_statement.pdf --bank yourbank
```

#### 4. Update Documentation
- Update README.md with new bank in the "Supported Banks" table
- Add parser documentation
- Provide sample usage examples

## Implementation Checklist for New Banks

- [ ] Analyze target bank's PDF format
- [ ] Identify column headers and transaction pattern
- [ ] Create parser class inheriting from BaseParser
- [ ] Implement `parse()` method with transaction extraction
- [ ] Implement `parse_metadata()` method with account info extraction
- [ ] Implement `validate_format()` for format detection
- [ ] Add regex patterns for your bank's specific formats
- [ ] Handle multi-line transactions if applicable
- [ ] Add validation logic (date order, balance consistency, etc.)
- [ ] Register in ParserFactory
- [ ] Test with sample PDFs
- [ ] Update documentation
- [ ] Add test cases in `tests/` directory

## Common Parsing Challenges

### 1. Multi-Line Transactions
**Problem:** Narration or other fields span multiple lines in PDF text

**Solution:**
```python
# Collect continuation lines until next transaction marker
while i < len(lines) and not is_transaction_start(lines[i]):
    content += ' ' + lines[i].strip()
    i += 1
```

### 2. Amount Parsing
**Problem:** Different banks format amounts differently (1000, 1,000, 1000.00, 1,000.00)

**Solution:**
```python
# Use flexible regex that handles multiple formats
pattern = r'\d+(?:,\d{3})*(?:\.\d{2})?'
# Normalize: remove commas, convert to float
amount = float(amount_str.replace(',', ''))
```

### 3. Date Format Detection
**Problem:** Banks use different date formats

**Solution:**
```python
from datetime import datetime

# Try multiple formats
for fmt in ['%d/%m/%Y', '%d/%m/%y', '%d-%m-%Y']:
    try:
        date_obj = datetime.strptime(date_str, fmt)
        break
    except ValueError:
        continue
```

### 4. Auto-Detection Reliability
**Problem:** Need robust format validation

**Solution:**
```python
def validate_format(self, file_path: str) -> bool:
    # Look for multiple bank-specific markers
    # Check at least 2-3 markers to reduce false positives
    markers_found = 0
    if 'Bank Name' in text:
        markers_found += 1
    if 'Account Number' in text:
        markers_found += 1
    # etc...
    return markers_found >= 2
```

## Testing

### Unit Tests
Located in `tests/` directory.

Example test for new parser:
```python
import pytest
from src.parsers.yourbank_parser import YourBankParser

def test_yourbank_parse():
    parser = YourBankParser()
    transactions = parser.parse('tests/data/yourbank_sample.pdf')
    assert len(transactions) > 0
    assert transactions[0].date is not None

def test_yourbank_validate_format():
    parser = YourBankParser()
    assert parser.validate_format('tests/data/yourbank_sample.pdf') == True
    assert parser.validate_format('tests/data/hdfc_sample.pdf') == False
```

### Manual Testing
```bash
# Test auto-detection
python main.py --file data/yourbank_statement.pdf

# Test explicit selection
python main.py --file data/yourbank_statement.pdf --bank yourbank

# View help
python main.py --help
```

## Performance Considerations

- **PDF Extraction:** `pdfplumber` is relatively fast but can be slow for large PDFs
- **Regex Parsing:** Pre-compile common patterns for reuse
- **Memory:** Large DataFrames should be paginated for display
- **Caching:** Consider caching parsed results if reprocessing same PDFs

## Future Enhancements

1. **Support for more banks:**
   - Axis Bank
   - ICICI Bank (complete implementation)
   - IDBI Bank
   - Kotak Mahindra Bank
   - Yes Bank

2. **Features:**
   - CSV/Excel export
   - Transaction categorization
   - Duplicate detection
   - Anomaly detection
   - Multi-statement merging

3. **Validation:**
   - Cheque number uniqueness
   - Transaction tampering detection
   - Balance reconciliation

4. **UI:**
   - Web dashboard
   - File upload interface
   - Interactive filtering

## References

- [pdfplumber Documentation](https://github.com/jsvine/pdfplumber)
- [pandas Documentation](https://pandas.pydata.org/)
- [Python Regex](https://docs.python.org/3/library/re.html)
- [Design Patterns - Factory Pattern](https://refactoring.guru/design-patterns/factory-method)
