"""Probe pre-2002 archive.org WAP PDFs to understand page 6 table structure."""
import boto3
import io
import pdfplumber

BUCKET = "leviathan-dev-shahem-001"
SAMPLES = ["1988-06", "1990-09", "1993-03", "1995-07", "1998-11", "2001-04"]

s3 = boto3.client("s3", region_name="us-east-1")


def unreverse(raw_table):
    return [
        [cell[::-1] if isinstance(cell, str) else cell for cell in row]
        for row in raw_table
    ]


for rm in SAMPLES:
    key = f"raw/production/source=usda_wap/release_month={rm}/production.pdf"
    pdf_bytes = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    print(f"\n{'='*60}")
    print(f"  {rm}  ({len(pdf_bytes)//1024} KB)")
    print(f"{'='*60}")

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        n = len(pdf.pages)
        print(f"  total pages: {n}")
        pg = pdf.pages[6]

        # --- default extract_table ---
        tbl = pg.extract_table()
        print(f"  extract_table() (default): {len(tbl) if tbl else None} rows")

        # --- text strategy ---
        ts_text = {"vertical_strategy": "text", "horizontal_strategy": "text"}
        tbl_t = pg.extract_table(ts_text)
        print(f"  extract_table(text/text): {len(tbl_t) if tbl_t else None} rows")

        # --- lines strategy ---
        ts_lines = {"vertical_strategy": "lines_strict", "horizontal_strategy": "lines_strict"}
        tbl_l = pg.extract_table(ts_lines)
        print(f"  extract_table(lines_strict): {len(tbl_l) if tbl_l else None} rows")

        # --- raw text ---
        txt = pg.extract_text()
        if txt:
            lines = [ln for ln in txt.splitlines() if ln.strip()]
            print(f"  extract_text() non-empty lines: {len(lines)}")
            print("  first 8 lines (raw):")
            for ln in lines[:8]:
                print(f"    {repr(ln)}")
            print("  first 8 lines (reversed):")
            for ln in lines[:8]:
                print(f"    {repr(ln[::-1])}")
        else:
            print("  extract_text(): None")

        # --- words ---
        words = pg.extract_words()
        print(f"  extract_words() count: {len(words)}")
        if words:
            print("  first 10 words (text, x0, top):")
            for w in words[:10]:
                print(f"    {repr(w['text']):20s}  x0={w['x0']:.1f}  top={w['top']:.1f}")

        # --- if text strategy worked, show rows ---
        if tbl_t:
            rev = unreverse(tbl_t)
            print(f"  text/text table after unreverse ({len(rev)} rows):")
            for i, row in enumerate(rev[:5]):
                print(f"    row[{i}]: {row}")
