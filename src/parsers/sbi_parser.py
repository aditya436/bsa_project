import re
from typing import List, Dict, Tuple, Optional
from src.parsers.base_parser import BaseParser
from src.models.transaction import Transaction
from src.utils.date_utils import DateUtils
from src.utils.pdf_extractor import PDFExtractor

# ---------------------------------------------------------------------------
# SBI Bank Statement Parser
#
# Supports two formats:
#   Format A – Traditional SBI statement (samples 2-6)
#       Header:  Account Name, Account Number, IFS Code, Branch, CIF No. …
#       Columns: Txn Date  Value Date  Description  Ref No./Cheque No.  Debit  Credit  Balance
#       Date:    "1 Sep 2023"  or  "10 Oct\n2023" (wrapped on next line)
#
#   Format B – SBI Online/Web statement (sample 1)
#       Header:  "S No. Value Date Transaction Date Cheque Number …"
#       Columns: DD/MM/YYYY  DD/MM/YYYY  -  <remarks>  <withdrawal>  <deposit>  <balance>
#       (Identical layout to Axis web format)
# ---------------------------------------------------------------------------


class SBIParser(BaseParser):
    """Parser for State Bank of India (SBI) account statements."""

    # ------------------------------------------------------------------
    # Format detection markers
    # ------------------------------------------------------------------
    _TRAD_MARKERS = (
        'account name',
        'account number',
        'ifs code',
        'cif no',
        'txn date',
    )
    _WEB_MARKERS = (
        's no. value date transaction date',
        'transactions list',
    )

    # ------------------------------------------------------------------
    # Footer / header lines to skip in traditional format
    # ------------------------------------------------------------------
    _FOOTER_MARKERS = (
        'txn date value description',
        'date no.',
        'account statement from',
        'balance as on',
        'nomination registered',
        '(indian financial system)',
        '(magnetic ink character recognition)',
        'micr code',
        'ifs code',
        'cif no.',
        'mod balance',
        'interest rate',
        'drawing power',
        'account description',
        'branch :',
        'account number :',
        'account name :',
        'address',
        'date :',
        'lleeggee',     # doubled-char legends page from scanned last page
        'legends used',
        'the count of transactions',
        'please do not share your atm',
        'please select a shorter date',
        '**this is a computer generated',
        'this is a computer generated',
        'bank never asks for such',
    )

    # Month abbreviation → zero-padded number
    _MONTHS = {
        'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
        'may': '05', 'jun': '06', 'jul': '07', 'aug': '08',
        'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12',
    }

    def validate_format(self, file_path: str) -> bool:
        text = self._first_page_text(file_path).lower()
        trad = sum(1 for m in self._TRAD_MARKERS if m in text)
        web  = sum(1 for m in self._WEB_MARKERS  if m in text)
        return trad >= 3 or web >= 1

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def parse(self, file_path: str) -> List[Transaction]:
        page_texts = PDFExtractor.extract_pages_fallback(file_path) or []
        if self._is_web_format(page_texts):
            return self._parse_web_format(page_texts)
        return self._parse_traditional_format(page_texts)

    def parse_metadata(self, file_path: str) -> Dict[str, str]:
        page_texts = PDFExtractor.extract_pages_fallback(file_path) or []
        if self._is_web_format(page_texts):
            return self._parse_web_metadata(page_texts, file_path)
        return self._parse_traditional_metadata(page_texts)

    # ------------------------------------------------------------------
    # Format detection helper
    # ------------------------------------------------------------------
    def _is_web_format(self, page_texts: List[str]) -> bool:
        first = (page_texts[0] if page_texts else '').lower()
        return any(m in first for m in self._WEB_MARKERS)

    def _first_page_text(self, file_path: str) -> str:
        try:
            pages = PDFExtractor.extract_pages_fallback(file_path) or []
            return pages[0] if pages else ''
        except Exception:
            return ''

    # ------------------------------------------------------------------
    # Traditional format parser
    # ------------------------------------------------------------------
    # Layout (each transaction spans 2-4 lines):
    #
    #   Line 1:  <TxnDate>  <ValueDate>  <Description start>  [Debit]  [Credit]  <Balance>
    #   Line 2:  <UPI/ref continuation>  [Ref No.]
    #   Line 3+: more narration (optional)
    #
    # Dates are either "1 Sep 2023" (same line, full) or split across
    # two tokens when dates wrap:  "10 Oct" on one part, "2023" on next.
    #
    # The key identifying pattern for the transaction start line:
    #   starts with  \d{1,2} [A-Z][a-z]{2} \d{4}   (full date)
    #   OR the line has  D Mon YYYY  D Mon YYYY  at the start (wrapped)
    # ------------------------------------------------------------------

    # Matches "1 Sep 2023" or "10 Oct 2023"
    _DATE_TOKEN = r'\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}'
    _DATE_RE    = re.compile(_DATE_TOKEN, re.IGNORECASE)

    # Full transaction start: two dates then description then amounts
    # Amounts are Indian-comma-formatted: 1,23,456.78  or  0.0
    _AMT = r'\d[\d,]*\.\d+'
    _TRAD_ROW_RE = re.compile(
        rf'^({_DATE_TOKEN})\s+({_DATE_TOKEN})\s+'   # txn_date  value_date
        rf'(.+?)\s+'                                  # description (non-greedy)
        rf'({_AMT})\s+({_AMT})$',                    # last two amounts (debit/credit + balance)
        re.IGNORECASE,
    )

    # Wrapped-date row: "10 Oct" "2023" on consecutive tokens — handled below
    _PARTIAL_DATE_RE = re.compile(
        r'^(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)$',
        re.IGNORECASE,
    )
    # Two day+month pairs without year — wrapped transaction start across lines
    _WRAPPED_START_RE = re.compile(
        r'^\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+'
        r'\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)',
        re.IGNORECASE,
    )

    def _parse_sbi_date(self, raw: str) -> str:
        """Convert '1 Sep 2023' → '01-09-2023'."""
        raw = raw.strip()
        m = re.match(r'(\d{1,2})\s+(\w{3})\s+(\d{4})', raw, re.IGNORECASE)
        if not m:
            return raw
        day  = m.group(1).zfill(2)
        mon  = self._MONTHS.get(m.group(2).lower(), '00')
        year = m.group(3)
        return f'{day}-{mon}-{year}'

    def _is_footer_trad(self, line: str) -> bool:
        ll = line.lower()
        return any(ll.startswith(f) or f in ll for f in self._FOOTER_MARKERS)

    def _parse_traditional_format(self, page_texts: List[str]) -> List[Transaction]:
        transactions: List[Transaction] = []
        previous_balance: Optional[str] = None

        for page_text in page_texts:
            raw_lines = page_text.split('\n')
            # Rebuild lines, replacing (cid:9) with a space
            lines = [re.sub(r'\(cid:\d+\)', ' ', l).strip() for l in raw_lines]

            i = 0
            while i < len(lines):
                line = lines[i]

                if not line or self._is_footer_trad(line):
                    i += 1
                    continue

                # ---- Detect transaction start ----
                # Case 1: both dates on same line → matched by _TRAD_ROW_RE
                # Case 2: wrapped date — "10 Oct\n2023\n10 Oct\n2023\n..." needs
                #         normalising before matching.
                #
                # Strategy: try to assemble a full "txn_date value_date rest" string
                # by peeking ahead when we see a date-like start.

                assembled, consumed = self._try_assemble_trad_row(lines, i)
                if assembled is None:
                    i += 1
                    continue

                m = self._TRAD_ROW_RE.match(assembled)
                if not m:
                    i += consumed
                    continue

                txn_date   = self._parse_sbi_date(m.group(1))
                value_date = self._parse_sbi_date(m.group(2))
                narration  = m.group(3).strip()
                amt1       = m.group(4)   # second-to-last amount
                balance    = m.group(5)   # last amount = closing balance

                i += consumed

                # Collect continuation narration lines
                # Stop at: empty, footer, next transaction start, ref-number-only line
                ref_no = ''
                while i < len(lines):
                    nxt = re.sub(r'\(cid:\d+\)', ' ', lines[i]).strip()
                    if not nxt or self._is_footer_trad(nxt):
                        break
                    # Stop on full date transaction row
                    nxt_assembled, _ = self._try_assemble_trad_row(lines, i)
                    if nxt_assembled and self._TRAD_ROW_RE.match(nxt_assembled):
                        break
                    # Stop on wrapped-date start: "10 Oct 10 Oct ..." (year on next line)
                    if self._WRAPPED_START_RE.match(nxt):
                        break
                    narration = (narration + ' ' + nxt).strip()
                    i += 1

                # Determine debit/credit from previous balance and amt1
                withdrawal_amt = ''
                deposit_amt    = ''
                try:
                    curr_bal = float(balance.replace(',', ''))
                    if previous_balance is not None:
                        prev_bal = float(previous_balance.replace(',', ''))
                        delta    = round(curr_bal - prev_bal, 2)
                        if delta >= 0:
                            deposit_amt    = f'{delta:.2f}'
                        else:
                            withdrawal_amt = f'{-delta:.2f}'
                    else:
                        # First transaction — use amt1 with keyword heuristic
                        credit_keywords = ['BY ', 'CR/', '/CR/', 'CREDIT', 'NEFT*', 'IMPS3']
                        if any(k in narration.upper() for k in credit_keywords):
                            deposit_amt    = amt1
                        else:
                            withdrawal_amt = amt1
                except (ValueError, AttributeError):
                    withdrawal_amt = amt1

                transactions.append(Transaction(
                    date=txn_date,
                    narration=narration,
                    chq_ref_no='',
                    value_dt=value_date,
                    withdrawal_amt=withdrawal_amt,
                    deposit_amt=deposit_amt,
                    closing_balance=balance,
                ))
                previous_balance = balance

        return transactions

    def _try_assemble_trad_row(
        self, lines: List[str], start: int
    ) -> Tuple[Optional[str], int]:
        """
        From position `start`, try to assemble a string that starts with
        two full SBI dates ("D Mon YYYY  D Mon YYYY  …").

        SBI wraps long dates so "10 Oct 2023" may appear as:
            line[i]   = "10 Oct"
            line[i+1] = "2023 10 Oct"       ← value_dt day+month
            line[i+2] = "2023 <description…>"

        Returns (assembled_string, lines_consumed) or (None, 1).
        """
        def clean(l: str) -> str:
            return re.sub(r'\(cid:\d+\)', ' ', l).strip()

        line0 = clean(lines[start])
        if not line0:
            return None, 1

        # Fast path: both dates already on this line
        if self._DATE_RE.search(line0):
            # Count how many full dates appear
            dates_found = self._DATE_RE.findall(line0)
            if len(dates_found) >= 2:
                return line0, 1
            # Only one full date — try to merge with next line
            if start + 1 < len(lines):
                line1 = clean(lines[start + 1])
                merged = line0 + ' ' + line1
                if len(self._DATE_RE.findall(merged)) >= 2:
                    # need more lines for the amounts?
                    if start + 2 < len(lines):
                        line2 = clean(lines[start + 2])
                        merged2 = merged + ' ' + line2
                        if self._TRAD_ROW_RE.match(merged2):
                            return merged2, 3
                    if self._TRAD_ROW_RE.match(merged):
                        return merged, 2
                    return merged, 2

        # Wrapped date path: line starts with "D Mon" (no year)
        pm = self._PARTIAL_DATE_RE.match(line0)
        if pm and start + 1 < len(lines):
            line1 = clean(lines[start + 1])
            # line1 should start with year
            if re.match(r'^\d{4}', line1):
                candidate = line0 + ' ' + line1
                # Now look for a second date in candidate
                dates_found = self._DATE_RE.findall(candidate)
                if len(dates_found) >= 2:
                    if self._TRAD_ROW_RE.match(candidate):
                        return candidate, 2
                    # amounts may be on line2
                    if start + 2 < len(lines):
                        line2 = clean(lines[start + 2])
                        candidate2 = candidate + ' ' + line2
                        if self._TRAD_ROW_RE.match(candidate2):
                            return candidate2, 3
                    return candidate, 2
                # year merged but second date not yet in — keep merging
                if start + 2 < len(lines):
                    line2 = clean(lines[start + 2])
                    candidate2 = candidate + ' ' + line2
                    dates_found2 = self._DATE_RE.findall(candidate2)
                    if len(dates_found2) >= 2:
                        if self._TRAD_ROW_RE.match(candidate2):
                            return candidate2, 3
                        if start + 3 < len(lines):
                            line3 = clean(lines[start + 3])
                            candidate3 = candidate2 + ' ' + line3
                            if self._TRAD_ROW_RE.match(candidate3):
                                return candidate3, 4
                        return candidate2, 3

        return None, 1

    # ------------------------------------------------------------------
    # Web format parser (SBI online statement — identical layout to Axis web)
    # ------------------------------------------------------------------
    _WEB_ROW_RE = re.compile(
        r'^(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+'
        r'(-|[\w/]+)\s+'
        r'(.+?)\s+'
        r'(\d[\d,]*\.\d+)\s+'
        r'(\d[\d,]*\.\d+)\s+'
        r'(\d[\d,]*\.\d+)$'
    )
    _SERIAL_RE = re.compile(r'^(\d{1,4})\s+(.*)|^(\d{1,4})$')

    _WEB_FOOTER = (
        'transactions list',
        's no. value date',
        'detailed statement',
        'search',
        'transaction period',
        'advanced search',
        'amount from',
        'cheque number from',
        'transaction remarks',
        'transaction type',
        'lleeggee',
        'legends used',
    )

    def _is_web_footer(self, line: str) -> bool:
        ll = line.lower()
        return any(ll.startswith(f) or f in ll for f in self._WEB_FOOTER)

    def _parse_web_format(self, page_texts: List[str]) -> List[Transaction]:
        transactions: List[Transaction] = []

        for page_text in page_texts:
            lines = [l.strip() for l in page_text.split('\n')]
            i = 0
            while i < len(lines):
                line = lines[i]
                if not line or self._is_web_footer(line):
                    i += 1
                    continue

                # Strip leading serial+date artifact from page boundaries
                match_line = line
                sp = re.match(
                    r'^(\d+)\s+(\d{2}/\d{2}/\d{4}\s+\d{2}/\d{2}/\d{4}.+)', line
                )
                if sp:
                    match_line = sp.group(2)

                m = self._WEB_ROW_RE.match(match_line)
                if not m:
                    i += 1
                    continue

                value_dt = DateUtils.normalize_date(m.group(1))
                txn_dt   = DateUtils.normalize_date(m.group(2))
                chq_no   = m.group(3) if m.group(3) != '-' else ''
                narration = m.group(4).strip()
                amt1      = m.group(5)
                amt2      = m.group(6)
                amt3      = m.group(7)

                withdrawal_amt = amt1 if float(amt1.replace(',', '')) != 0.0 else ''
                deposit_amt    = amt2 if float(amt2.replace(',', '')) != 0.0 else ''
                closing_balance = amt3

                i += 1
                # Next line: serial number, optionally with narration continuation.
                # Only consume if it is NOT itself a transaction row.
                if i < len(lines):
                    nxt_stripped = lines[i].strip()
                    if not self._WEB_ROW_RE.match(nxt_stripped):
                        sm = self._SERIAL_RE.match(nxt_stripped)
                        if sm:
                            tail = (sm.group(2) or '').strip()
                            if tail:
                                narration = (narration + ' ' + tail).strip()
                            i += 1

                # Further continuation lines
                while i < len(lines):
                    nxt = lines[i].strip()
                    if not nxt or self._is_web_footer(nxt):
                        break
                    if re.match(r'^\d+$', nxt):
                        break
                    # Check if next line is a new transaction (with or without serial prefix)
                    chk = nxt
                    sp2 = re.match(
                        r'^(\d+)\s+(\d{2}/\d{2}/\d{4}\s+\d{2}/\d{2}/\d{4}.+)', nxt
                    )
                    if sp2:
                        chk = sp2.group(2)
                    if self._WEB_ROW_RE.match(chk):
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
                    closing_balance=closing_balance,
                ))

        return transactions

    # ------------------------------------------------------------------
    # Metadata – Traditional format
    # ------------------------------------------------------------------
    def _parse_traditional_metadata(self, page_texts: List[str]) -> Dict[str, str]:
        meta: Dict[str, str] = {
            'Bank':            'SBI',
            'Account Holder':  '',
            'Account Number':  '',
            'Address':         '',
            'Joint Holder':    '',
            'Branch':          '',
            'IFSC code':       '',
            'CIF No':          '',
            'Account Status':  '',
            'Scheme':          '',
            'Email':           '',
            'Mobile':          '',
            'PAN':             '',
            'Customer ID':     '',
            'A/C open date':   '',
            'From date':       '',
            'To date':         '',
            'Opening Balance': '',
            'Closing Balance': '',
            'Debit counts':    '',
            'Credit counts':   '',
            'Debit amount':    '',
            'Credit amount':   '',
        }

        # Combine first two pages for header search
        header_text = '\n'.join(page_texts[:2])
        lines = [re.sub(r'\(cid:\d+\)', ' ', l).strip() for l in header_text.split('\n')]

        def field_in_line(pattern: str, line: str) -> str:
            """Extract capture group from a single line."""
            m = re.search(pattern, line, re.IGNORECASE)
            return m.group(1).strip() if m else ''

        def find_field(pattern: str) -> str:
            """Search each line independently; return first match."""
            for ln in lines:
                v = field_in_line(pattern, ln)
                if v:
                    return v
            return ''

        meta['Account Holder'] = find_field(
            r'Account Name\s*:+\s*(?:Mr\.|Mrs\.|Ms\.|Dr\.)?\s*(.+)'
        )
        meta['Account Number'] = find_field(
            r'Account Number\s*:+\s*(\d+)'
        )
        meta['IFSC code'] = find_field(
            r'IFS Code\s*:+\s*([A-Z]{4}\d{7})'
        )
        meta['Branch'] = find_field(
            r'Branch\s*:+\s*(.+)'
        )
        meta['CIF No'] = find_field(
            r'CIF No\.?\s*:+\s*(\d+)'
        )
        meta['Scheme'] = find_field(
            r'Account Description\s*:+\s*(.+)'
        )

        # Date range — may span one line
        for ln in lines:
            stmt_m = re.search(
                r'Account Statement from\s+(.+?)\s+to\s+(.+)',
                ln, re.IGNORECASE
            )
            if stmt_m:
                meta['From date'] = self._parse_sbi_date(stmt_m.group(1).strip())
                meta['To date']   = self._parse_sbi_date(stmt_m.group(2).strip())
                break

        # Opening balance
        for ln in lines:
            bal_m = re.search(
                r'Balance as on .+?:\s+([\d,]+\.\d+)', ln, re.IGNORECASE
            )
            if bal_m:
                meta['Opening Balance'] = bal_m.group(1)
                break

        # Address — multi-line between "Address" and "Date :"
        addr_lines = []
        in_addr = False
        for ln in lines:
            ll = ln.lower()
            if ll.startswith('address'):
                in_addr = True
                after = re.sub(r'^address.*?:+\s*', '', ln, flags=re.IGNORECASE).strip()
                if after:
                    addr_lines.append(after)
                continue
            if in_addr:
                if re.match(
                    r'^(Date|Account Number|Account Description|Branch|Drawing|Interest|MOD|CIF|IFS|MICR|Nomination)\s*:?',
                    ln, re.IGNORECASE
                ):
                    break
                if ln:
                    addr_lines.append(ln)
        meta['Address'] = ', '.join(addr_lines).strip(', ')

        # Closing balance = last transaction's closing_balance (populated after parse)
        return meta

    # ------------------------------------------------------------------
    # Metadata – Web format
    # ------------------------------------------------------------------
    def _parse_web_metadata(
        self, page_texts: List[str], file_path: str
    ) -> Dict[str, str]:
        meta: Dict[str, str] = {
            'Bank':            'SBI',
            'Account Holder':  '',
            'Account Number':  '',
            'Address':         '',
            'Joint Holder':    '',
            'Branch':          '',
            'IFSC code':       '',
            'CIF No':          '',
            'Account Status':  '',
            'Scheme':          '',
            'Email':           '',
            'Mobile':          '',
            'PAN':             '',
            'Customer ID':     '',
            'A/C open date':   '',
            'From date':       '',
            'To date':         '',
            'Opening Balance': '',
            'Closing Balance': '',
            'Debit counts':    '',
            'Credit counts':   '',
            'Debit amount':    '',
            'Credit amount':   '',
        }

        first = page_texts[0] if page_texts else ''
        lines = [l.strip() for l in first.split('\n') if l.strip()]

        for ln in lines:
            # "Account Number 111201003558(INR) - BHIMARAJU SRIKANTH"
            m = re.match(
                r'Account Number\s+(\d+)\(INR\)\s*-\s*(.+)', ln, re.IGNORECASE
            )
            if m:
                meta['Account Number'] = m.group(1)
                meta['Account Holder'] = m.group(2).strip()

            # "Transaction Date from DD/MM/YYYY to DD/MM/YYYY"
            m2 = re.match(
                r'Transaction Date from\s+(\d{2}/\d{2}/\d{4})\s+to\s+(\d{2}/\d{2}/\d{4})',
                ln, re.IGNORECASE
            )
            if m2:
                meta['From date'] = DateUtils.normalize_date(m2.group(1))
                meta['To date']   = DateUtils.normalize_date(m2.group(2))

        return meta
