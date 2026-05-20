"""Discover FAS GAIN commodity filter IDs from the search-page sidebar.

fas.usda.gov is SSR (server-side rendered) — the filter sidebar with
commodity facets is present in the raw HTML. curl_cffi bypasses the TLS
fingerprint WAF that blocks plain Python requests.

Output
------
  scratch/gain/commodity_ids.json   {commodity_name: id, ...}

Usage
-----
    python scratch/gain/probe_gain_commodity_ids.py
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from bs4 import BeautifulSoup
from curl_cffi import requests as cr

_IMPERSONATE = "chrome124"
_GAIN_SEARCH_URL = (
    "https://fas.usda.gov/data/search"
    "?reports%5B0%5D=report_type%3A10251"   # Attaché Report (GAIN) only, no commodity filter
)
_OUT_PATH = Path(__file__).parent / "commodity_ids.json"

# Regex to pull the numeric ID from href like:
#   /data/search?reports[0]=report_type:10251&reports[1]=report_commodities:609
_COMMODITY_ID_RE = re.compile(r"report_commodities%3A(\d+)|report_commodities:(\d+)")


def _fetch(url: str, retries: int = 3) -> str | None:
    with cr.Session() as sess:
        sess.headers.update({
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://fas.usda.gov/",
        })
        for attempt in range(retries):
            try:
                r = sess.get(url, impersonate=_IMPERSONATE, timeout=30, allow_redirects=True)
                if r.status_code == 200:
                    return r.text
                print(f"  [WARN] HTTP {r.status_code}")
            except Exception as exc:
                print(f"  [WARN] Attempt {attempt + 1}: {exc}")
                if attempt < retries - 1:
                    time.sleep(3)
    return None


def discover() -> dict[str, int]:
    """Fetch the GAIN search page and extract all commodity filter IDs."""
    print(f"Fetching: {_GAIN_SEARCH_URL}")
    html = _fetch(_GAIN_SEARCH_URL)
    if not html:
        raise RuntimeError("Failed to fetch GAIN search page.")

    soup = BeautifulSoup(html, "html.parser")

    # Sidebar commodity filter links have href containing report_commodities:NNN
    # They appear as: <a href="/data/search?reports[0]=...&reports[1]=report_commodities:609">Coffee (1247)</a>
    commodity_map: dict[str, int] = {}

    # Look for all anchor tags whose href contains "report_commodities"
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        m = _COMMODITY_ID_RE.search(href)
        if not m:
            continue
        cid = int(m.group(1) or m.group(2))
        # Clean up label text: "Coffee (1,247)" → "Coffee"
        label = a.get_text(strip=True)
        label = re.sub(r"\s*\(\d[\d,]*\)\s*$", "", label).strip()
        if label:
            commodity_map[label] = cid

    return commodity_map


def main() -> None:
    commodity_map = discover()

    if not commodity_map:
        print("\nWARNING: No commodity IDs found.")
        print("The filter sidebar may not be in the SSR HTML for this page.")
        print("Try fetching a page that has an active commodity filter applied.")
        raise SystemExit(1)

    # Sort by ID for readability
    sorted_map = dict(sorted(commodity_map.items(), key=lambda x: x[1]))

    print(f"\nFound {len(sorted_map)} commodity filter IDs:")
    for name, cid in sorted_map.items():
        print(f"  {cid:>6}  {name}")

    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(sorted_map, fh, indent=2, ensure_ascii=False)

    print(f"\nSaved: {_OUT_PATH}")

    # Print the specific IDs we care about
    targets = [
        "Corn", "Maize", "Wheat", "Soybeans", "Soybean Oil", "Soybean Meal",
        "Palm Oil", "Rapeseed", "Canola", "Sugar", "Cotton", "Cocoa", "Rice",
        "Coffee",
    ]
    print("\nTarget commodity IDs (partial match):")
    for target in targets:
        for name, cid in sorted_map.items():
            if target.lower() in name.lower():
                print(f"  {target:20s} → {cid:>6}  (matched: '{name}')")
                break


if __name__ == "__main__":
    main()
