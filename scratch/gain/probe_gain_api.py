"""Probe the USDA FAS GAIN JSON API (apps.fas.usda.gov/newgainapi).

The FAS search UI is JS-heavy (Drupal).  Before spinning up Playwright for a
full crawl, this script checks whether the backend JSON API is accessible with
the same curl_cffi WAF bypass we use for WMT downloads.

If the API returns valid report data with PDF attachment URLs we can paginate
it directly — no browser required.

Usage
-----
Quick probe (checks 1 page, prints findings):
    python scratch/gain/probe_gain_api.py

Full run (paginates all pages, saves JSONL for build_manifest.py):
    python scratch/gain/probe_gain_api.py --save

Exit codes
----------
0  API works and found records
1  API unreachable or returned no records → fall back to probe_gain_playwright.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from curl_cffi import requests as curl_requests

_IMPERSONATE = "chrome124"
_OUT_PATH = Path(__file__).parent / "api_results.jsonl"

# Target countries: 18 major coffee-producing nations (ISO 3166-1 alpha-2).
# We save ALL records during the probe but note which ones are in scope.
TARGET_COUNTRIES: set[str] = {
    "BR", "CO", "ET", "VN", "ID", "HN", "GT", "PE", "MX",
    "UG", "IN", "TZ", "KE", "CI", "CM", "PG", "PH", "LA",
}

# Known GAIN report categories for coffee
COFFEE_CATEGORIES = ["Coffee Annual", "Coffee Semi-annual", "Tropical Products Annual"]

_NEWGAIN_BASE = "https://apps.fas.usda.gov/newgainapi/api/Report/GetReportByQuery"

# Commodity codes to try (HS + USDA internal codes)
_COMMODITY_CODES = [
    "0813",   # HS code for coffee (green, roasted, extracts)
    "0901",   # HS code for coffee (unroasted)
    "Coffee", # text search fallback
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session() -> curl_requests.Session:
    session = curl_requests.Session()
    session.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://fas.usda.gov/",
        "Origin": "https://fas.usda.gov",
    })
    return session


def _try_endpoint(
    session: curl_requests.Session,
    url: str,
    params: dict,
    label: str,
) -> dict | list | None:
    """GET url+params, return parsed JSON or None on failure."""
    print(f"\n  Trying {label}")
    print(f"    URL: {url}")
    print(f"    Params: {params}")
    try:
        resp = session.get(url, params=params, impersonate=_IMPERSONATE, timeout=30)
        print(f"    Status: {resp.status_code}")
        ct = resp.headers.get("content-type", "")
        print(f"    Content-Type: {ct}")

        if resp.status_code != 200:
            print(f"    → FAILED (non-200)")
            print(f"    Body: {resp.text[:200]}")
            return None

        if "json" not in ct and not resp.text.strip().startswith(("[", "{")):
            print(f"    → Response is HTML/text, not JSON")
            print(f"    Body: {resp.text[:200]}")
            return None

        data = resp.json()
        return data

    except Exception as exc:
        print(f"    → ERROR: {exc}")
        return None


# ---------------------------------------------------------------------------
# Phase A: newgainapi
# ---------------------------------------------------------------------------

def probe_newgainapi(session: curl_requests.Session) -> tuple[bool, dict | None]:
    """Try the newgainapi for Coffee Annual reports.

    Returns (success, endpoint_config) where endpoint_config holds the working
    params so we can reuse them for pagination.
    """
    print("\n" + "=" * 60)
    print("Phase A: apps.fas.usda.gov/newgainapi")
    print("=" * 60)

    for cat in ["Coffee Annual", "Coffee Semi-annual"]:
        for code in _COMMODITY_CODES[:2]:  # just the numeric ones first
            params = {
                "commodityCode": code,
                "reportCategoryList": cat,
                "languageCode": "EN",
                "pageNum": "1",
                "pageSize": "5",
            }
            data = _try_endpoint(
                session,
                _NEWGAIN_BASE,
                params,
                label=f"newgainapi commodityCode={code} category={cat!r}",
            )
            if data is None:
                continue

            records = data if isinstance(data, list) else (
                data.get("results") or data.get("reports") or data.get("data") or []
            )
            if not records:
                print(f"    → Empty records list")
                continue

            print(f"    → SUCCESS! Got {len(records)} records on page 1")
            print(f"    First record keys: {list(records[0].keys())}")

            # Check for PDF attachment URL
            first = records[0]
            attachments = first.get("Attachments") or first.get("attachments") or []
            if attachments:
                print(f"    Attachment sample: {attachments[0]}")
            else:
                print(f"    No 'Attachments' key found. All keys: {list(first.keys())}")
                print(f"    Sample record: {json.dumps(first, indent=2)[:600]}")

            return True, {
                "url": _NEWGAIN_BASE,
                "commodityCode": code,
                "reportCategoryList": cat,
            }

    # Try without commodityCode filter (text-based search)
    params = {
        "searchText": "Coffee Annual",
        "languageCode": "EN",
        "pageNum": "1",
        "pageSize": "5",
    }
    data = _try_endpoint(session, _NEWGAIN_BASE, params, label="newgainapi searchText")
    if data is not None:
        records = data if isinstance(data, list) else list(data.values())[0] if data else []
        if records:
            print(f"    → Partial success with searchText. Sample: {str(records[0])[:300]}")
            return True, {"url": _NEWGAIN_BASE, "searchText": "Coffee Annual"}

    return False, None


# ---------------------------------------------------------------------------
# Phase B: Alternate GAIN endpoints
# ---------------------------------------------------------------------------

def probe_alternate_endpoints(session: curl_requests.Session) -> bool:
    """Try other potential GAIN JSON endpoints."""
    print("\n" + "=" * 60)
    print("Phase B: Alternate endpoints")
    print("=" * 60)

    candidates = [
        (
            "https://apps.fas.usda.gov/newgainapi/api/Report/GetReportsByProduct",
            {"productCode": "0813", "reportCategoryList": "Coffee Annual",
             "languageCode": "EN", "pageNum": "1", "pageSize": "5"},
            "GetReportsByProduct",
        ),
        (
            "https://apps.fas.usda.gov/newgainapi/api/Report/GetRecentReports",
            {"pageNum": "1", "pageSize": "5"},
            "GetRecentReports",
        ),
        (
            "https://apps.fas.usda.gov/newgainapi/api/ReportCategory/AllReportCategory",
            {},
            "AllReportCategory (list of categories)",
        ),
        (
            "https://apps.fas.usda.gov/newgainapi/api/Report/GetCountriesWithReports",
            {},
            "GetCountriesWithReports",
        ),
    ]

    for url, params, label in candidates:
        data = _try_endpoint(session, url, params, label=label)
        if data is not None and data:
            print(f"    → Non-empty response! Type={type(data).__name__}")
            preview = json.dumps(data, indent=2)[:400]
            print(f"    Preview: {preview}")
            return True

    return False


# ---------------------------------------------------------------------------
# Full pagination
# ---------------------------------------------------------------------------

def paginate_and_save(
    session: curl_requests.Session,
    endpoint_cfg: dict,
    categories: list[str] | None = None,
) -> int:
    """Paginate all coffee GAIN reports from the working endpoint and save to JSONL."""
    if categories is None:
        categories = COFFEE_CATEGORIES

    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    saved = 0

    with open(_OUT_PATH, "w", encoding="utf-8") as fh:
        for category in categories:
            print(f"\n  Paginating category: {category!r}")
            page = 1
            while True:
                params = {
                    **{k: v for k, v in endpoint_cfg.items() if k != "url"},
                    "reportCategoryList": category,
                    "languageCode": "EN",
                    "pageNum": str(page),
                    "pageSize": "50",
                }
                resp = session.get(
                    endpoint_cfg["url"],
                    params=params,
                    impersonate=_IMPERSONATE,
                    timeout=30,
                )
                if resp.status_code != 200:
                    print(f"    Page {page}: HTTP {resp.status_code} — stopping")
                    break

                data = resp.json()
                records = data if isinstance(data, list) else (
                    data.get("results") or data.get("reports") or data.get("data") or []
                )
                if not records:
                    print(f"    Page {page}: empty — done with {category!r}")
                    break

                for record in records:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                    saved += 1

                print(f"    Page {page}: {len(records)} records (total: {saved})")

                if len(records) < 50:
                    break

                page += 1
                time.sleep(1.0)

    print(f"\nSaved {saved} records to {_OUT_PATH}")
    return saved


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Probe USDA GAIN JSON API. Exit 0=success, 1=not found."
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Paginate all results and save to scratch/gain/api_results.jsonl",
    )
    args = parser.parse_args()

    with _make_session() as session:
        success, endpoint_cfg = probe_newgainapi(session)

        if not success:
            success = probe_alternate_endpoints(session)

        print("\n" + "=" * 60)
        if success and endpoint_cfg:
            print("RESULT: API accessible ✓")
            if args.save:
                n = paginate_and_save(session, endpoint_cfg)
                print(f"\nNext step: python scratch/gain/build_manifest.py --source api")
            else:
                print("Run with --save to collect all records.")
                print("Then: python scratch/gain/build_manifest.py --source api")
            sys.exit(0)
        elif success:
            print("RESULT: API partially accessible but no usable endpoint found.")
            print("Fall back: python scratch/gain/probe_gain_playwright.py")
            sys.exit(1)
        else:
            print("RESULT: API not accessible (all endpoints returned 404 / HTML).")
            print("Fall back: python scratch/gain/probe_gain_playwright.py")
            sys.exit(1)
        print("=" * 60)


if __name__ == "__main__":
    main()
