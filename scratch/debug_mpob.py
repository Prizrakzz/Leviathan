"""Debug script to inspect MPOB HTML table structure."""
import io
import pandas as pd
from bs4 import BeautifulSoup

html = open("scratch/mpob_2019_sample.html", encoding="utf-8", errors="replace").read()
soup = BeautifulSoup(html, "html.parser")
tables = soup.find_all("table")
print(f"Tables found: {len(tables)}")

KEYWORDS = ("production", "export", "stock", "ffb", "cpo", "pko", "palm")

for i, tbl in enumerate(tables[:5]):
    for flavor in ["html5lib", "lxml", "html.parser"]:
        try:
            dfs = pd.read_html(io.StringIO(str(tbl)), header=0, flavor=flavor)
            for j, df in enumerate(dfs):
                print(f"\nTable {i}.{j} [{flavor}]: shape={df.shape}")
                print(f"  cols: {list(df.columns[:6])}")
                print(f"  row0: {list(df.iloc[0, :6])}")
                col_text = " ".join(str(c).lower() for c in df.columns)
                cell_text = " ".join(df.astype(str).values.flatten()).lower()
                col_hits = [kw for kw in KEYWORDS if kw in col_text]
                cell_hits = [kw for kw in KEYWORDS if kw in cell_text]
                print(f"  col_text hits: {col_hits}")
                print(f"  cell_text hits: {cell_hits}")
            break
        except Exception as e:
            print(f"  Table {i} [{flavor}]: FAILED - {e}")
