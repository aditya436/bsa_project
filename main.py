from src.parsers.parser_factory import ParserFactory
import pandas as pd
import argparse
import sys

if __name__ == '__main__':
    arg_parser = argparse.ArgumentParser(
        description='Parse bank statement PDF and extract transactions + metadata.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  python main.py --file data/statement.pdf --bank hdfc
  python main.py --file data/statement.pdf  (auto-detect bank)
  python main.py --file data/statement.pdf --bank icici

Supported banks: {', '.join(ParserFactory.get_supported_banks()).upper()}
        """
    )
    arg_parser.add_argument('--file', '-f', default='data/hdfc/Acct_Statement_XX0547_10052024.pdf', 
                           help='Path to the PDF file to parse (default: data/hdfc/Acct_Statement_XX0547_10052024.pdf)')
    arg_parser.add_argument('--bank', '-b', default=None, 
                           help='Bank name (hdfc, icici). If not provided, will auto-detect.')
    args = arg_parser.parse_args()

    pdf_path = args.file
    
    # Determine which parser to use
    if args.bank:
        try:
            parser = ParserFactory.get_parser(args.bank)
            print(f"Using {args.bank.upper()} parser")
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
    else:
        # Auto-detect bank
        detected_bank = ParserFactory.detect_bank(pdf_path)
        if detected_bank:
            parser = ParserFactory.get_parser(detected_bank)
        else:
            print("Error: Could not auto-detect bank. Please specify with --bank flag.")
            print(f"Supported banks: {', '.join(ParserFactory.get_supported_banks()).upper()}")
            sys.exit(1)

    transactions = parser.parse(pdf_path)
    print(f"Parsed {len(transactions)} transactions from {pdf_path}.")

    # Convert to DataFrame
    df = pd.DataFrame([t.__dict__ for t in transactions])

    # Set display options to show full data without truncation
    pd.set_option('display.max_rows', None)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', None)
    pd.set_option('display.max_colwidth', None)

    # Remove unwanted columns from transactions output
    df = df[['date', 'narration', 'withdrawal_amt', 'deposit_amt', 'closing_balance']]

    # Extract metadata and create a separate metadata DataFrame
    metadata = parser.parse_metadata(pdf_path)
    metadata_df = pd.DataFrame([metadata])

    print("\nAccount Metadata:")
    print(metadata_df.T)
    print("\nTransactions DataFrame:")
    print(df.head(10))