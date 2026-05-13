import re
import logging
from typing import List, Dict
from datetime import datetime

import pdfplumber

from src.parsers.base_parser import BaseParser
from src.models.transaction import Transaction
from src.utils.date_utils import DateUtils
from src.utils.pdf_extractor import PDFExtractor


class AxisParser(BaseParser):
    """
    Parser for Axis Bank statement PDFs.

    Supports two formats:
    1. Traditional — 'Tran Date Chq No Particulars Debit Credit Balance Init.'
       - Date format: DD-MM-YYYY
       - Narration lines appear BEFORE the date line (inverted order in PDF text)
       - Columns: date, chq_no, particulars, debit, credit, balance, init_br

    2. Web (Detailed Statement) — 'S No. Value Date Transaction Date Cheque Number
       Transaction Remarks Withdrawal Amount Deposit Amount Balance (INR)'
       - Date format: DD/MM/YYYY
       - Serial number + narration continuation lines follow the data row
    """

    # Footer/boilerplate lines on every page
    _FOOTER_MARKERS = (
        '++++ End of Statement ++++',
        'Contentsofthisstatement',
        'This is a computer generated',
        'Axis Bank Limited',
        'AXIS BANK LIMITED',
        'Note :-',
        'Note:',
        'Abbreviations used',
        'IMPS -',
        'NEFT -',
        'UPI -',
        'ECS -',
        'CLG -',
        'EDC -',
        'SETU',
        'Int.pd',
        'Int.Coll',
        'VMT-ICON',
        'AUTOSWEEP',
        'REV SWEEP',
        'SWEEP TRF',
        'CWDR',
        'PUR',
        'TIP/ SCG',
        'RATE.DIFF',
        'MMT -',
        'N chg -',
        'ONL -',
        'PAC -',
        'PAVC -',
        'PAYC -',
        'RCHG -',
        'SGB-',
        'SMO -',
        'T Chg -',
        'TOP -',
        'UCCBRN',
        'VAT / MAT',
        'VPS / IPS',
    )

    # Header rows to skip
    _HEADER_MARKERS = (
        'Tran Date',
        'S No. Value Date',
        'OPENING BALANCE',
        'CLOSING BALANCE',
        'Transaction Date from',
        'Transaction Period',
        'Advanced Search',
        'Amount from',
        'Cheque number from',
        'Transaction remarks',
        'Transaction type',
        'Transactions List',
        'DETAILED STATEMENT',
        'Search',
        '(INR ) (INR )',
    )

    def validate_format(self, file_path: str) -> bool:
        """Return True if PDF contains Axis Bank markers."""
        try:
            page_texts = PDFExtractor.extract_pages_fallback(file_path)
            text = '\n'.join(page_texts[:3])
            markers_found = sum([
                bool(re.search(r'axis\s+bank', text, re.IGNORECASE)),
                bool(re.search(r'UTIB\d{7}', text)),
                bool(re.search(r'Statement\s+of\s+(Axis\s+)?Account\s+No', text, re.IGNORECASE)),
                bool(re.search(r'Tran\s+Date\s+Chq\s+No\s+Particulars', text, re.IGNORECASE)),
                bool(re.search(r'Customer\s+ID\s*:\d+', text, re.IGNORECASE)),
            ])
            return markers_found >= 2
        except Exception:
            return False

    def parse(self, file_path: str) -> List[Transaction]:
        """Parse Axis Bank statement PDF and extract transactions."""
        try:
            page_texts = PDFExtractor.extract_pages_fallback(file_path)
            if not page_texts:
                logging.error(f"Could not extract text from {file_path}")
                return []
            full_text = '\n'.join(page_texts)
        except Exception as e:
            logging.error(f"Error reading {file_path}: {e}")
            return []

        # Detect format
        if re.search(r'S\s+No\.\s+Value\s+Date\s+Transaction\s+Date', full_text, re.IGNORECASE):
            return self._parse_web_format(page_texts)
        else:
            return self._parse_traditional_format(page_texts)

    # ------------------------------------------------------------------
    # Traditional format parser
    # Each transaction spans 1+ lines:
    #   [narration line(s)]  — appear BEFORE the date line
    #   DD-MM-YYYY  [chq_no]  [narration_cont...]  amount  balance  br_code
    #
    # The date line always ends with:  amount  balance  br_code  (last 3 tokens)
    # amount  = single debit OR credit value (not both on same line)
    # balance = running closing balance
    # br_code = 3-5 digit branch/init code (no decimal)
    # ------------------------------------------------------------------
    def _parse_traditional_format(self, page_texts: List[str]) -> List[Transaction]:
        transactions = []
        previous_balance = None

        date_re = re.compile(r'^\d{2}-\d{2}-\d{4}')
        amount_re = re.compile(r'^\d[\d,]*\.\d{2}$')
        br_code_re = re.compile(r'^\d{3,5}$')

        for page_text in page_texts:
            lines = [l.strip() for l in page_text.split('\n')]
            i = 0
            pending_narration = []  # lines before the date line

            while i < len(lines):
                line = lines[i]

                if not line:
                    i += 1
                    continue
                if self._is_footer(line) or self._is_header(line):
                    pending_narration = []
                    i += 1
                    continue

                if date_re.match(line):
                    parts = line.split()
                    date_str = DateUtils.normalize_date(parts[0])
                    rest = parts[1:]

                    # Strip trailing br_code (3-5 digit int)
                    br_code = ''
                    if rest and br_code_re.match(rest[-1]):
                        br_code = rest.pop()

                    # Last two tokens should now be: amount  balance
                    # Both must look like amounts
                    closing_balance = ''
                    first_amt = ''
                    if len(rest) >= 2 and amount_re.match(rest[-1]) and amount_re.match(rest[-2]):
                        closing_balance = rest.pop()
                        first_amt = rest.pop()
                    elif len(rest) >= 1 and amount_re.match(rest[-1]):
                        closing_balance = rest.pop()

                    # Validate closing balance
                    try:
                        current_bal = float(closing_balance.replace(',', ''))
                    except (ValueError, AttributeError):
                        pending_narration = []
                        i += 1
                        continue

                    # Remaining rest = optional chq_no + narration continuation
                    # First token is chq_no if it looks like a ref (alphanumeric, no spaces)
                    chq_no = ''
                    inline_narration = ''
                    if rest:
                        # Check if first token is a cheque/ref number
                        # (alphanumeric, not a pure word like 'Salary')
                        if re.match(r'^[A-Za-z0-9]{2,20}$', rest[0]) and not rest[0].istitle():
                            chq_no = rest[0]
                            inline_narration = ' '.join(rest[1:])
                        else:
                            inline_narration = ' '.join(rest)

                    # Build full narration: pending lines + inline continuation
                    narration_parts = pending_narration[:]
                    if inline_narration:
                        narration_parts.append(inline_narration)
                    narration = ' '.join(narration_parts).strip()
                    pending_narration = []

                    # Determine debit/credit via balance delta
                    withdrawal_amt = ''
                    deposit_amt = ''
                    if previous_balance is not None:
                        try:
                            prev_bal = float(previous_balance.replace(',', ''))
                            delta = current_bal - prev_bal
                            if delta >= 0:
                                deposit_amt = f"{delta:.2f}"
                            else:
                                withdrawal_amt = f"{-delta:.2f}"
                        except ValueError:
                            if first_amt:
                                withdrawal_amt = first_amt
                    elif first_amt:
                        # First transaction — keyword heuristic
                        keywords_credit = ['CREDIT', 'DEPOSIT', 'SALARY', 'NEFT', 'IMPS',
                                           'REFUND', 'INT.PD', 'INT.', 'SB:']
                        if any(k in narration.upper() for k in keywords_credit):
                            deposit_amt = first_amt
                        else:
                            withdrawal_amt = first_amt

                    if closing_balance:
                        transactions.append(Transaction(
                            date=date_str,
                            narration=narration,
                            chq_ref_no=chq_no,
                            value_dt=date_str,
                            withdrawal_amt=withdrawal_amt,
                            deposit_amt=deposit_amt,
                            closing_balance=closing_balance
                        ))
                        previous_balance = closing_balance
                else:
                    # Accumulate as narration for the upcoming date line
                    pending_narration.append(line)

                i += 1

        return transactions

    # ------------------------------------------------------------------
    # Web (Detailed Statement) format parser
    # Header: S No. Value Date Transaction Date Cheque Number
    #         Transaction Remarks Withdrawal Amount Deposit Amount Balance
    # Each transaction row:
    #   DD/MM/YYYY  DD/MM/YYYY  -  <remarks>  <withdrawal|0.0>  <deposit|0.0>  <balance>
    #   <serial_no>
    #   [continuation narration lines...]
    # ------------------------------------------------------------------
    def _parse_web_format(self, page_texts: List[str]) -> List[Transaction]:
        transactions = []

        # Two dates side by side (value_dt and txn_dt), then '-', then amounts
        row_re = re.compile(
            r'^(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+'  # value_dt  txn_dt
            r'(-|[\w/]+)\s+'                                     # chq_no (often '-')
            r'(.+?)\s+'                                          # remarks
            r'(\d{1,3}(?:,\d{3})*\.\d+)\s+'                     # withdrawal or deposit
            r'(\d{1,3}(?:,\d{3})*\.\d+)\s+'                     # deposit or balance
            r'(\d{1,3}(?:,\d{3})*\.\d+)$'                       # balance
        )

        for page_text in page_texts:
            lines = [l.strip() for l in page_text.split('\n')]
            i = 0
            while i < len(lines):
                line = lines[i]
                if not line or self._is_footer(line) or self._is_header(line):
                    i += 1
                    continue

                m = row_re.match(line)
                if m:
                    value_dt = DateUtils.normalize_date(m.group(1))
                    txn_dt = DateUtils.normalize_date(m.group(2))
                    chq_no = m.group(3) if m.group(3) != '-' else ''
                    narration = m.group(4).strip()
                    amt1 = m.group(5)
                    amt2 = m.group(6)
                    amt3 = m.group(7)

                    # amt1=withdrawal, amt2=deposit, amt3=balance  (0.0 means absent)
                    withdrawal_amt = amt1 if float(amt1.replace(',', '')) != 0.0 else ''
                    deposit_amt = amt2 if float(amt2.replace(',', '')) != 0.0 else ''
                    closing_balance = amt3

                    i += 1
                    # Skip serial number line (pure integer)
                    if i < len(lines) and re.match(r'^\d+$', lines[i].strip()):
                        i += 1

                    # Collect continuation narration lines
                    while i < len(lines):
                        nxt = lines[i].strip()
                        if not nxt or self._is_footer(nxt) or self._is_header(nxt):
                            break
                        # Stop if next line is a new transaction row
                        if row_re.match(nxt):
                            break
                        narration = (narration + ' ' + nxt).strip()
                        i += 1

                    transactions.append(Transaction(
                        date=txn_dt,
                        narration=narration,
                        chq_ref_no=chq_no,
                        value_dt=value_dt,
                        withdrawal_amt=withdrawal_amt,
                        deposit_amt=deposit_amt,
                        closing_balance=closing_balance
                    ))
                else:
                    i += 1

        return transactions

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------
    def parse_metadata(self, file_path: str) -> Dict[str, str]:
        """Parse account metadata from Axis Bank statement."""
        metadata = {
            'Bank': 'Axis',
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
            page_texts = PDFExtractor.extract_pages_fallback(file_path)
            if not page_texts:
                return metadata

            header_text = '\n'.join(page_texts[:2])
            lines = [l.strip() for l in header_text.split('\n') if l.strip()]

            # --- Extract address block ---
            # Address sits between the 'Joint Holder' line and the first line
            # that contains 'Customer ID'. Strip the 'Customer ID :...' suffix
            # from the last address line (city line merged by PDF renderer).
            joint_holder_idx = next(
                (i for i, l in enumerate(lines) if re.match(r'Joint\s+Holder', l, re.IGNORECASE)), None
            )
            customer_id_idx = next(
                (i for i, l in enumerate(lines) if 'Customer ID' in l), None
            )
            if joint_holder_idx is not None and customer_id_idx is not None and customer_id_idx > joint_holder_idx + 1:
                addr_lines = lines[joint_holder_idx + 1: customer_id_idx]
                # The Customer ID line has city/state prepended — strip the suffix
                city_line = re.sub(r'\s*Customer\s+ID\s*:.*', '', lines[customer_id_idx]).strip()
                if city_line:
                    addr_lines.append(city_line)
                # Also grab the pincode from the MICR line (digits before 'MICR')
                if customer_id_idx + 1 < len(lines):
                    pincode_match = re.match(r'^(\d{6})', lines[customer_id_idx + 1])
                    if pincode_match:
                        addr_lines.append(pincode_match.group(1))
                metadata['Address'] = ', '.join(addr_lines)

            for i, line in enumerate(lines):

                # Account holder — first non-empty line before 'Joint Holder'
                if not metadata['Account Holder']:
                    if i + 1 < len(lines) and lines[i + 1].startswith('Joint Holder'):
                        metadata['Account Holder'] = line

                # Joint Holder
                if not metadata['Joint Holder']:
                    jh = re.search(r'Joint\s+Holder\s*:-?\s*(.+)', line, re.IGNORECASE)
                    if jh and jh.group(1).strip() not in ('-', ''):
                        metadata['Joint Holder'] = jh.group(1).strip()

                # Account Number + period — traditional format
                # "Statement of Account No :921010033551909 for the period (From : 01-01-2024 To : 24-04-2024)"
                if not metadata['Account Number']:
                    acct = re.search(
                        r'Statement\s+of\s+(?:Axis\s+)?Account\s+No\s*:?\s*(\d+)',
                        line, re.IGNORECASE
                    )
                    if acct:
                        metadata['Account Number'] = acct.group(1)
                    # Web format: "Account Number 007501534501(INR) - MAHADEV GIRI GOSWAMI"
                    acct2 = re.search(
                        r'Account\s+Number\s+(\d+)\s*\(INR\)\s*-\s*(.+)',
                        line, re.IGNORECASE
                    )
                    if acct2:
                        metadata['Account Number'] = acct2.group(1)
                        metadata['Account Holder'] = acct2.group(2).strip()

                # Period — traditional: "(From : 01-01-2024 To : 24-04-2024)"
                if not metadata['From date'] or not metadata['To date']:
                    period = re.search(
                        r'From\s*:?\s*(\d{2}[-/]\d{2}[-/]\d{4})\s+To\s*:?\s*(\d{2}[-/]\d{2}[-/]\d{4})',
                        line, re.IGNORECASE
                    )
                    if period:
                        metadata['From date'] = DateUtils.normalize_date(period.group(1))
                        metadata['To date'] = DateUtils.normalize_date(period.group(2))

                # Period — web format: "Transaction Date from 01/09/2023 to 25/04/2024"
                if not metadata['From date'] or not metadata['To date']:
                    period2 = re.search(
                        r'Transaction\s+Date\s+from\s+(\d{2}/\d{2}/\d{4})\s+to\s+(\d{2}/\d{2}/\d{4})',
                        line, re.IGNORECASE
                    )
                    if period2:
                        metadata['From date'] = DateUtils.normalize_date(period2.group(1))
                        metadata['To date'] = DateUtils.normalize_date(period2.group(2))

                # Customer ID
                if not metadata['Customer ID']:
                    cid = re.search(r'Customer\s+ID\s*:?\s*(\d+)', line, re.IGNORECASE)
                    if cid:
                        metadata['Customer ID'] = cid.group(1)

                # IFSC code
                if not metadata['IFSC code']:
                    ifsc = re.search(r'IFSC\s+Code\s*:?\s*(UTIB\w+)', line, re.IGNORECASE)
                    if ifsc:
                        metadata['IFSC code'] = ifsc.group(1)

                # Email
                if not metadata['Email']:
                    email = re.search(r'Registered\s+Email\s+ID\s*:?\s*(\S+@\S+)', line, re.IGNORECASE)
                    if email:
                        metadata['Email'] = email.group(1)

                # Mobile
                if not metadata['Mobile']:
                    mob = re.search(r'Registered\s+Mobile\s+No\s*:?\s*(X+\d+)', line, re.IGNORECASE)
                    if mob:
                        metadata['Mobile'] = mob.group(1)

                # PAN
                if not metadata['PAN']:
                    pan = re.search(r'PAN\s*:?\s*([A-Z]{5}\d{4}[A-Z])', line)
                    if pan:
                        metadata['PAN'] = pan.group(1)

                # Scheme
                if not metadata['Scheme']:
                    scheme = re.search(r'Scheme\s*:?\s*(.+)', line, re.IGNORECASE)
                    if scheme:
                        metadata['Scheme'] = scheme.group(1).strip()

        except Exception as e:
            logging.error(f"Error extracting Axis metadata: {e}")

        return metadata

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _is_footer(self, line: str) -> bool:
        return any(line.startswith(m) for m in self._FOOTER_MARKERS)

    def _is_header(self, line: str) -> bool:
        return any(line.startswith(m) for m in self._HEADER_MARKERS)
