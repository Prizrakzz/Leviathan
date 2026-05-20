"""Probe MPOB BEPI /images/overview/ to discover which years have PDFs.

Tries both filename patterns for each year 2006-2016:
  - Overview_of_Industry_{YYYY}.pdf  (pre-2021 style, confirmed 2016-2020)
  - Overview{YYYY}.pdf               (2021+ style, unlikely for <=2016)

Outputs a sorted table of found PDFs and saves results to
data/mpob/overview_pdf_probe.json for use in populating mpob_archive.yaml.

Usage:
    python scratch/mpob/probe_overview_pdfs.py
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

os.chdir(r"C:\Users\User\Desktop\Leviathan")

BASE = "https://bepi.mpob.gov.my/images/overview"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

PATTERNS = [
    "Overview_of_Industry_{year}.pdf",   # confirmed pre-2021
    "Overview{year}.pdf",                # 2021+ style
]

# Probe pre-2017 years (2017-2020 are covered by HTML annual summaries,
# but include them here to confirm the URL pattern crossover point)
PROBE_YEARS = list(range(2006, 2021))


def probe_year(year: int, session: requests.Session) -> dict | None:
    for pattern in PATTERNS:
        filename = pattern.format(year=year)
        url = f"{BASE}/{filename}"
        try:
            r = session.head(url, timeout=10, allow_redirects=True)
            if r.status_code == 200:
                size = int(r.headers.get("Content-Length", 0))
                return {"year": year, "filename": filename, "url": url, "bytes": size}
        except requests.RequestException:
            pass
    return None


def main() -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    found: list[dict] = []
    print(f"Probing {len(PROBE_YEARS)} years ({PROBE_YEARS[0]}–{PROBE_YEARS[-1]}) ...")

    for year in PROBE_YEARS:
        result = probe_year(year, session)
        if result:
            mb = result["bytes"] / 1_048_576
            print(f"  {year}: FOUND  {result['filename']}  ({mb:.1f} MB)")
            found.append(result)
        else:
            print(f"  {year}: not found")
        time.sleep(0.3)

    session.close()

    print(f"\nTotal PDFs found: {len(found)}")
    print(f"Year range: {found[0]['year']}–{found[-1]['year']}" if found else "None")

    out_path = Path("data/mpob/overview_pdf_probe.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(found, indent=2), encoding="utf-8")
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
