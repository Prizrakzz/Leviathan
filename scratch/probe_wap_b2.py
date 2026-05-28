"""Find Table 01 in pre-2002 WAP PDFs by scanning all pages."""
import boto3
import io
import pdfplumber

BUCKET = "leviathan-dev-shahem-001"
SAMPLES = ["1988-06", "1993-03", "1995-07", "1998-11", "2001-04"]

s3 = boto3.client("s3", region_name="us-east-1")

TABLE01_MARKERS = {"Wheat", "Oilseeds", "Cotton"}

for rm in SAMPLES:
    key = f"raw/production/source=usda_wap/release_month={rm}/production.pdf"
    pdf_bytes = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    print(f"\n{'='*60}")
    print(f"  {rm}  ({len(pdf_bytes)//1024} KB)")
    print(f"{'='*60}")

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        n = len(pdf.pages)
        print(f"  Total pages: {n}")
        print(f"  Page 6 content (0-indexed): see below")

        # Scan every page for Table01 markers
        for i, pg in enumerate(pdf.pages):
            txt = pg.extract_text() or ""
            words_in_page = set(txt.split())
            matches = TABLE01_MARKERS & words_in_page

            # Also check for "World" with numeric data pattern
            has_world = "World" in words_in_page or "WORLD" in words_in_page
            has_production = "Production" in words_in_page or "PRODUCTION" in words_in_page

            if matches or (has_world and has_production):
                lines = [l for l in txt.splitlines() if l.strip()]
                print(f"\n  --- Page {i} (matches={matches}) ---")
                for ln in lines[:10]:
                    print(f"    {repr(ln)}")

                # Try extract_table
                tbl = pg.extract_table()
                print(f"  extract_table(): {len(tbl) if tbl else None} rows")
                if tbl and len(tbl) > 2:
                    print(f"    row[0]: {tbl[0]}")
                    print(f"    row[1]: {tbl[1]}")
                    print(f"    row[2]: {tbl[2]}")

                # Only show first 3 matching pages to avoid overflow
