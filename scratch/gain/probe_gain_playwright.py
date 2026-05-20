"""Playwright-based GAIN report crawler for fas.usda.gov.

Use this script ONLY if probe_gain_api.py exits with code 1 (API not
accessible).  Playwright launches a real Chromium browser so the JS-rendered
Drupal search page loads fully.

Strategy
--------
1. Intercept all XHR/fetch responses to discover whether Drupal is making
   a JSON API call internally.  If it is, we capture the endpoint and reuse
   it — much faster than scraping HTML.
2. If no JSON API is found, fall back to HTML scraping: paginate through
   search result cards, visit each landing page, extract PDF attachment URL.
3. Filter results to TARGET_COUNTRIES inline to avoid visiting irrelevant
   landing pages.

Output
------
  scratch/gain/crawl_results.jsonl   (one JSON record per report)

Usage
-----
Full crawl (all target countries, Coffee Annual + Semi-annual):
    python scratch/gain/probe_gain_playwright.py

Quick test (first 2 result pages only):
    python scratch/gain/probe_gain_playwright.py --limit-pages 2

Override search URL (if Drupal facet codes change):
    python scratch/gain/probe_gain_playwright.py --search-url "https://fas.usda.gov/data/gain?..."

Next step after success:
    python scratch/gain/build_manifest.py --source playwright
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

# ---------------------------------------------------------------------------
# Country config
# ---------------------------------------------------------------------------

# Map: USDA country name substrings (lowercase) → ISO 3166-1 alpha-2
# Multiple keys may map to the same ISO2 (name variations / USDA conventions)
COUNTRY_NAME_TO_ISO2: dict[str, str] = {
    "brazil": "BR",
    "colombia": "CO",
    "ethiopia": "ET",
    "vietnam": "VN",
    "viet nam": "VN",
    "indonesia": "ID",
    "honduras": "HN",
    "guatemala": "GT",
    "peru": "PE",
    "mexico": "MX",
    "uganda": "UG",
    "india": "IN",
    "tanzania": "TZ",
    "kenya": "KE",
    "cote d'ivoire": "CI",
    "côte d'ivoire": "CI",
    "ivory coast": "CI",
    "cameroon": "CM",
    "papua new guinea": "PG",
    "philippines": "PH",
    "laos": "LA",
    "lao p.d.r.": "LA",
    "lao pdr": "LA",
    "lao people": "LA",
}

TARGET_ISO2: set[str] = set(COUNTRY_NAME_TO_ISO2.values())

# ---------------------------------------------------------------------------
# URL patterns
# ---------------------------------------------------------------------------

# Search URL: GAIN reports filtered to coffee commodity.
# reports[0] = report type 10251 (GAIN/Attaché)
# reports[1] = commodity 609 (Coffee) — may need adjustment
_DEFAULT_SEARCH_URL = (
    "https://fas.usda.gov/data/search"
    "?reports%5B0%5D=report_type%3A10251"
    "&reports%5B1%5D=report_commodities%3A609"
)

# Regex to extract structured info from PDF filename
# e.g. "Coffee Annual_Nairobi_Kenya_KE2026-0011.pdf"
_PDF_FILENAME_RE = re.compile(
    r"(?P<category>[^_]+(?:\s[^_]+)*)"
    r"_(?P<post>[^_]+)"
    r"_(?P<country_name>[^_]+)"
    r"_(?P<report_id>[A-Z]{2}\d{4}-\d{4})"
    r"\.pdf$",
    re.IGNORECASE,
)

# Report ID in URL/text: e.g. "KE2026-0011"
_REPORT_ID_RE = re.compile(r"\b([A-Z]{2})(\d{4})-(\d{4})\b")

_OUT_PATH = Path(__file__).parent / "crawl_results.jsonl"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def country_name_to_iso2(name: str) -> str | None:
    """Map a country name (as it appears on FAS) to ISO2 code."""
    nl = name.lower().strip()
    for key, iso2 in COUNTRY_NAME_TO_ISO2.items():
        if key in nl:
            return iso2
    return None


def parse_pdf_filename(url: str) -> dict:
    """Extract structured metadata from a GAIN PDF URL/filename."""
    decoded = unquote(url)
    filename = decoded.split("/")[-1]
    m = _PDF_FILENAME_RE.match(filename)
    if m:
        return {
            "category": m.group("category").strip(),
            "post": m.group("post").strip(),
            "country_name_from_file": m.group("country_name").strip(),
            "report_id": m.group("report_id").upper(),
            "filename_clean": filename.replace(" ", "_"),
        }
    # Fallback: just return the filename
    rid_m = _REPORT_ID_RE.search(filename)
    return {
        "category": "",
        "post": "",
        "country_name_from_file": "",
        "report_id": rid_m.group(0) if rid_m else "",
        "filename_clean": filename.replace(" ", "_"),
    }


def normalize_pdf_url(href: str, base_url: str = "https://fas.usda.gov") -> str:
    """Ensure the PDF URL is absolute and normalise spaces."""
    url = urljoin(base_url, href)
    # Replace %20 → _ in the path component for S3 safety (keep query params intact)
    parsed = urlparse(url)
    clean_path = parsed.path  # leave encoded — unquote happens at manifest build time
    return url


# ---------------------------------------------------------------------------
# Captured JSON API responses
# ---------------------------------------------------------------------------

_captured_api: list[dict] = []  # populated by response interceptor


def _handle_response(response) -> None:
    """Playwright response interceptor — capture potential JSON API calls."""
    try:
        ct = response.headers.get("content-type", "")
        url = response.url
        if "json" not in ct:
            return
        # Only care about API-ish endpoints that could return report lists
        if not any(kw in url for kw in ["api", "views", "search", "report", "gain"]):
            return
        body = response.json()
        if not body:
            return
        # Quick check: does this look like a list of reports?
        records = body if isinstance(body, list) else (
            body.get("results") or body.get("reports") or body.get("data") or []
        )
        if records and isinstance(records[0], dict) and len(records[0]) > 3:
            _captured_api.append({
                "url": url,
                "records_count": len(records),
                "sample": records[0],
            })
            print(f"  [API] Intercepted JSON: {url}  ({len(records)} records)")
    except Exception:
        pass  # silently skip non-JSON or broken responses


# ---------------------------------------------------------------------------
# Scraping helpers
# ---------------------------------------------------------------------------

def extract_report_links(page) -> list[dict]:
    """Extract report landing-page links and metadata from a search results page."""
    results = []

    # Try multiple selectors — Drupal themes vary
    selectors = [
        "article.views-row",
        ".view-content .views-row",
        ".search-result",
        ".gain-report-item",
        "div[class*='views-row']",
    ]

    rows = []
    for sel in selectors:
        rows = page.query_selector_all(sel)
        if rows:
            break

    if not rows:
        # Fallback: grab all internal links that look like report pages
        anchors = page.query_selector_all("a[href*='/data/gain/']")
        for a in anchors:
            href = a.get_attribute("href") or ""
            if re.search(r"/data/gain/\d{4}/\d{2}/", href):
                title = a.inner_text().strip()
                results.append({
                    "landing_url": urljoin("https://fas.usda.gov", href),
                    "title": title,
                    "country_name": "",
                    "date_text": "",
                })
        return results

    for row in rows:
        link_el = (
            row.query_selector("h3 a") or
            row.query_selector("h2 a") or
            row.query_selector(".views-field-title a") or
            row.query_selector("a")
        )
        if not link_el:
            continue

        href = link_el.get_attribute("href") or ""
        title = link_el.inner_text().strip()

        # Country name: look for a dedicated field, or infer from title
        country_el = (
            row.query_selector(".views-field-field-country") or
            row.query_selector(".country") or
            row.query_selector("[class*='country']")
        )
        country_name = country_el.inner_text().strip() if country_el else ""

        # Date text
        date_el = (
            row.query_selector("time") or
            row.query_selector(".date-display-single") or
            row.query_selector(".views-field-field-report-date") or
            row.query_selector("[class*='date']")
        )
        date_text = date_el.inner_text().strip() if date_el else ""

        results.append({
            "landing_url": urljoin("https://fas.usda.gov", href),
            "title": title,
            "country_name": country_name,
            "date_text": date_text,
        })

    return results


def scrape_landing_page(page, landing_url: str) -> dict | None:
    """Visit a report landing page and extract PDF URL + metadata."""
    try:
        page.goto(landing_url, timeout=20_000, wait_until="domcontentloaded")
    except Exception as exc:
        print(f"    [WARN] Failed to load {landing_url}: {exc}")
        return None

    # Find PDF link — try several patterns
    pdf_href = None
    for sel in [
        "a[href*='gain-report'][href$='.pdf']",
        "a[href*='.pdf']",
        "a[href*='sites/default/files'][href*='pdf']",
        ".field--name-field-report-file a",
        ".field--name-field-report-attachments a",
        "[class*='attachment'] a",
        "[class*='file'] a",
    ]:
        el = page.query_selector(sel)
        if el:
            href = el.get_attribute("href") or ""
            if href:
                pdf_href = href
                break

    if not pdf_href:
        # Last resort: scan all anchors for PDF-looking URLs
        for el in page.query_selector_all("a"):
            href = el.get_attribute("href") or ""
            if href.lower().endswith(".pdf"):
                pdf_href = href
                break

    if not pdf_href:
        print(f"    [WARN] No PDF found on {landing_url}")
        return None

    pdf_url = normalize_pdf_url(pdf_href)

    # Publication date from <time> element or <meta>
    pub_date_raw = ""
    time_el = page.query_selector("time[datetime]")
    if time_el:
        pub_date_raw = time_el.get_attribute("datetime") or time_el.inner_text()
    else:
        meta_el = page.query_selector("meta[property='article:published_time']")
        if meta_el:
            pub_date_raw = meta_el.get_attribute("content") or ""

    # Country name from meta or content
    country_name = ""
    for sel in [
        ".field--name-field-country .field__item",
        "[class*='country'] .field__item",
        ".gain-country",
    ]:
        el = page.query_selector(sel)
        if el:
            country_name = el.inner_text().strip()
            break

    return {
        "landing_url": landing_url,
        "pdf_url": pdf_url,
        "pub_date_raw": pub_date_raw,
        **parse_pdf_filename(pdf_url),
        "country_name_page": country_name,
    }


# ---------------------------------------------------------------------------
# Main crawl
# ---------------------------------------------------------------------------

def crawl(
    search_url: str,
    limit_pages: int | None,
    sleep_between: float,
) -> int:
    """Crawl GAIN search results with Playwright. Returns number of records saved."""
    from playwright.sync_api import sync_playwright  # local import (optional dep)

    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    saved = 0
    skipped_country = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        # Intercept responses to look for hidden JSON API
        context.on("response", _handle_response)  # type: ignore[arg-type]

        search_page = context.new_page()
        detail_page = context.new_page()

        with open(_OUT_PATH, "w", encoding="utf-8") as fh:
            page_num = 0
            current_url = search_url

            while True:
                page_num += 1
                if limit_pages and page_num > limit_pages:
                    print(f"\n  --limit-pages {limit_pages} reached, stopping.")
                    break

                paged_url = (
                    current_url if page_num == 1
                    else f"{search_url}&page={page_num - 1}"
                )
                print(f"\n[Page {page_num}] {paged_url}")

                try:
                    search_page.goto(paged_url, timeout=30_000, wait_until="networkidle")
                except Exception as exc:
                    print(f"  [ERROR] Failed to load page: {exc}")
                    break

                # If this is page 1, report any intercepted JSON APIs
                if page_num == 1 and _captured_api:
                    print(f"\n  *** Discovered {len(_captured_api)} internal JSON API call(s) ***")
                    for cap in _captured_api:
                        print(f"    - {cap['url']}  ({cap['records_count']} records)")
                    print("  Consider using probe_gain_api.py with these endpoints.\n")

                links = extract_report_links(search_page)
                print(f"  Found {len(links)} result cards")

                if not links:
                    print("  No results — end of pagination.")
                    break

                for link_info in links:
                    landing_url = link_info["landing_url"]
                    title = link_info.get("title", "")
                    country_name = link_info.get("country_name", "")

                    # Country filter: use page-level country name if available,
                    # otherwise defer to PDF filename parsing (done in scrape_landing_page)
                    if country_name:
                        iso2 = country_name_to_iso2(country_name)
                        if iso2 is None:
                            skipped_country += 1
                            continue

                    print(f"  → {title or landing_url}")

                    record = scrape_landing_page(detail_page, landing_url)
                    if record is None:
                        continue

                    # Re-check country filter using PDF filename data
                    iso2_from_file = None
                    cname_candidates = [
                        record.get("country_name_from_file", ""),
                        record.get("country_name_page", ""),
                        country_name,
                    ]
                    for cname in cname_candidates:
                        if cname:
                            iso2_from_file = country_name_to_iso2(cname)
                            if iso2_from_file:
                                break

                    # If country unresolvable, check report_id prefix
                    if not iso2_from_file and record.get("report_id"):
                        rid_prefix = record["report_id"][:2].upper()
                        if rid_prefix in TARGET_ISO2:
                            iso2_from_file = rid_prefix

                    if not iso2_from_file:
                        skipped_country += 1
                        continue

                    record["country_iso2"] = iso2_from_file
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                    saved += 1
                    print(f"    ✓ Saved ({iso2_from_file}) {record.get('report_id', '?')}")

                    time.sleep(sleep_between)

                # Check if there's a "next page" link
                next_el = search_page.query_selector("a[rel='next'], .pager__item--next a, li.next a")
                if not next_el:
                    print("\n  No next-page link — end of results.")
                    break

                time.sleep(sleep_between)

        browser.close()

    print(f"\nCrawl complete. Saved: {saved}, Skipped (out-of-country): {skipped_country}")
    print(f"Output: {_OUT_PATH}")
    return saved


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Playwright GAIN coffee report crawler for fas.usda.gov."
    )
    parser.add_argument(
        "--search-url",
        default=_DEFAULT_SEARCH_URL,
        help="Starting search URL (default: GAIN + Coffee commodity facets).",
    )
    parser.add_argument(
        "--limit-pages",
        type=int,
        default=None,
        metavar="N",
        help="Stop after N search result pages (for testing, e.g. --limit-pages 2).",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.5,
        metavar="SECONDS",
        help="Seconds to wait between requests (default: 1.5).",
    )
    args = parser.parse_args()

    print("USDA GAIN Playwright Crawler")
    print(f"Search URL: {args.search_url}")
    if args.limit_pages:
        print(f"Limit: {args.limit_pages} pages")
    print(f"Target countries: {sorted(TARGET_ISO2)}")
    print()

    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        print("ERROR: playwright is not installed.")
        print("Install it with:  pip install playwright  &&  playwright install chromium")
        raise SystemExit(1)

    n = crawl(args.search_url, args.limit_pages, args.sleep)
    if n == 0:
        print("\nWARNING: No records saved. Check the search URL or selectors.")
        raise SystemExit(1)
    else:
        print(f"\nNext step: python scratch/gain/build_manifest.py --source playwright")


if __name__ == "__main__":
    main()
