# Quick Reference - Adding a New Bank Parser

## 5-Minute Quick Start

### 1. Create Parser Class
File: `src/parsers/yourbank_parser.py`
```python
from src.parsers.base_parser import BaseParser
from src.models.transaction import Transaction
from typing import List, Dict
import pdfplumber

class YourBankParser(BaseParser):
    def parse(self, file_path: str) -> List[Transaction]:
        transactions = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                # TODO: Extract and parse transactions
                pass
        return transactions
    
    def parse_metadata(self, file_path: str) -> Dict[str, str]:
        return {'Bank': 'YourBank'}  # TODO: Extract metadata
    
    def validate_format(self, file_path: str) -> bool:
        # Look for bank-specific markers in PDF
        with pdfplumber.open(file_path) as pdf:
            text = pdf.pages[0].extract_text()
            return 'YourBank' in text
```

### 2. Register Parser
File: `src/parsers/parser_factory.py` - Add to `PARSERS` dict:
```python
from src.parsers.yourbank_parser import YourBankParser

PARSERS = {
    'hdfc': HDFCParser,
    'icici': ICICIParser,
    'yourbank': YourBankParser,  # ← Add here
}
```

### 3. Use It
```bash
python main.py --file data/statement.pdf --bank yourbank
```

## Common Code Snippets

### Extract Transaction from Line
```python
# Match date pattern: DD/MM/YY or DD/MM/YYYY
if re.match(r'\d{2}/\d{2}/\d{2,4}', line):
    date = line[:8]  # DD/MM/YY
    # Rest of transaction parsing...
```

### Parse Amount
```python
# Handles: 1000, 1,000, 1000.00, 1,000.00
amount_str = "1,234.56"
amount = float(amount_str.replace(',', ''))  # 1234.56
```

### Extract from PDF
```python
with pdfplumber.open(file_path) as pdf:
    # Get text from all pages
    for page in pdf.pages:
        text = page.extract_text()
        lines = text.split('\n')
        # Process lines...
    
    # Get text from specific page
    first_page = pdf.pages[0].extract_text()
```

### Validate Date
```python
from datetime import datetime

date_str = "15/05/2024"
try:
    date_obj = datetime.strptime(date_str, '%d/%m/%Y')
    print(f"Valid: {date_obj}")
except ValueError:
    print(f"Invalid date: {date_str}")
```

### Create Transaction Object
```python
from src.models.transaction import Transaction

transaction = Transaction(
    date='15/05/2024',
    narration='SALARY CREDIT',
    chq_ref_no='CHQ123',
    value_dt='15/05/2024',
    withdrawal_amt='',
    deposit_amt='50000.00',
    closing_balance='125000.00'
)
```

### Regex Patterns for Banks

**Date formats:**
```python
# DD/MM/YY
r'\d{2}/\d{2}/\d{2}(?!\d)'

# DD/MM/YYYY
r'\d{2}/\d{2}/\d{4}'

# YYYY-MM-DD
r'\d{4}-\d{2}-\d{2}'
```

**Amounts:**
```python
# 1000.00 or 1,000.00
r'\d+(?:,\d{3})*\.?\d{0,2}'

# Strict: Must have decimals
r'\d+(?:,\d{3})*\.\d{2}'
```

**Account numbers:**
```python
# Usually 10-16 digits
r'\d{10,16}'

# With leading/trailing spaces
r'A/C\s*:?\s*(\d+)'
```

## Testing Your Parser

### Quick Test
```bash
python -c "from src.parsers.yourbank_parser import YourBankParser; p = YourBankParser(); print(p.validate_format('data/sample.pdf'))"
```

### Full Test
```bash
python main.py --file data/statement.pdf --bank yourbank
```

### Debug Mode
```python
import logging
logging.basicConfig(level=logging.DEBUG)
parser = YourBankParser()
transactions = parser.parse('data/statement.pdf')
```

## Troubleshooting

**ImportError: No module named...**
- Check file names and paths
- Ensure `__init__.py` exists in `src/` and `src/parsers/`

**PDF not recognized:**
- Implement `validate_format()` properly
- Check bank-specific markers in first page

**Transactions not extracted:**
- Print raw PDF text: `print(page.extract_text())`
- Check regex patterns match actual format
- Verify date format in target PDF

**Amount parsing fails:**
- PDF might use different decimal: comma vs period
- Some banks use spaces instead of commas: "1 234.56"
- Try: `amount.replace(' ', '').replace(',', '')`

## File Structure Reminder

```
BSA-Project/
├── src/
│   ├── parsers/
│   │   ├── __init__.py
│   │   ├── base_parser.py          ← Inherit from this
│   │   ├── hdfc_parser.py
│   │   ├── icici_parser.py
│   │   ├── yourbank_parser.py      ← Create this
│   │   └── parser_factory.py       ← Register here
│   └── models/
│       └── transaction.py
├── data/
├── main.py
└── requirements.txt
```

## See Also
- [Full Architecture Guide](ARCHITECTURE.md)
- [README](README.md)
- [Transaction Model](src/models/transaction.py)
- [HDFC Parser (Complete Example)](src/parsers/hdfc_parser.py)
