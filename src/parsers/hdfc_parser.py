import pdfplumber
import re
import logging
from datetime import datetime
from typing import List, Dict
from src.parsers.base_parser import BaseParser
from src.models.transaction import Transaction
from src.utils.date_utils import DateUtils

# Set up logging for validation warnings
logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')


class HDFCParser(BaseParser):
    """
    Parser for HDFC Bank statement PDFs.
    
    Extracts transactions with 7-column format:
    Date, Narration, Chq/Ref No., Value Date, Withdrawal, Deposit, Closing Balance
    """
    
    # Footer/boilerplate lines that appear at the bottom of every page
    _FOOTER_MARKERS = (
        'HDFCBANKLIMITED',
        '*Closingbalance',
        'Contentsofthisstatement',
        'thisstatement.',
        'StateaccountbranchGSTN',
        'HDFCBankGSTINnumber',
        'RegisteredOfficeAddress',
        'PageNo.:',
        'STATEMENTSUMMARY',
        'OpeningBalance',
        'GeneratedOn:',
        'Thisisacomputergenerated',
        'notrequiresignature.',
    )

    def parse(self, file_path: str) -> List[Transaction]:
        """Parse HDFC statement PDF and extract transactions."""
        transactions = []
        previous_balance = None
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ''
                lines = text.split('\n')
                i = 0
                while i < len(lines):
                    line = lines[i].strip()
                    # Skip page footer/boilerplate lines
                    if any(line.startswith(marker) for marker in self._FOOTER_MARKERS):
                        i += 1
                        continue
                    if re.match(r'\d{2}/\d{2}/\d{2}', line):
                        # Start of transaction
                        date = line[:8]
                        # Normalize date to dd-mm-yyyy format
                        date = DateUtils.normalize_date(date)
                        main_line = line[8:].strip()
                        i += 1
                        # Collect continuation lines separately until next date
                        continuation_parts = []
                        footer_reached = False
                        while i < len(lines) and not re.match(r'\d{2}/\d{2}/\d{2}', lines[i].strip()):
                            stripped = lines[i].strip()
                            if any(stripped.startswith(marker) for marker in self._FOOTER_MARKERS):
                                footer_reached = True
                            if stripped and not footer_reached:
                                continuation_parts.append(stripped)
                            i += 1
                        # Parse the main line only for structured fields
                        parts = main_line.split()
                        if len(parts) >= 4:
                            # Find the value_dt (date)
                            value_dt_idx = None
                            for j, p in enumerate(parts):
                                if re.match(r'\d{2}/\d{2}/\d{2}', p):
                                    value_dt_idx = j
                                    break
                            if value_dt_idx is not None and value_dt_idx > 0:
                                value_dt = parts[value_dt_idx]
                                # Normalize value date to dd-mm-yyyy format
                                value_dt = DateUtils.normalize_date(value_dt)
                                chq_ref_no = parts[value_dt_idx - 1]
                                narration = ' '.join(parts[:value_dt_idx - 1])
                                # Append continuation lines to narration
                                if continuation_parts:
                                    narration = (narration + ' ' + ' '.join(continuation_parts)).strip()
                                # Find amounts after value_dt
                                remaining = parts[value_dt_idx + 1:]
                                numbers = [p for p in remaining if re.match(r'\d+,\d+\.\d+|\d+\.\d+', p)]
                                if len(numbers) >= 2:
                                    first_amt = numbers[0]
                                    closing_balance = numbers[1]
                                    
                                    # Validation 1: Ensure closing_balance is a valid number
                                    try:
                                        current_bal = float(closing_balance.replace(',', ''))
                                    except ValueError:
                                        logging.warning(f"Invalid closing balance '{closing_balance}' for transaction on {date}. Skipping.")
                                        continue
                                    
                                    # Validation 2: Check for negative balances if unexpected (assuming savings account)
                                    if current_bal < 0:
                                        logging.warning(f"Negative closing balance {current_bal} detected for transaction on {date}.")
                                    
                                    # Balance-based logic with validation
                                    if previous_balance is not None:
                                        try:
                                            prev_bal = float(previous_balance.replace(',', ''))
                                        except ValueError:
                                            logging.warning(f"Invalid previous balance '{previous_balance}'. Using keyword-based for {date}.")
                                            prev_bal = None
                                        
                                        if prev_bal is not None:
                                            # Skip duplicate artifacts when the closing balance repeats
                                            if abs(current_bal - prev_bal) < 0.01:
                                                logging.debug(f"Skipping duplicate artifact for {date}: closing balance repeats previous balance {previous_balance}.")
                                                continue
                                            
                                            amount = current_bal - prev_bal
                                            if amount > 0:
                                                deposit_amt = f"{amount:.2f}"
                                                withdrawal_amt = ''
                                            else:
                                                withdrawal_amt = f"{-amount:.2f}"
                                                deposit_amt = ''
                                            
                                            # Validation 3: Cross-check calculated amount with extracted first_amt
                                            calculated_amt = abs(amount)
                                            extracted_amt = float(first_amt.replace(',', ''))
                                            if abs(calculated_amt - extracted_amt) > 0.01:  # Allow small floating point differences
                                                logging.warning(f"Amount mismatch for {date}: calculated {calculated_amt:.2f}, extracted {extracted_amt:.2f}. Possible tampering.")
                                        else:
                                            # Fallback to keyword-based
                                            if any(word in narration.upper() for word in ['DEPOSIT', 'CREDIT', 'RECEIVED', 'TRANSFER IN']):
                                                withdrawal_amt = ''
                                                deposit_amt = first_amt
                                            else:
                                                withdrawal_amt = first_amt
                                                deposit_amt = ''
                                    else:
                                        # For first transaction, use keyword-based
                                        if any(word in narration.upper() for word in ['DEPOSIT', 'CREDIT', 'RECEIVED', 'TRANSFER IN']):
                                            withdrawal_amt = ''
                                            deposit_amt = first_amt
                                        else:
                                            withdrawal_amt = first_amt
                                            deposit_amt = ''
                                    
                                    # Validation 4: Ensure dates are in chronological order (convert to datetime for proper comparison)
                                    if transactions:
                                        try:
                                            current_dt = datetime.strptime(date, '%d-%m-%Y')
                                            prev_dt = datetime.strptime(transactions[-1].date, '%d-%m-%Y')
                                            if current_dt < prev_dt:
                                                logging.warning(f"Transaction date {date} is not in chronological order.")
                                        except ValueError:
                                            logging.warning(f"Invalid date format for {date} or {transactions[-1].date}.")
                                    
                                    transactions.append(Transaction(
                                        date=date,
                                        narration=narration,
                                        chq_ref_no=chq_ref_no,
                                        value_dt=value_dt,
                                        withdrawal_amt=withdrawal_amt,
                                        deposit_amt=deposit_amt,
                                        closing_balance=closing_balance
                                    ))
                                    previous_balance = closing_balance
                    else:
                        i += 1
        return transactions

    def parse_metadata(self, file_path: str) -> Dict[str, str]:
        """Parse account metadata from HDFC statement header and summary."""
        with pdfplumber.open(file_path) as pdf:
            first_page_text = pdf.pages[0].extract_text() or ''
            last_page_text = pdf.pages[-1].extract_text() or ''

        metadata = self._extract_header_metadata(first_page_text)
        summary = self._extract_statement_summary(last_page_text)
        metadata.update(summary)
        return metadata

    def _extract_header_metadata(self, text: str) -> Dict[str, str]:
        """Extract metadata from the header section of the statement."""
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        data = {
            'Bank': 'HDFC',
            'Account Holder': '',
            'Account Number': '',
            'Address': '',
            'Joint Holder': '',
            'Account Status': '',
            'Branch': '',
            'Email': '',
            'Mobile': '',
            'IFSC code': '',
            'PAN': '',
            'Customer ID': '',
            'Scheme': '',
            'A/C open date': '',
            'From date': '',
            'To date': ''
        }

        address_start = next((i for i, l in enumerate(lines) if l.startswith('Address')), None)
        city_index = next((i for i, l in enumerate(lines) if l.startswith('City')), None)
        if address_start is not None and city_index is not None and city_index > address_start:
            address_lines = [lines[address_start].split(':', 1)[1].strip()]
            address_lines += [lines[j] for j in range(address_start + 1, city_index)]
            data['Address'] = ' '.join(address_lines).replace(' ,', ',')

        if city_index is not None and city_index + 1 < len(lines):
            data['Account Holder'] = lines[city_index + 1]

        joint_match = re.search(r'JOINTHOLDERS:\s*(.*?)\s*AccountStatus\s*:\s*(\S+)', text)
        if joint_match:
            data['Joint Holder'] = joint_match.group(1).strip()
            data['Account Status'] = joint_match.group(2).strip()
        else:
            account_status_match = re.search(r'AccountStatus\s*:\s*(\S+)', text)
            if account_status_match:
                data['Account Status'] = account_status_match.group(1).strip()

        email_match = re.search(r'Email\s*:\s*(\S+)', text)
        if email_match:
            data['Email'] = email_match.group(1).strip()

        ifsc_match = re.search(r'RTGS/NEFTIFSC\s*:\s*(\S+)', text)
        if ifsc_match:
            data['IFSC code'] = ifsc_match.group(1).strip()

        acct_match = re.search(r'AccountNo\s*:\s*(\d+)', text)
        if acct_match:
            data['Account Number'] = acct_match.group(1).strip()

        mobile_match = re.search(r'Phone(?:no\.?|\s+no\.?)\s*:\s*(\S+)', text, re.IGNORECASE)
        if mobile_match:
            data['Mobile'] = mobile_match.group(1).strip()

        branch_match = re.search(r'AccountBranch\s*:\s*(.+)', text)
        if branch_match:
            data['Branch'] = branch_match.group(1).strip()

        account_open_match = re.search(r'A/COpenDate\s*:\s*(\d{2}/\d{2}/\d{4})', text)
        if account_open_match:
            data['A/C open date'] = account_open_match.group(1).strip()

        period_match = re.search(r'From\s*:\s*(\d{2}/\d{2}/\d{4})\s*To\s*:\s*(\d{2}/\d{2}/\d{4})', text)
        if period_match:
            data['From date'] = period_match.group(1).strip()
            data['To date'] = period_match.group(2).strip()

        return data

    def _extract_statement_summary(self, text: str) -> Dict[str, str]:
        """Extract statement summary from the last page."""
        data = {
            'Opening Balance': '',
            'Debit counts': '',
            'Credit counts': '',
            'Debit amount': '',
            'Credit amount': '',
            'Closing Balance': ''
        }
        summary_start = re.search(r'STATEMENTSUMMARY', text)
        if summary_start:
            lines = [line.strip() for line in text[summary_start.end():].split('\n') if line.strip()]
            header_index = next((i for i, line in enumerate(lines) if 'OpeningBalance' in line and 'ClosingBal' in line), None)
            if header_index is not None:
                if header_index + 1 < len(lines):
                    header_line = lines[header_index]
                    data_line = lines[header_index + 1]
                    
                    opening_match = re.search(r'(\d+,\d+\.\d+|\d+\.\d+)', data_line)
                    closing_match = re.search(r'(\d+,\d+\.\d+|\d+\.\d+)(?!.*\d+,\d+\.\d+)', data_line)
                    
                    if opening_match:
                        data['Opening Balance'] = opening_match.group(1)
                    if closing_match:
                        data['Closing Balance'] = closing_match.group(1)
            
            debits_match = re.search(r'DebitAdvices:(\d+)', text)
            credits_match = re.search(r'CreditAdvices:(\d+)', text)
            
            if debits_match:
                data['Debit counts'] = debits_match.group(1)
            if credits_match:
                data['Credit counts'] = credits_match.group(1)
            
            debit_amt_match = re.search(r'DebitAmount\s*(?:Dr\.)?:?\s*(\d+,\d+\.\d+|\d+\.\d+)', text)
            credit_amt_match = re.search(r'CreditAmount\s*(?:Cr\.)?:?\s*(\d+,\d+\.\d+|\d+\.\d+)', text)
            
            if debit_amt_match:
                data['Debit amount'] = debit_amt_match.group(1)
            if credit_amt_match:
                data['Credit amount'] = credit_amt_match.group(1)
        
        return data
    
    def validate_format(self, file_path: str) -> bool:
        """Check if PDF is in HDFC format by looking for HDFC-specific markers."""
        try:
            with pdfplumber.open(file_path) as pdf:
                first_page_text = pdf.pages[0].extract_text()
                # Look for HDFC-specific markers
                hdfc_markers = ['HDFC Bank', 'RTGS/NEFTIFSC', 'AccountStatus']
                found_markers = sum(1 for marker in hdfc_markers if marker in first_page_text)
                return found_markers >= 2
        except Exception:
            return False
