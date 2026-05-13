import pdfplumber
import re
import logging
from datetime import datetime
from typing import List, Dict
from src.parsers.base_parser import BaseParser
from src.models.transaction import Transaction
from src.utils.pdf_extractor import PDFExtractor
from src.utils.date_utils import DateUtils

logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')


class ICICIParser(BaseParser):
    """
    Parser for ICICI Bank statement PDFs.

    Supports two formats:
    1. Traditional format: DATE MODE** PARTICULARS DEPOSITS WITHDRAWALS BALANCE
    2. Web statement format: S No. Value Date Transaction Date Cheque Number Transaction Remarks Withdrawal Amount Deposit Amount Balance
    """

    def parse(self, file_path: str) -> List[Transaction]:
        """
        Parse ICICI statement PDF and extract transactions.

        Auto-detects format and uses appropriate parsing method.
        """
        try:
            # Use robust PDF extraction with fallback
            page_texts = PDFExtractor.extract_pages_fallback(file_path)
            if not page_texts:
                logging.error(f"Could not extract text from {file_path}")
                return []

            # Detect format from first page
            all_text = ' '.join(page_texts)
            if 'S No. Value Date Transaction Date' in all_text:
                # Web statement format
                return self._parse_web_format(page_texts)
            elif 'DATE MODE** PARTICULARS' in all_text:
                # Traditional format
                return self._parse_traditional_format(page_texts)
            else:
                logging.error(f"Unrecognized ICICI format in {file_path}")
                return []

        except Exception as e:
            logging.error(f"Error parsing ICICI statement: {str(e)}")
            return []

    def _parse_traditional_format(self, page_texts: List[str]) -> List[Transaction]:
        """
        Parse traditional ICICI format: DATE MODE** PARTICULARS DEPOSITS WITHDRAWALS BALANCE
        """
        transactions = []
        previous_balance = None

        for page_text in page_texts:
            if not page_text:
                continue

            lines = page_text.split('\n')
            i = 0

            while i < len(lines):
                line = lines[i].strip()

                # Find transaction header to start parsing
                if 'DATE MODE** PARTICULARS' in line:
                    i += 1  # Move to next line after header
                    continue

                # Check if this is a transaction line starting with date
                if re.match(r'\d{2}-\d{2}-\d{4}', line):
                    # Skip B/F (brought forward) entries - these are opening balances
                    if 'B/F' in line:
                        i += 1
                        continue

                    # Start collecting transaction data
                    transaction_lines = [line]
                    i += 1

                    # Collect continuation lines until next date or header
                    while i < len(lines):
                        next_line = lines[i].strip()
                        if re.match(r'\d{2}-\d{2}-\d{4}', next_line) or 'DATE MODE** PARTICULARS' in next_line:
                            # Next transaction starts, stop here
                            break
                        if next_line:  # Only add non-empty lines
                            transaction_lines.append(next_line)
                        i += 1

                    # Parse the complete transaction
                    result = self._parse_transaction_block_traditional(transaction_lines)
                    if result:
                        transaction, extracted_amount = result

                        # Apply balance-based debit/credit detection
                        if previous_balance is not None and transaction.closing_balance:
                            try:
                                curr_bal = float(transaction.closing_balance.replace(',', ''))
                                prev_bal = float(previous_balance.replace(',', ''))

                                # Skip duplicate artifacts
                                if abs(curr_bal - prev_bal) < 0.01:
                                    logging.debug(f"Skipping duplicate artifact for {transaction.date}: balance unchanged.")
                                    continue

                                # Calculate the transaction amount from balance difference
                                amount_diff = curr_bal - prev_bal

                                if amount_diff > 0:
                                    # Balance increased = deposit
                                    transaction.deposit_amt = f"{amount_diff:.2f}"
                                    transaction.withdrawal_amt = ''
                                else:
                                    # Balance decreased = withdrawal
                                    transaction.withdrawal_amt = f"{-amount_diff:.2f}"
                                    transaction.deposit_amt = ''

                                # Validation: Check if calculated amount matches extracted amount
                                if extracted_amount:
                                    extracted_amt = float(extracted_amount.replace(',', ''))
                                    if abs(abs(amount_diff) - extracted_amt) > 0.01:
                                        logging.warning(f"Amount mismatch for {transaction.date}: calculated {abs(amount_diff):.2f}, extracted {extracted_amt:.2f}")

                            except ValueError:
                                logging.warning(f"Invalid balance format for transaction on {transaction.date}.")

                        # Validation: Ensure chronological order
                        if transactions and transaction.date:
                            try:
                                current_dt = datetime.strptime(transaction.date, '%d-%m-%Y')
                                prev_dt = datetime.strptime(transactions[-1].date, '%d-%m-%Y')
                                if current_dt < prev_dt:
                                    logging.warning(f"Transaction date {transaction.date} is not in chronological order.")
                            except ValueError:
                                logging.warning(f"Invalid date format for {transaction.date} or {transactions[-1].date}.")

                        transactions.append(transaction)
                        previous_balance = transaction.closing_balance
                else:
                    i += 1

        logging.info(f"Parsed {len(transactions)} transactions from ICICI traditional format")
        return transactions

    def _parse_web_format(self, page_texts: List[str]) -> List[Transaction]:
        """
        Parse web statement format: S No. Value Date Transaction Date Cheque Number
        Transaction Remarks Withdrawal Amount Deposit Amount Balance
        """
        transactions = []

        # Collect all lines from all pages after the header is found
        all_lines = []
        header_found = False
        for page_text in page_texts:
            if not page_text:
                continue
            for line in page_text.split('\n'):
                line = line.strip()
                if not line:
                    continue
                # Detect and skip header line (only needs to appear once)
                if 'Value Date Transaction Date' in line:
                    header_found = True
                    continue
                # Skip lines before header (metadata)
                if not header_found:
                    continue
                all_lines.append(line)

        if not all_lines:
            return transactions

        # Phase 1: Clean lines - strip serial numbers and skip artifacts
        cleaned_lines = []
        for line in all_lines:
            # Skip lines that are purely digits (serial numbers or artifacts)
            if re.match(r'^\d+$', line):
                continue
            # Skip sub-header lines like "(INR ) (INR )"
            if re.match(r'^[\(\)INR\s]+$', line, re.IGNORECASE):
                continue

            # Strip leading serial number if followed by a date
            sno_date_match = re.match(r'^\d+\s+(\d{2}/\d{2}/\d{4})', line)
            if sno_date_match:
                cleaned_lines.append(line[sno_date_match.start(1):])
                continue

            # Line starts directly with a date
            if re.match(r'\d{2}/\d{2}/\d{4}', line):
                cleaned_lines.append(line)
                continue

            # Continuation line - strip leading serial number + space if present
            sno_cont_match = re.match(r'^(\d+)\s+(\D)', line)
            if sno_cont_match:
                cleaned_lines.append(line[sno_cont_match.start(2):])
            else:
                cleaned_lines.append(line)

        # Phase 2: Group lines into transaction blocks
        # Each block starts with a line beginning with DD/MM/YYYY
        blocks = []
        current_block = None

        for line in cleaned_lines:
            if re.match(r'\d{2}/\d{2}/\d{4}', line):
                if current_block is not None:
                    blocks.append(current_block)
                current_block = [line]
            else:
                if current_block is not None:
                    current_block.append(line)

        if current_block is not None:
            blocks.append(current_block)

        # Phase 3: Parse each transaction block
        for block in blocks:
            main_line = block[0]
            continuation = ' '.join(block[1:]) if len(block) > 1 else ''
            transaction = self._parse_transaction_line_web(main_line, continuation)
            if transaction:
                transactions.append(transaction)
            else:
                logging.debug(f"Failed to parse web transaction: {main_line}")

        logging.info(f"Parsed {len(transactions)} transactions from ICICI web format")
        return transactions

    def _parse_transaction_line_web(self, line: str, continuation: str = '') -> Transaction:
        """
        Parse a single transaction line from web format.

        Format: Value Date Transaction Date - Transaction Remarks Withdrawal Amount Deposit Amount Balance
        Example: 01/07/2023 01/07/2023 - APY_501209797952_Rs.1318 fr 1318.00 0.0 100716.14
        """
        try:
            # Match 3 amounts at the end of the line: WITHDRAWAL DEPOSIT BALANCE
            # Amounts can be negative (e.g. balance), may have commas, variable decimal places
            amount_end_pattern = r'(-?\d+(?:,\d{3})*\.\d+)\s+(-?\d+(?:,\d{3})*\.\d+)\s+(-?\d+(?:,\d{3})*\.\d+)\s*$'
            match = re.search(amount_end_pattern, line)

            if not match:
                return None

            withdrawal_raw = match.group(1)
            deposit_raw = match.group(2)
            balance_raw = match.group(3)

            # Extract text before the amounts
            text_part = line[:match.start()].strip()

            # Extract dates from text
            dates = re.findall(r'\d{2}/\d{2}/\d{4}', text_part)
            if len(dates) < 2:
                return None

            value_date = dates[0]
            transaction_date = dates[1]

            # Extract remarks: remove dates and leading separator
            remarks_text = re.sub(r'\d{2}/\d{2}/\d{4}', '', text_part).strip()
            remarks_text = re.sub(r'^-\s*', '', remarks_text).strip()

            # Append continuation narration
            if continuation:
                remarks_text = (remarks_text + ' ' + continuation).strip()

            # Clean extra whitespace
            remarks_text = re.sub(r'\s+', ' ', remarks_text).strip()

            # Normalize dates
            transaction_date = DateUtils.normalize_date(transaction_date)
            value_date = DateUtils.normalize_date(value_date)

            # Clean amounts
            withdrawal_amt = withdrawal_raw.replace(',', '')
            deposit_amt = deposit_raw.replace(',', '')
            balance = balance_raw.replace(',', '')

            # Mark zero amounts as empty (no withdrawal/deposit)
            try:
                if float(withdrawal_amt) == 0:
                    withdrawal_amt = ''
            except ValueError:
                pass
            try:
                if float(deposit_amt) == 0:
                    deposit_amt = ''
            except ValueError:
                pass

            # Extract cheque/reference number from remarks
            chq_ref_no = ''
            ref_match = re.search(r'/(\d{5,})/', remarks_text)
            if ref_match:
                chq_ref_no = ref_match.group(1)

            return Transaction(
                date=transaction_date,
                narration=remarks_text,
                chq_ref_no=chq_ref_no,
                value_dt=value_date,
                withdrawal_amt=withdrawal_amt,
                deposit_amt=deposit_amt,
                closing_balance=balance
            )

        except Exception as e:
            logging.warning(f"Error parsing web format transaction line: {line} - {str(e)}")
            return None

    def _parse_transaction_block_traditional(self, lines: List[str]) -> Transaction:
        """
        Parse a complete transaction block that may span multiple lines.

        Expected format:
        DD-MM-YYYY MODE/.../PARTICULARS AMOUNT BALANCE
        [continuation lines for particulars]
        """
        if not lines:
            return None

        # First line contains the main transaction data
        first_line = lines[0]

        # Extract date (first part)
        date_match = re.match(r'(\d{2}-\d{2}-\d{4})', first_line)
        if not date_match:
            return None

        date = date_match.group(1)
        # Normalize date to ensure consistent dd-mm-yyyy format
        date = DateUtils.normalize_date(date)
        remaining = first_line[len(date):].strip()

        # Find all amounts in the transaction (last one is balance)
        amounts = re.findall(r'\d{1,3}(?:,\d{3})*\.\d{2}', first_line)

        if not amounts:
            logging.warning(f"No amounts found in transaction line: {first_line}")
            return None

        # Last amount is always the balance
        closing_balance = amounts[-1]

        # Transaction amount is the second-to-last amount (if exists)
        transaction_amount = amounts[-2] if len(amounts) >= 2 else ''

        # Extract mode and particulars
        # Split remaining text into parts
        parts = remaining.split()

        # Find where amounts start to separate text from numbers
        amount_start_idx = -1
        for j, part in enumerate(parts):
            if re.match(r'\d{1,3}(?:,\d{3})*\.\d{2}', part):
                amount_start_idx = j
                break

        if amount_start_idx == -1:
            # No amounts found in parts, this shouldn't happen
            return None

        # Text parts are everything before the first amount
        text_parts = parts[:amount_start_idx]

        # Join all text parts and then parse mode/particulars
        full_text = ' '.join(text_parts)

        # Mode is the first part before slash
        if '/' in full_text:
            mode_part, particulars = full_text.split('/', 1)
            mode = mode_part.strip()
            particulars = particulars.strip()
        else:
            # No slash, assume first word is mode
            words = full_text.split()
            mode = words[0] if words else ''
            particulars = ' '.join(words[1:]) if len(words) > 1 else ''

        # Add continuation lines to particulars
        if len(lines) > 1:
            continuation = ' '.join(lines[1:]).strip()
            if continuation:
                particulars += ' ' + continuation

        # Clean up particulars (remove extra spaces)
        particulars = re.sub(r'\s+', ' ', particulars).strip()

        # Determine debit/credit based on mode and balance change
        withdrawal_amt = ''
        deposit_amt = ''

        # Note: Debit/credit determination will be done in main parse method using balance changes
        # For now, just store the transaction amount for validation

        # Use current date as value_dt since ICICI doesn't have separate value date
        value_dt = date

        # For ICICI, chq_ref_no might be part of mode or empty
        chq_ref_no = ''
        if '/' in mode:
            # Extract reference number from mode like "CRED/6305480595@axis"
            mode_parts = mode.split('/')
            if len(mode_parts) > 1:
                chq_ref_no = mode_parts[1].split('@')[0]  # Take the number part

        return Transaction(
            date=date,
            narration=particulars,
            chq_ref_no=chq_ref_no,
            value_dt=value_dt,
            withdrawal_amt=withdrawal_amt,
            deposit_amt=deposit_amt,
            closing_balance=closing_balance
        ), transaction_amount

    def parse_metadata(self, file_path: str) -> Dict[str, str]:
        """
        Parse account metadata from ICICI statement.
        
        ICICI metadata locations:
        - Account holder name and number in header
        - Statement period dates
        - Branch information
        - Contact details
        
        Supports both web format and traditional format.
        """
        metadata = {
            'Bank': 'ICICI',
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
            'To date': '',
            'Opening Balance': '',
            'Closing Balance': '',
            'Debit counts': '',
            'Credit counts': '',
            'Debit amount': '',
            'Credit amount': ''
        }
        
        try:
            # Use robust PDF extraction with fallback
            page_texts = PDFExtractor.extract_pages_fallback(file_path)
            if not page_texts:
                logging.error(f"Could not extract text from {file_path} for metadata")
                return metadata
            
            # Combine first few pages for metadata search
            header_text = '\n'.join(page_texts[:3])
            lines = header_text.split('\n')
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # --- Account Number ---
                if not metadata['Account Number']:
                    # Web format: "Account Number 036001534567(INR) - RAJKUMAR GOVIND"
                    acct_match = re.search(r'Account\s+Number\s+(\d+)\s*\(INR\)\s*-\s*(.+)', line, re.IGNORECASE)
                    if acct_match:
                        metadata['Account Number'] = acct_match.group(1)
                        metadata['Account Holder'] = acct_match.group(2).strip()
                    else:
                        # Traditional format: "Account Number: 036001534567" or "Account No.: ..."
                        acct_match = re.search(r'Account\s+(?:Number|No\.?)\s*:?\s*(\d{6,})', line, re.IGNORECASE)
                        if not acct_match:
                            acct_match = re.search(r'Savings\s+Account\s+(?:Number|No\.?)\s*:?\s*(\d{6,})', line, re.IGNORECASE)
                        if acct_match:
                            metadata['Account Number'] = acct_match.group(1)
                
                # --- Account Holder (additional patterns) ---
                if not metadata['Account Holder']:
                    # "Transactions List - RAJKUMAR GOVIND - 036001534567"
                    name_match = re.search(r'Transactions\s+List\s*-\s*(.+?)\s*-\s*\d+', line, re.IGNORECASE)
                    if name_match:
                        metadata['Account Holder'] = name_match.group(1).strip()
                    else:
                        # Traditional: "MR.KARRAVULA PRAVEEN KUMAR Your Base Branch: ..."
                        name_match = re.search(r'^((?:MR|MRS|MS|MISS|DR)\.?\s*.+?)\s+Your\s+Base\s+Branch', line, re.IGNORECASE)
                        if name_match:
                            metadata['Account Holder'] = name_match.group(1).strip()
                
                # --- Statement Period ---
                if not metadata['From date'] or not metadata['To date']:
                    # Web format: "Transaction Date from 01/07/2023 to 08/10/2023"
                    period_match = re.search(
                        r'(?:Transaction\s+Date|Date)\s+from\s+(\d{2}/\d{2}/\d{4})\s+to\s+(\d{2}/\d{2}/\d{4})',
                        line, re.IGNORECASE
                    )
                    if period_match:
                        metadata['From date'] = DateUtils.normalize_date(period_match.group(1))
                        metadata['To date'] = DateUtils.normalize_date(period_match.group(2))
                    else:
                        # Traditional: "for the period from DD-MM-YYYY to DD-MM-YYYY"
                        period_match = re.search(
                            r'for\s+the\s+period\s+from\s+(\d{2}[-/]\d{2}[-/]\d{4})\s+to\s+(\d{2}[-/]\d{2}[-/]\d{4})',
                            line, re.IGNORECASE
                        )
                        if period_match:
                            metadata['From date'] = DateUtils.normalize_date(period_match.group(1))
                            metadata['To date'] = DateUtils.normalize_date(period_match.group(2))
                    
                    # Traditional with English month names: "for the period August 31, 2023 - February 08, 2024"
                    if not metadata['From date'] or not metadata['To date']:
                        period_match = re.search(
                            r'for\s+the\s+period\s+(\w+\s+\d{1,2},?\s+\d{4})\s*[-–]\s*(\w+\s+\d{1,2},?\s+\d{4})',
                            line, re.IGNORECASE
                        )
                        if period_match:
                            try:
                                from_str = period_match.group(1).replace(',', '')
                                to_str = period_match.group(2).replace(',', '')
                                from_dt = datetime.strptime(from_str, '%B %d %Y')
                                to_dt = datetime.strptime(to_str, '%B %d %Y')
                                metadata['From date'] = from_dt.strftime('%d-%m-%Y')
                                metadata['To date'] = to_dt.strftime('%d-%m-%Y')
                            except ValueError:
                                pass
                
                # --- Branch ---
                if not metadata['Branch']:
                    branch_match = re.search(r'(?:Your\s+Base\s+)?Branch\s*:\s*(.+?)(?:\s*IFSC|$)', line, re.IGNORECASE)
                    if branch_match:
                        metadata['Branch'] = branch_match.group(1).strip()
                
                # --- Email ---
                if not metadata['Email']:
                    email_match = re.search(r'Email\s*:?\s*([^\s]+@[^\s]+\.[^\s]+)', line, re.IGNORECASE)
                    if email_match:
                        metadata['Email'] = email_match.group(1)
                
                # --- Mobile ---
                if not metadata['Mobile']:
                    mobile_match = re.search(r'Mobile\s*:?\s*(\d{10,})', line, re.IGNORECASE)
                    if mobile_match:
                        metadata['Mobile'] = mobile_match.group(1)
        
        except Exception as e:
            logging.error(f"Error extracting ICICI metadata: {str(e)}")
        
        return metadata

    def validate_format(self, file_path: str) -> bool:
        """
        Check if PDF is in ICICI format by looking for ICICI-specific markers.
        
        Look for strings like:
        - "ICICI Bank"
        - "Statement of Transactions in Savings Account"
        - "DATE MODE** PARTICULARS"
        - ICICI-specific header/footer patterns
        """
        try:
            # Use robust PDF extraction with fallback
            page_texts = PDFExtractor.extract_pages_fallback(file_path)
            if not page_texts:
                return False
            
            # Check all pages for ICICI markers
            all_text = ' '.join(page_texts)
            
            # Check for web format (ICICI online banking statement)
            if 'S No. Value Date Transaction Date' in all_text:
                return True
            
            # Check for traditional format markers (need at least 2)
            icici_markers = [
                'ICICI Bank', 
                'Statement of Transactions in Savings Account',
                'DATE MODE** PARTICULARS',
                'IFSC Code'
            ]
            found_markers = sum(1 for marker in icici_markers if marker in all_text)
            return found_markers >= 2
        except Exception:
            return False
