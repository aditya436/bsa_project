# Bank Statement Parser

A Python-based, extensible engine for parsing bank statements in PDF format. Currently supports HDFC and ICICI banks with a clean architecture for adding more banks.

## Features

- **Multi-bank support**: HDFC, ICICI (with easy extensibility for more)
- **Transaction parsing**: Extracts all transaction details with validation
- **Metadata extraction**: Account holder info, statement period, IFSC codes, etc.
- **Statement summary**: Opening balance, closing balance, debit/credit counts
- **Auto-detection**: Automatically detects bank format or allows explicit specification
- **Validation**: Transaction validation, chronological order checks, amount verification
- **DataFrame output**: Easy pandas integration for further analysis

## Installation

```bash
# Clone the repository
git clone https://github.com/aditya436/BSA-Project.git
cd BSA-Project

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Basic Usage (Auto-detect bank)
```bash
python main.py --file data/statement.pdf
```

### Explicit Bank Specification
```bash
python main.py --file data/statement.pdf --bank hdfc
python main.py --file data/statement.pdf --bank icici
```

### Help
```bash
python main.py --help
```

## Project Structure

```
BSA-Project/
├── src/
│   ├── parsers/
│   │   ├── base_parser.py              # Abstract base class for all parsers
│   │   ├── hdfc_parser.py              # HDFC-specific parser implementation
│   │   ├── icici_parser.py             # ICICI-specific parser template
│   │   ├── parser_factory.py           # Factory pattern for parser selection
│   │   └── pdf_parser.py               # (Deprecated - use hdfc_parser.py)
│   └── models/
│       └── transaction.py              # Transaction data model
├── data/                               # Sample and user PDF files
├── tests/                              # Unit tests
├── main.py                             # Entry point
├── requirements.txt                    # Dependencies
└── README.md                           # This file
```

## Architecture

### Parser Hierarchy
```
BaseParser (Abstract)
├── HDFCParser    ✓ Fully implemented
└── ICICIParser   ⊗ Template ready for implementation
```

### Adding a New Bank Parser

1. **Create a new parser file** (e.g., `src/parsers/axis_parser.py`)

```python
from src.parsers.base_parser import BaseParser
from src.models.transaction import Transaction
from typing import List, Dict

class AxisParser(BaseParser):
    def parse(self, file_path: str) -> List[Transaction]:
        # Implement Axis-specific parsing logic
        pass
    
    def parse_metadata(self, file_path: str) -> Dict[str, str]:
        # Implement Axis-specific metadata extraction
        pass
    
    def validate_format(self, file_path: str) -> bool:
        # Implement format validation for Axis PDFs
        pass
```

2. **Register in ParserFactory** (`src/parsers/parser_factory.py`)

```python
from src.parsers.axis_parser import AxisParser

class ParserFactory:
    PARSERS = {
        'hdfc': HDFCParser,
        'icici': ICICIParser,
        'axis': AxisParser,  # Add this line
    }
```

3. **Use the new parser**

```bash
python main.py --file data/axis_statement.pdf --bank axis
```

## Supported Banks

| Bank | Status | Parser | Auto-detect |
|------|--------|--------|-------------|
| HDFC | ✓ Complete | `HDFCParser` | Yes |
| ICICI | ⊗ Template | `ICICIParser` | Partial |
| More... | 📋 Future | TBD | TBD |

## Data Models

### Transaction
```python
@dataclass
class Transaction:
    date: str                    # Transaction date (DD/MM/YY)
    narration: str              # Transaction description
    chq_ref_no: str            # Cheque/Reference number
    value_dt: str              # Value date (DD/MM/YY)
    withdrawal_amt: str        # Debit amount
    deposit_amt: str           # Credit amount
    closing_balance: str       # Balance after transaction
```

## Dependencies

- `pdfplumber`: PDF text extraction
- `pandas`: DataFrame creation and manipulation
- Python 3.8+

See `requirements.txt` for all dependencies.

## Validation & Error Handling

The parser includes several validation mechanisms:

1. **Format Validation**: Checks if PDF matches expected bank format
2. **Balance Validation**: Verifies closing balance is numeric
3. **Chronological Order**: Ensures transactions are in date order
4. **Amount Verification**: Cross-checks calculated vs. extracted amounts
5. **Negative Balance Detection**: Alerts on unexpected negative balances

All warnings are logged to help identify data issues.

## Example Output

```
Parsed 25 transactions from data/statement.pdf

Account Metadata:
             Bank                 HDFC
Name         John Doe
Email        john@example.com
IFSC code    HDFC0001234
From date    01/04/2024
To date      30/04/2024

Transactions DataFrame:
         date           narration  withdrawal_amt  deposit_amt  closing_balance
0   01/04/2024    SALARY CREDIT         -         50000.00      125000.00
1   02/04/2024    WATER BILL           450.00      -           124550.00
2   03/04/2024    TRANSFER IN          -         5000.00       129550.00
```

## Contributing

To add support for a new bank:

1. Create a parser class inheriting from `BaseParser`
2. Implement `parse()`, `parse_metadata()`, and `validate_format()` methods
3. Register in `ParserFactory.PARSERS`
4. Add test files in `tests/`
5. Update this README

## License

MIT

## Author

Aditya (@aditya436)
