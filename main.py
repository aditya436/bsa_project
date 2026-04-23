from src.parsers.pdf_parser import PDFParser
import pandas as pd
import argparse

if __name__ == '__main__':
    arg_parser = argparse.ArgumentParser(description='Parse bank statement PDF and extract transactions + metadata.')
    arg_parser.add_argument('--file', '-f', default='data/Acct_Statement_XX0547_10052024.pdf', help='Path to the PDF file to parse (default: data/Acct_Statement_XX0547_10052024.pdf)')
    args = arg_parser.parse_args()

    pdf_path = args.file
    parser = PDFParser()

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