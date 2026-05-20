"""Probe MPOC Competitive Price Table (CPO vs SBO vs SFO spreads).

The live page at https://mpoc.org.my/market-insight/daily-palm-oil-prices/
contains two tables:
  1. CPO daily Bursa settlement prices (rolling ~2-week window).
  2. Monthly competitive price comparison: CPO BMD+3 vs SBO ARG FOB vs
     SFO Black Sea FOB, with price premiums.

This probe confirms the URL, validation markers, data depth of the spread
table, and saves results to data/mpoc/competitive_prices_probe.json.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import requests

_URL = "https://mpoc.org.my/market-insight/daily-palm-oil-prices/"
_VALIDATION_MARKERS = ["CPO", "SBO"]  # both must be present
_SPREAD_MARKER = "BMD"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_OUT_PATH = (
    Path(__file__).parent.parent.parent
    / "data"
    / "mpoc"
    / "competitive_prices_probe.json"
)

# Pattern to find rows like "26-Jan | 1064 | 1188 ..." in the spread table
_ROW_PATTERN = re.compile(r"\d{2}-[A-Za-z]{3}", re.IGNORECASE)


def main() -> None:
    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": _UA})

    print(f"Fetching {_URL} ...")
    resp = session.get(_URL, timeout=30, allow_redirects=True)
    resp.raise_for_status()
    html = resp.text
    html_upper = html.upper()
    size_bytes = len(resp.content)

    markers_found = {m: (m in html_upper) for m in _VALIDATION_MARKERS}
    spread_table_found = _SPREAD_MARKER in html_upper

    # Extract month labels from the spread table to estimate data depth
    spread_rows = _ROW_PATTERN.findall(html)
    unique_months = list(dict.fromkeys(spread_rows))  # deduplicated, ordered

    print(f"  Status: {resp.status_code}  Size: {size_bytes:,} bytes")
    print(f"  Validation markers: {markers_found}")
    print(f"  Spread table found (BMD marker): {spread_table_found}")
    print(f"  Spread table row labels found: {unique_months}")

    result = {
        "url": _URL,
        "status_code": resp.status_code,
        "size_bytes": size_bytes,
        "validation_markers": markers_found,
        "spread_table_found": spread_table_found,
        "spread_row_labels": unique_months,
        "notes": (
            "Single live page — no historical archive. "
            "Re-run fetch_mpoc.py periodically (without --skip-existing-s3) to refresh."
        ),
    }

    _OUT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nSaved → {_OUT_PATH}")


if __name__ == "__main__":
    main()
