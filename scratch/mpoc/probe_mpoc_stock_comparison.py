"""Probe MPOC Stock Comparison page(s).

The live page at https://mpoc.org.my/market-insight/stock-comparison/ shows
multi-country oils & fats ending-stock tables plus analyst narrative.

This probe:
  1. Fetches the main stock-comparison page and identifies all country sections
     (headers like "COUNTRY : CHINA").
  2. Checks for per-country sub-URLs (e.g. /market-insight/stock-comparison-china/).
  3. Checks for historical archive pages (e.g., monthly snapshots).
  4. Saves findings to data/mpoc/stock_comparison_probe.json.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

_BASE_URL = "https://mpoc.org.my/market-insight/stock-comparison/"
_VALIDATION_MARKER = "OILS AND FATS ENDING STOCKS"
_COUNTRY_PATTERN = re.compile(r"COUNTRY\s*:\s*([A-Z /&]+)", re.IGNORECASE)
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_OUT_PATH = Path(__file__).parent.parent.parent / "data" / "mpoc" / "stock_comparison_probe.json"


def _slug(country: str) -> str:
    return country.lower().strip().replace(" ", "-").replace("/", "-").replace("&", "and")


def main() -> None:
    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": _UA})

    results: dict = {}

    # -----------------------------------------------------------------------
    # Step 1: Main page
    # -----------------------------------------------------------------------
    print("Fetching main stock comparison page...")
    resp = session.get(_BASE_URL, timeout=30, allow_redirects=True)
    resp.raise_for_status()
    html = resp.text
    size_bytes = len(resp.content)

    marker_found = _VALIDATION_MARKER in html.upper()
    countries_raw = _COUNTRY_PATTERN.findall(html.upper())
    countries = [c.strip().title() for c in dict.fromkeys(countries_raw)]  # deduplicated, ordered

    print(f"  Status: {resp.status_code}  Size: {size_bytes:,} bytes")
    print(f"  Validation marker: {marker_found}")
    print(f"  Countries found: {countries}")

    results["main_page"] = {
        "url": _BASE_URL,
        "status_code": resp.status_code,
        "size_bytes": size_bytes,
        "validation_marker_found": marker_found,
        "countries": countries,
    }

    # -----------------------------------------------------------------------
    # Step 2: Check per-country sub-URLs
    # -----------------------------------------------------------------------
    print("\nChecking per-country sub-URLs...")
    sub_url_results = []
    for country in countries:
        slug = _slug(country)
        candidate_urls = [
            f"https://mpoc.org.my/market-insight/stock-comparison-{slug}/",
            f"https://mpoc.org.my/market-insight/stock-comparison/{slug}/",
        ]
        for url in candidate_urls:
            try:
                r = session.head(url, timeout=10, allow_redirects=True)
                if r.status_code == 200:
                    sub_url_results.append({"country": country, "url": url, "status": "found"})
                    print(f"  ✓ {country}: {url}")
                    break
            except Exception:
                pass
        else:
            sub_url_results.append({"country": country, "url": None, "status": "no_sub_url"})
            print(f"  — {country}: no sub-URL found")
        time.sleep(0.3)

    results["sub_url_check"] = sub_url_results

    # -----------------------------------------------------------------------
    # Step 3: Check for historical monthly archive pages
    # -----------------------------------------------------------------------
    print("\nChecking for historical archive pages...")
    archive_candidates = [
        "https://mpoc.org.my/market-insight/stock-comparison-archive/",
        "https://mpoc.org.my/market-insight/stock-comparison/archive/",
        "https://mpoc.org.my/category/stock-comparison/",
    ]
    archive_results = []
    for url in archive_candidates:
        try:
            r = session.head(url, timeout=10, allow_redirects=True)
            archive_results.append({"url": url, "status_code": r.status_code})
            print(f"  {r.status_code}  {url}")
        except Exception as exc:
            archive_results.append({"url": url, "error": str(exc)})
            print(f"  ERR  {url}  ({exc})")
        time.sleep(0.3)

    results["archive_check"] = archive_results

    # -----------------------------------------------------------------------
    # Save
    # -----------------------------------------------------------------------
    _OUT_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSaved → {_OUT_PATH}")


if __name__ == "__main__":
    main()
