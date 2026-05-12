import os
import unittest
from src.parsers.hdfc_parser import HDFCParser
from src.parsers.icici_parser import ICICIParser
from src.parsers.parser_factory import ParserFactory
from src.models.transaction import Transaction
from src.utils.date_utils import DateUtils

# Resolve paths relative to project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HDFC_PDF = os.path.join(PROJECT_ROOT, 'data', 'hdfc', 'Acct_Statement_XX0547_10052024.pdf')
ICICI_PDF = os.path.join(PROJECT_ROOT, 'data', 'icici', 'Bank_Statement_ICICI.pdf')


class TestTransaction(unittest.TestCase):
    """Tests for the Transaction dataclass."""

    def test_creation(self):
        t = Transaction(
            date='01-01-2024',
            narration='TEST PAYMENT',
            chq_ref_no='REF123',
            value_dt='01-01-2024',
            withdrawal_amt='500.00',
            deposit_amt='',
            closing_balance='9500.00'
        )
        self.assertEqual(t.date, '01-01-2024')
        self.assertEqual(t.narration, 'TEST PAYMENT')
        self.assertEqual(t.withdrawal_amt, '500.00')
        self.assertEqual(t.deposit_amt, '')
        self.assertEqual(t.closing_balance, '9500.00')

    def test_fields_are_strings(self):
        t = Transaction('d', 'n', 'c', 'v', 'w', 'dep', 'bal')
        for field in [t.date, t.narration, t.chq_ref_no, t.value_dt,
                      t.withdrawal_amt, t.deposit_amt, t.closing_balance]:
            self.assertIsInstance(field, str)


class TestDateUtils(unittest.TestCase):
    """Tests for the DateUtils utility class."""

    def test_normalize_dd_mm_yyyy(self):
        self.assertEqual(DateUtils.normalize_date('25-12-2023'), '25-12-2023')

    def test_normalize_dd_slash_mm_slash_yyyy(self):
        self.assertEqual(DateUtils.normalize_date('25/12/2023'), '25-12-2023')

    def test_normalize_dd_slash_mm_slash_yy(self):
        result = DateUtils.normalize_date('25/12/23')
        self.assertEqual(result, '25-12-2023')

    def test_normalize_iso_format(self):
        self.assertEqual(DateUtils.normalize_date('2023-12-25'), '25-12-2023')

    def test_normalize_empty_string(self):
        self.assertEqual(DateUtils.normalize_date(''), '')

    def test_validate_date_order_correct(self):
        dates = ['01-01-2024', '15-01-2024', '01-02-2024']
        self.assertTrue(DateUtils.validate_date_order(dates))

    def test_validate_date_order_incorrect(self):
        dates = ['15-01-2024', '01-01-2024', '01-02-2024']
        self.assertFalse(DateUtils.validate_date_order(dates))

    def test_parse_date_range(self):
        start, end = DateUtils.parse_date_range('from 01-01-2024 to 31-01-2024')
        self.assertEqual(start, '01-01-2024')
        self.assertEqual(end, '31-01-2024')


class TestParserFactory(unittest.TestCase):
    """Tests for the ParserFactory."""

    def test_get_hdfc_parser(self):
        parser = ParserFactory.get_parser('hdfc')
        self.assertIsInstance(parser, HDFCParser)

    def test_get_icici_parser(self):
        parser = ParserFactory.get_parser('icici')
        self.assertIsInstance(parser, ICICIParser)

    def test_case_insensitive(self):
        parser = ParserFactory.get_parser('HDFC')
        self.assertIsInstance(parser, HDFCParser)

    def test_unsupported_bank_raises(self):
        with self.assertRaises(ValueError):
            ParserFactory.get_parser('axis')

    def test_get_supported_banks(self):
        banks = ParserFactory.get_supported_banks()
        self.assertIn('hdfc', banks)
        self.assertIn('icici', banks)

    @unittest.skipUnless(os.path.exists(HDFC_PDF), 'HDFC sample PDF not found')
    def test_detect_hdfc(self):
        detected = ParserFactory.detect_bank(HDFC_PDF)
        self.assertEqual(detected, 'hdfc')

    @unittest.skipUnless(os.path.exists(ICICI_PDF), 'ICICI sample PDF not found')
    def test_detect_icici(self):
        detected = ParserFactory.detect_bank(ICICI_PDF)
        self.assertEqual(detected, 'icici')


class TestHDFCParser(unittest.TestCase):
    """Tests for the HDFCParser against real PDF data."""

    @classmethod
    def setUpClass(cls):
        cls.parser = HDFCParser()
        cls.pdf_available = os.path.exists(HDFC_PDF)

    @unittest.skipUnless(os.path.exists(HDFC_PDF), 'HDFC sample PDF not found')
    def test_parse_returns_transactions(self):
        transactions = self.parser.parse(HDFC_PDF)
        self.assertIsInstance(transactions, list)
        self.assertGreater(len(transactions), 0)

    @unittest.skipUnless(os.path.exists(HDFC_PDF), 'HDFC sample PDF not found')
    def test_transaction_fields_populated(self):
        transactions = self.parser.parse(HDFC_PDF)
        t = transactions[0]
        self.assertIsInstance(t, Transaction)
        self.assertTrue(t.date)
        self.assertTrue(t.narration)
        self.assertTrue(t.closing_balance)

    @unittest.skipUnless(os.path.exists(HDFC_PDF), 'HDFC sample PDF not found')
    def test_dates_normalized(self):
        transactions = self.parser.parse(HDFC_PDF)
        for t in transactions:
            self.assertRegex(t.date, r'^\d{2}-\d{2}-\d{4}$',
                             f"Date not in dd-mm-yyyy format: {t.date}")

    @unittest.skipUnless(os.path.exists(HDFC_PDF), 'HDFC sample PDF not found')
    def test_withdrawal_or_deposit_set(self):
        transactions = self.parser.parse(HDFC_PDF)
        for t in transactions:
            has_withdrawal = bool(t.withdrawal_amt)
            has_deposit = bool(t.deposit_amt)
            self.assertTrue(has_withdrawal or has_deposit,
                            f"Transaction on {t.date} has neither withdrawal nor deposit")

    @unittest.skipUnless(os.path.exists(HDFC_PDF), 'HDFC sample PDF not found')
    def test_parse_metadata(self):
        metadata = self.parser.parse_metadata(HDFC_PDF)
        self.assertIsInstance(metadata, dict)
        self.assertEqual(metadata.get('Bank'), 'HDFC')
        self.assertIn('Name', metadata)
        self.assertIn('From date', metadata)
        self.assertIn('To date', metadata)

    @unittest.skipUnless(os.path.exists(HDFC_PDF), 'HDFC sample PDF not found')
    def test_validate_format_positive(self):
        self.assertTrue(self.parser.validate_format(HDFC_PDF))

    @unittest.skipUnless(os.path.exists(ICICI_PDF), 'ICICI sample PDF not found')
    def test_validate_format_negative(self):
        self.assertFalse(self.parser.validate_format(ICICI_PDF))


class TestICICIParser(unittest.TestCase):
    """Tests for the ICICIParser against real PDF data."""

    @classmethod
    def setUpClass(cls):
        cls.parser = ICICIParser()
        cls.pdf_available = os.path.exists(ICICI_PDF)

    @unittest.skipUnless(os.path.exists(ICICI_PDF), 'ICICI sample PDF not found')
    def test_parse_returns_transactions(self):
        transactions = self.parser.parse(ICICI_PDF)
        self.assertIsInstance(transactions, list)
        self.assertGreater(len(transactions), 0)

    @unittest.skipUnless(os.path.exists(ICICI_PDF), 'ICICI sample PDF not found')
    def test_transaction_fields_populated(self):
        transactions = self.parser.parse(ICICI_PDF)
        t = transactions[0]
        self.assertIsInstance(t, Transaction)
        self.assertTrue(t.date)
        self.assertTrue(t.closing_balance)

    @unittest.skipUnless(os.path.exists(ICICI_PDF), 'ICICI sample PDF not found')
    def test_dates_normalized(self):
        transactions = self.parser.parse(ICICI_PDF)
        for t in transactions:
            self.assertRegex(t.date, r'^\d{2}-\d{2}-\d{4}$',
                             f"Date not in dd-mm-yyyy format: {t.date}")

    @unittest.skipUnless(os.path.exists(ICICI_PDF), 'ICICI sample PDF not found')
    def test_parse_metadata(self):
        metadata = self.parser.parse_metadata(ICICI_PDF)
        self.assertIsInstance(metadata, dict)
        self.assertEqual(metadata.get('Bank'), 'ICICI')

    @unittest.skipUnless(os.path.exists(ICICI_PDF), 'ICICI sample PDF not found')
    def test_validate_format_positive(self):
        self.assertTrue(self.parser.validate_format(ICICI_PDF))

    @unittest.skipUnless(os.path.exists(HDFC_PDF), 'HDFC sample PDF not found')
    def test_validate_format_negative(self):
        self.assertFalse(self.parser.validate_format(HDFC_PDF))


if __name__ == '__main__':
    unittest.main()