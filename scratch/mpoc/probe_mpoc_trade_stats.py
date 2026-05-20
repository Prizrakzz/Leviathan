"""Probe MPOC Monthly Trade Statistics pages.

Checks availability of annual trade-statistics pages at:
    https://mpoc.org.my/monthly-palm-oil-trade-statistics-{YYYY}/

For each found page, also verifies the expected HTML validation marker is
present so fetch_mpoc.py can use the same check.

Writes results to data/mpoc/trade_stats_probe.json.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

_BASE_URL = "https://mpoc.org.my/monthly-palm-oil-trade-statistics-{year}/"
_VALIDATION_MARKER = "EXPORTS TO MAJOR COUNTRIES"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_OUT_PATH = Path(__file__).parent.parent.parent / "data" / "mpoc" / "trade_stats_probe.json"

START_YEAR = 2000
END_YEAR = 2025


def main() -> None:
    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": _UA})

    results: list[dict] = []

    for year in range(START_YEAR, END_YEAR + 1):
        url = _BASE_URL.format(year=year)
        try:
            resp = session.get(url, timeout=20, allow_redirects=True)
            if resp.status_code == 404:
                status = "not_found"
                marker_found = False
                size_bytes = 0
            elif resp.status_code == 200:
                marker_found = _VALIDATION_MARKER in resp.text.upper()
                status = "found" if marker_found else "found_no_marker"
                size_bytes = len(resp.content)
            else:
                status = f"http_{resp.status_code}"
                marker_found = False
                size_bytes = 0

            entry = {
                "year": year,
                "url": url,
                "status": status,
                "marker_found": marker_found,
                "size_bytes": size_bytes,
            }
        except Exception as exc:
            entry = {
                "year": year,
                "url": url,
                "status": f"error: {exc}",
                "marker_found": False,
                "size_bytes": 0,
            }

        results.append(entry)
        icon = "✓" if entry["status"] == "found" else ("✗" if entry["status"] == "not_found" else "?")
        print(f"  {year}  {icon}  {entry['status']}  ({entry['size_bytes']:,} bytes)")
        time.sleep(0.5)

    _OUT_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    found = [r for r in results if r["status"] == "found"]
    print(f"\nFound: {len(found)} pages ({found[0]['year'] if found else 'n/a'}–{found[-1]['year'] if found else 'n/a'})")
    print(f"Saved → {_OUT_PATH}")


if __name__ == "__main__":
    main()
