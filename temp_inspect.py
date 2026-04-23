import pdfplumber

path = 'data/Acct_Statement_XX0547_10052024.pdf'
with pdfplumber.open(path) as pdf:
    print('pages', len(pdf.pages))
    print('---PAGE1---')
    print(pdf.pages[0].extract_text()[:2000])
    print('---LAST---')
    print(pdf.pages[-1].extract_text()[:5000])
