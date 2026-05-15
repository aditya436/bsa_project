import re
import logging
import math
from collections import Counter
from datetime import datetime, date
from typing import List, Dict, Tuple, Optional

from src.models.transaction import Transaction


class FraudDetector:
    """
    Fraud detection utility for parsed bank statements.

    Produces a risk score (0-100) and a list of specific flags.
    Score interpretation:
        0-25  : Low risk — likely genuine
        26-50 : Moderate risk — warrants review
        51-75 : High risk — strong indicators of tampering
        76-100: Very high risk — likely fraudulent or AI-generated

    Usage:
        detector = FraudDetector()
        report = detector.analyze(transactions, metadata)
        print(report['risk_score'], report['flags'])
    """

    # ------------------------------------------------------------------ #
    # Reference number patterns for major Indian payment modes            #
    # ------------------------------------------------------------------ #
    # UPI: Axis/HDFC format  UPI/P2A/<12digits>/  or ICICI format  UPI/<12digits>/
    _UPI_RE      = re.compile(r'UPI/(?:P2[APM]/|CR/|DR/)?\d{9,15}', re.IGNORECASE)
    # IMPS: standard  IMPS/P2A/<12digits>/  or ICICI  MMT/IMPS/<12digits>/
    _IMPS_RE     = re.compile(r'(?:MMT/)?IMPS/(?:P2[AP]/)?\d{9,15}', re.IGNORECASE)
    _NEFT_RE     = re.compile(r'NEFT/[A-Z0-9]{8,20}/', re.IGNORECASE)
    _NACH_RE     = re.compile(r'(?:ACH|NACH|ECS)-(?:CR|DR)', re.IGNORECASE)
    _CHQ_RE      = re.compile(r'^\d{6}$')

    # PDF creator strings that indicate manual editing / non-bank origin
    _SUSPICIOUS_CREATORS = (
        'microsoft word',
        'microsoft excel',
        'libreoffice',
        'openoffice',
        'canva',
        'adobe illustrator',
        'photoshop',
        'inkscape',
        'wps',
        'google docs',
        'smallpdf',
        'ilovepdf',
        'pdf24',
        'sejda',
        'chatgpt',
        'openai',
    )

    def analyze(
        self,
        transactions: List[Transaction],
        metadata: Dict[str, str],
        file_path: Optional[str] = None,
    ) -> Dict:
        """
        Run all fraud checks and return a consolidated report.

        Returns a dict with:
            risk_score   : int 0-100
            risk_level   : str ('Low' / 'Moderate' / 'High' / 'Very High')
            flags        : list of FlagItem dicts (check, severity, detail)
            summary      : dict with counts of each severity
        """
        flags = []

        if not transactions:
            flags.append(self._flag('EMPTY_STATEMENT', 'HIGH',
                                    'No transactions found — empty or unparseable statement.'))
            return self._build_report(flags)

        # --- Run all checks ---
        flags += self._check_pdf_metadata(file_path)
        flags += self._check_balance_chain(transactions, metadata)
        flags += self._check_opening_closing_match(transactions, metadata)
        flags += self._check_date_range(transactions, metadata)
        flags += self._check_chronological_order(transactions)
        flags += self._check_future_dates(transactions)
        flags += self._check_duplicate_transactions(transactions)
        flags += self._check_narration_authenticity(transactions)
        flags += self._check_round_number_bias(transactions)
        flags += self._check_transaction_date_distribution(transactions)
        flags += self._check_amount_precision(transactions)
        flags += self._check_metadata_completeness(metadata)

        return self._build_report(flags)

    # ================================================================== #
    # Individual checks                                                   #
    # ================================================================== #

    def _check_pdf_metadata(self, file_path: Optional[str]) -> List[Dict]:
        """Inspect PDF creator/producer/author fields for non-bank origins."""
        flags = []
        if not file_path:
            return flags
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                meta = pdf.metadata or {}
                creator  = str(meta.get('Creator',  '') or '').lower()
                producer = str(meta.get('Producer', '') or '').lower()
                author   = str(meta.get('Author',   '') or '').lower()
                combined = f"{creator} {producer} {author}"

                for sus in self._SUSPICIOUS_CREATORS:
                    if sus in combined:
                        flags.append(self._flag(
                            'SUSPICIOUS_PDF_CREATOR', 'HIGH',
                            f"PDF metadata shows non-bank origin: '{combined.strip()}'"
                        ))
                        break

                # Completely blank PDF metadata is also suspicious for bank docs
                if not creator and not producer:
                    flags.append(self._flag(
                        'MISSING_PDF_METADATA', 'MEDIUM',
                        'PDF has no creator/producer metadata — may indicate editing or regeneration.'
                    ))
        except Exception as e:
            logging.debug(f"PDF metadata check failed: {e}")
        return flags

    def _check_balance_chain(
        self, transactions: List[Transaction], metadata: Dict[str, str]
    ) -> List[Dict]:
        """
        Validate every step: prev_balance ± amount == closing_balance.
        Uses opening balance from metadata if available.
        """
        flags = []
        errors = []

        # Seed with opening balance from metadata if present
        opening_str = metadata.get('Opening Balance', '')
        try:
            prev = float(opening_str.replace(',', '')) if opening_str else None
        except ValueError:
            prev = None

        for idx, t in enumerate(transactions):
            try:
                closing = float(t.closing_balance.replace(',', ''))
            except (ValueError, AttributeError):
                flags.append(self._flag(
                    'INVALID_BALANCE_VALUE', 'HIGH',
                    f"Transaction #{idx + 1} ({t.date}) has non-numeric closing balance: '{t.closing_balance}'"
                ))
                prev = None
                continue

            w = float(t.withdrawal_amt.replace(',', '')) if t.withdrawal_amt else 0.0
            d = float(t.deposit_amt.replace(',', ''))    if t.deposit_amt    else 0.0

            if prev is not None:
                expected = round(prev - w + d, 2)
                if abs(expected - closing) > 0.02:
                    errors.append(
                        f"#{idx + 1} ({t.date}): expected {expected:.2f}, got {closing:.2f}"
                    )

            prev = closing

        if errors:
            sample = errors[:5]
            flags.append(self._flag(
                'BALANCE_CHAIN_BROKEN', 'HIGH',
                f"{len(errors)} balance continuity error(s). First 5: {'; '.join(sample)}"
            ))
        return flags

    def _check_opening_closing_match(
        self, transactions: List[Transaction], metadata: Dict[str, str]
    ) -> List[Dict]:
        """Cross-check statement summary opening/closing vs first/last transaction."""
        flags = []

        def _f(s):
            try:
                return float(s.replace(',', '')) if s else None
            except (ValueError, AttributeError):
                return None

        meta_open  = _f(metadata.get('Opening Balance', ''))
        meta_close = _f(metadata.get('Closing Balance', ''))
        txn_close  = _f(transactions[-1].closing_balance)

        if meta_close is not None and txn_close is not None:
            if abs(meta_close - txn_close) > 0.02:
                flags.append(self._flag(
                    'CLOSING_BALANCE_MISMATCH', 'HIGH',
                    f"Summary closing balance ({meta_close}) ≠ last transaction balance ({txn_close})."
                ))
        return flags

    def _check_date_range(
        self, transactions: List[Transaction], metadata: Dict[str, str]
    ) -> List[Dict]:
        """All transaction dates must fall within the statement's From/To period."""
        flags = []
        from_str = metadata.get('From date', '')
        to_str   = metadata.get('To date', '')

        if not from_str or not to_str:
            return flags

        try:
            from_dt = self._parse_date(from_str)
            to_dt   = self._parse_date(to_str)
        except ValueError:
            return flags

        out_of_range = []
        for t in transactions:
            try:
                txn_dt = self._parse_date(t.date)
                if txn_dt < from_dt or txn_dt > to_dt:
                    out_of_range.append(t.date)
            except ValueError:
                continue

        if out_of_range:
            flags.append(self._flag(
                'TRANSACTIONS_OUTSIDE_DATE_RANGE', 'HIGH',
                f"{len(out_of_range)} transaction(s) outside stated period "
                f"({from_str} – {to_str}): {out_of_range[:5]}"
            ))
        return flags

    def _check_chronological_order(self, transactions: List[Transaction]) -> List[Dict]:
        """Transactions must be in non-decreasing date order."""
        flags = []
        violations = []
        prev_dt = None
        for idx, t in enumerate(transactions):
            try:
                curr_dt = self._parse_date(t.date)
            except ValueError:
                continue
            if prev_dt is not None and curr_dt < prev_dt:
                violations.append(f"#{idx + 1}: {t.date} after {transactions[idx - 1].date}")
            prev_dt = curr_dt

        if violations:
            flags.append(self._flag(
                'NON_CHRONOLOGICAL_DATES', 'MEDIUM',
                f"{len(violations)} date ordering violation(s): {violations[:3]}"
            ))
        return flags

    def _check_future_dates(self, transactions: List[Transaction]) -> List[Dict]:
        """No transaction should be dated in the future."""
        flags = []
        today = date.today()
        future = [t.date for t in transactions if self._safe_date(t.date) and
                  self._safe_date(t.date) > today]
        if future:
            flags.append(self._flag(
                'FUTURE_DATED_TRANSACTIONS', 'HIGH',
                f"{len(future)} transaction(s) with future dates: {future[:5]}"
            ))
        return flags

    def _check_duplicate_transactions(self, transactions: List[Transaction]) -> List[Dict]:
        """Identical (date, narration, amount) triplets are suspicious."""
        flags = []
        seen = Counter()
        for t in transactions:
            key = (t.date, t.narration.strip(), t.withdrawal_amt, t.deposit_amt, t.closing_balance)
            seen[key] += 1

        dupes = {k: v for k, v in seen.items() if v > 1}
        if dupes:
            examples = [f"'{k[1][:40]}' on {k[0]} x{v}" for k, v in list(dupes.items())[:3]]
            flags.append(self._flag(
                'DUPLICATE_TRANSACTIONS', 'MEDIUM',
                f"{len(dupes)} duplicate transaction(s) detected: {'; '.join(examples)}"
            ))
        return flags

    def _check_narration_authenticity(self, transactions: List[Transaction]) -> List[Dict]:
        """
        Check that payment mode narrations contain proper reference numbers.
        Real bank narrations are long, structured strings with encoded refs.
        """
        flags = []
        upi_txns   = [t for t in transactions if 'UPI/' in t.narration.upper()]
        imps_txns  = [t for t in transactions if 'IMPS/' in t.narration.upper()]
        neft_txns  = [t for t in transactions if 'NEFT/' in t.narration.upper()]

        def _pct_invalid(txn_list, pattern):
            if not txn_list:
                return 0.0
            invalid = [t for t in txn_list if not pattern.search(t.narration)]
            return len(invalid) / len(txn_list)

        upi_fail  = _pct_invalid(upi_txns,  self._UPI_RE)
        imps_fail = _pct_invalid(imps_txns, self._IMPS_RE)
        neft_fail = _pct_invalid(neft_txns, self._NEFT_RE)

        if upi_fail > 0.3 and len(upi_txns) >= 5:
            flags.append(self._flag(
                'INVALID_UPI_REF_NUMBERS', 'HIGH',
                f"{upi_fail * 100:.0f}% of {len(upi_txns)} UPI narrations lack valid 12-digit reference numbers."
            ))
        if imps_fail > 0.3 and len(imps_txns) >= 3:
            flags.append(self._flag(
                'INVALID_IMPS_REF_NUMBERS', 'MEDIUM',
                f"{imps_fail * 100:.0f}% of {len(imps_txns)} IMPS narrations lack valid reference numbers."
            ))
        if neft_fail > 0.3 and len(neft_txns) >= 3:
            flags.append(self._flag(
                'INVALID_NEFT_REF_NUMBERS', 'MEDIUM',
                f"{neft_fail * 100:.0f}% of {len(neft_txns)} NEFT narrations lack valid reference numbers."
            ))

        # Very short narrations are suspicious (real ones are typically 30+ chars)
        short = [t for t in transactions if len(t.narration.strip()) < 10]
        if len(short) / len(transactions) > 0.2:
            flags.append(self._flag(
                'SUSPICIOUSLY_SHORT_NARRATIONS', 'MEDIUM',
                f"{len(short)} transactions ({len(short) * 100 // len(transactions)}%) "
                f"have narrations shorter than 10 characters."
            ))
        return flags

    def _check_round_number_bias(self, transactions: List[Transaction]) -> List[Dict]:
        """
        AI-generated amounts tend to be suspiciously round (multiples of 500/1000).
        Real statements have irregular amounts (fees, interest, taxes).
        """
        flags = []
        amounts = []
        for t in transactions:
            for amt_str in [t.withdrawal_amt, t.deposit_amt]:
                if amt_str:
                    try:
                        amounts.append(float(amt_str.replace(',', '')))
                    except ValueError:
                        pass

        if not amounts:
            return flags

        round_500  = sum(1 for a in amounts if a >= 500  and a % 500  == 0)
        round_1000 = sum(1 for a in amounts if a >= 1000 and a % 1000 == 0)
        pct_500  = round_500  / len(amounts)
        pct_1000 = round_1000 / len(amounts)

        if pct_1000 > 0.75 and len(amounts) >= 10:
            flags.append(self._flag(
                'EXTREME_ROUND_NUMBER_BIAS', 'HIGH',
                f"{pct_1000 * 100:.0f}% of amounts are exact multiples of 1000 "
                f"— far above the typical ~20-30% in real statements."
            ))
        elif pct_500 > 0.85 and len(amounts) >= 10:
            flags.append(self._flag(
                'HIGH_ROUND_NUMBER_BIAS', 'MEDIUM',
                f"{pct_500 * 100:.0f}% of amounts are exact multiples of 500."
            ))
        return flags

    def _check_transaction_date_distribution(
        self, transactions: List[Transaction]
    ) -> List[Dict]:
        """
        Real statements have irregular date gaps.
        Suspiciously uniform daily spacing or too few unique dates suggests fabrication.
        """
        flags = []
        dates = []
        for t in transactions:
            d = self._safe_date(t.date)
            if d:
                dates.append(d)

        if len(dates) < 10:
            return flags

        unique_dates = sorted(set(dates))
        if len(unique_dates) < 3:
            return flags

        gaps = [(unique_dates[i + 1] - unique_dates[i]).days
                for i in range(len(unique_dates) - 1)]
        mean_gap = sum(gaps) / len(gaps)
        std_gap  = math.sqrt(sum((g - mean_gap) ** 2 for g in gaps) / len(gaps)) if gaps else 0

        # Coefficient of variation: real statements are irregular (CV > 0.5 typically)
        cv = std_gap / mean_gap if mean_gap > 0 else 0
        if cv < 0.15 and len(gaps) >= 10:
            flags.append(self._flag(
                'UNIFORM_DATE_SPACING', 'MEDIUM',
                f"Transaction dates are suspiciously uniform (CV={cv:.2f}). "
                f"Mean gap: {mean_gap:.1f} days, StdDev: {std_gap:.1f} days."
            ))

        # Transactions only on weekdays / never on weekends is suspicious
        # (real accounts have ATM/UPI on weekends too)
        weekend_txns = sum(1 for d in dates if d.weekday() >= 5)
        if len(dates) >= 30 and weekend_txns == 0:
            flags.append(self._flag(
                'NO_WEEKEND_TRANSACTIONS', 'LOW',
                f"Zero weekend transactions across {len(dates)} entries over "
                f"{(max(dates) - min(dates)).days} days — uncommon for personal accounts."
            ))
        return flags

    def _check_amount_precision(self, transactions: List[Transaction]) -> List[Dict]:
        """
        Real bank amounts have varied decimal precision (fees, interest = odd paise).
        Statements where 100% of amounts end in .00 are suspicious.
        """
        flags = []
        amounts = []
        for t in transactions:
            for amt_str in [t.withdrawal_amt, t.deposit_amt]:
                if amt_str:
                    try:
                        amounts.append(float(amt_str.replace(',', '')))
                    except ValueError:
                        pass

        if len(amounts) < 10:
            return flags

        whole_rupees = sum(1 for a in amounts if a == int(a))
        pct = whole_rupees / len(amounts)
        if pct > 0.97:
            flags.append(self._flag(
                'ALL_AMOUNTS_WHOLE_RUPEES', 'MEDIUM',
                f"{pct * 100:.0f}% of amounts have no paise component (.00). "
                f"Genuine statements typically include interest, charges, and tax amounts with paise."
            ))
        return flags

    def _check_metadata_completeness(self, metadata: Dict[str, str]) -> List[Dict]:
        """Flag statements where critical metadata fields are entirely absent."""
        flags = []
        critical = ['Account Number', 'Account Holder', 'From date', 'To date']
        missing = [f for f in critical if not metadata.get(f, '').strip()]
        if missing:
            flags.append(self._flag(
                'MISSING_CRITICAL_METADATA', 'MEDIUM',
                f"Critical metadata fields are empty: {missing}"
            ))
        return flags

    # ================================================================== #
    # Report builder                                                      #
    # ================================================================== #

    def _build_report(self, flags: List[Dict]) -> Dict:
        severity_weight = {'HIGH': 25, 'MEDIUM': 10, 'LOW': 4}
        severity_cap    = {'HIGH': 75, 'MEDIUM': 30, 'LOW': 12}

        totals = {'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
        for f in flags:
            totals[f['severity']] += 1

        raw_score = (
            min(totals['HIGH']   * severity_weight['HIGH'],   severity_cap['HIGH'])   +
            min(totals['MEDIUM'] * severity_weight['MEDIUM'], severity_cap['MEDIUM']) +
            min(totals['LOW']    * severity_weight['LOW'],    severity_cap['LOW'])
        )
        score = min(raw_score, 100)

        if score <= 25:
            level = 'Low'
        elif score <= 50:
            level = 'Moderate'
        elif score <= 75:
            level = 'High'
        else:
            level = 'Very High'

        return {
            'risk_score': score,
            'risk_level': level,
            'flags': flags,
            'summary': {
                'total_flags': len(flags),
                'high':   totals['HIGH'],
                'medium': totals['MEDIUM'],
                'low':    totals['LOW'],
            }
        }

    # ================================================================== #
    # Helpers                                                             #
    # ================================================================== #

    @staticmethod
    def _flag(check: str, severity: str, detail: str) -> Dict:
        return {'check': check, 'severity': severity, 'detail': detail}

    @staticmethod
    def _parse_date(date_str: str) -> date:
        """Parse dd-mm-yyyy or dd/mm/yyyy into a date object."""
        for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%d-%m-%y', '%d/%m/%y'):
            try:
                return datetime.strptime(date_str.strip(), fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Cannot parse date: {date_str}")

    @classmethod
    def _safe_date(cls, date_str: str) -> Optional[date]:
        try:
            return cls._parse_date(date_str)
        except ValueError:
            return None
