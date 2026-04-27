import pdfplumber
import re

# Examine ICICI statement format in detail
pdf_path = 'data/icici/icici_santhosh.pdf'
with pdfplumber.open(pdf_path) as pdf:
    first_page = pdf.pages[0].extract_text()
    lines = first_page.split('\n')

    print('=== ICICI TRANSACTION PATTERN ANALYSIS ===')

    # Find transaction section
    transaction_start = None
    for i, line in enumerate(lines):
        if 'DATE MODE** PARTICULARS' in line:
            transaction_start = i + 1
            break

    if transaction_start:
        print('\nFirst 10 transaction lines:')
        for i in range(transaction_start, min(transaction_start + 10, len(lines))):
            line = lines[i].strip()
            if line:
                print(f'{i}: "{line}"')

        print('\nAnalyzing transaction patterns:')
        for i in range(transaction_start, min(transaction_start + 20, len(lines))):
            line = lines[i].strip()
            if not line:
                continue

            # Check if line starts with date
            if re.match(r'\d{2}-\d{2}-\d{4}', line):
                parts = line.split()
                print(f'\nDate line: {line}')
                print(f'  Parts count: {len(parts)}')
                if len(parts) >= 3:
                    date = parts[0]
                    mode = parts[1] if len(parts) > 1 else ''
                    # Find amounts (numbers with decimals)
                    amounts = re.findall(r'\d{1,3}(?:,\d{3})*\.\d{2}', line)
                    print(f'  Date: {date}, Mode: {mode}, Amounts found: {amounts}')

                    # Check if this is a B/F (brought forward) entry
                    if 'B/F' in line:
                        print('  -> B/F entry (opening balance)')
                    elif len(amounts) >= 1:
                        balance = amounts[-1]  # Last amount is usually balance
                        if len(amounts) == 2:
                            # Has deposit or withdrawal
                            if amounts[0] != balance:
                                print(f'  -> Transaction with amount {amounts[0]}, balance {balance}')
                            else:
                                print(f'  -> Balance only: {balance}')
                        else:
                            print(f'  -> Balance: {balance}')
