import sys
sys.path.insert(0, 'src')
from leviathan.transforms.raw_to_bronze.mpob_pdf import extract_mpob_overview_annual

ingest_date = '2026-06-01'
for yr in [2010, 2011, 2012, 2013, 2014, 2015, 2016]:
    with open(rf'C:\Temp\mpob_probe\year={yr}\mpob_overview_{yr}.pdf', 'rb') as f:
        pdf_bytes = f.read()
    df = extract_mpob_overview_annual(pdf_bytes, yr, ingest_date)
    if df.empty:
        print(f'{yr}: EMPTY')
    else:
        print(f'{yr}: {len(df)} rows')
        for _, r in df.iterrows():
            print(f'  {r["variable"]:45s}  {r["value"]:>15,.0f}')
