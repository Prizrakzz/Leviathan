"""Fast HTTP-only GAIN coffee report crawler using curl_cffi + BeautifulSoup.

No browser required — fas.usda.gov search results are server-side rendered.
WAF bypass is handled by curl_cffi impersonating Chrome 124.

Usage
-----
Quick test (first 2 listing pages, no landing-page fetches):
    python scratch/gain/probe_gain_http.py --limit-pages 2 --skip-landing

Full crawl (all pages, visits landing pages for PDF URLs):
    python scratch/gain/probe_gain_http.py

Output
------
  scratch/gain/crawl_results.jsonl   (one JSON record per report)

Next step:
    python scratch/gain/build_manifest.py --source playwright
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup
from curl_cffi import requests as cr

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_IMPERSONATE = "chrome124"
_BASE_URL = "https://fas.usda.gov"
_SEARCH_URL = (
    "https://fas.usda.gov/data/search"
    "?reports%5B0%5D=report_type%3A10251"   # Attaché Report (GAIN)
    "&reports%5B1%5D=report_commodities%3A609"  # Coffee commodity
)

_OUT_PATH = Path(__file__).parent / "crawl_results.jsonl"

# ---------------------------------------------------------------------------
# Country mapping  (title substring → ISO2)
# ---------------------------------------------------------------------------

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
# HTTP helpers
# ---------------------------------------------------------------------------


def _make_session() -> cr.Session:
    sess = cr.Session()
    sess.headers.update({
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://fas.usda.gov/",
    })
    return sess


def _get_html(sess: cr.Session, url: str, retries: int = 2) -> str | None:
    for attempt in range(retries + 1):
        try:
            r = sess.get(url, impersonate=_IMPERSONATE, timeout=30, allow_redirects=True)
            if r.status_code == 200:
                return r.text
            print(f"  [WARN] HTTP {r.status_code} for {url}")
            return None
        except Exception as exc:
            if attempt == retries:
                print(f"  [ERROR] {url}: {exc}")
                return None
            time.sleep(2)
    return None


# ---------------------------------------------------------------------------
# Parse listing page
# ---------------------------------------------------------------------------


def _parse_listing(html: str) -> list[dict]:
    """Extract report cards from a search result listing page."""
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".c-card")
    results = []

    for card in cards:
        link_el = card.select_one(".c-card__url")
        title_el = card.select_one(".c-card__title")
        time_el = card.select_one("time[datetime]")

        if not link_el or not title_el:
            continue

        href = link_el.get("href", "")
        title = title_el.get_text(strip=True)
        landing_url = urljoin(_BASE_URL, href)
        datetime_str = time_el.get("datetime", "") if time_el else ""
        date_text = time_el.get_text(strip=True) if time_el else ""

        results.append({
            "landing_url": landing_url,
            "title": title,
            "datetime_str": datetime_str,
            "date_text": date_text,
        })

    return results


def _has_next_page(html: str) -> bool:
    """Return True if there's a next-page link in the pagination."""
    soup = BeautifulSoup(html, "html.parser")
    # Drupal pager: look for a link with rel=next or .pager__item--next
    return bool(
        soup.select_one("a[rel='next']")
        or soup.select_one(".pager__item--next a")
        or soup.select_one("li.next a")
    )


# ---------------------------------------------------------------------------
# Country extraction from card title
# ---------------------------------------------------------------------------


def _iso2_from_title(title: str) -> str | None:
    """Extract ISO2 from 'Country: Report Category' format."""
    # Title format: "Kenya: Coffee Annual" or "Indonesia: Coffee Semi-annual"
    country_part = title.split(":")[0].strip().lower() if ":" in title else title.lower()
    for key, iso2 in COUNTRY_NAME_TO_ISO2.items():
        if key in country_part:
            return iso2
    return None


def _category_from_title(title: str) -> str:
    """Extract category from 'Country: Category'."""
    if ":" in title:
        return title.split(":", 1)[1].strip()
    return title.strip()


# ---------------------------------------------------------------------------
# Parse landing page
# ---------------------------------------------------------------------------

_REPORT_ID_RE = re.compile(r"\b([A-Z]{2})(\d{4})-(\d{4})\b")
_PDF_FILENAME_RE = re.compile(
    r"(?P<category>[^_]+(?:\s[^_]+)*)"
    r"_(?P<post>[^_]+)"
    r"_(?P<country_name>[^_]+)"
    r"_(?P<report_id>[A-Z]{2}\d{4}-\d{4})"
    r"\.pdf$",
    re.IGNORECASE,
)


def _parse_landing_page(html: str, landing_url: str) -> dict | None:
    """Extract PDF URL and metadata from a GAIN report landing page."""
    soup = BeautifulSoup(html, "html.parser")

    # PDF link: href contains /data/gain-report/ or ends in .pdf
    pdf_el = (
        soup.select_one("a[href*='gain-report']")
        or soup.select_one("a[href$='.pdf']")
    )
    if not pdf_el:
        return None

    pdf_href = pdf_el.get("href", "")
    pdf_url = urljoin(_BASE_URL, pdf_href)
    decoded = unquote(pdf_url)
    filename = decoded.rstrip("/").split("/")[-1]
    filename_clean = filename.replace(" ", "_")

    # Parse structured fields from filename
    post = ""
    country_name_in_url = ""
    report_id = ""
    category_from_file = ""

    m = _PDF_FILENAME_RE.match(filename)
    if m:
        category_from_file = m.group("category").strip()
        post = m.group("post").strip()
        country_name_in_url = m.group("country_name").strip()
        report_id = m.group("report_id").upper()
    else:
        rid_m = _REPORT_ID_RE.search(filename)
        if rid_m:
            report_id = rid_m.group(0)

    return {
        "pdf_url": pdf_url,
        "filename_clean": filename_clean,
        "post": post,
        "country_name_in_url": country_name_in_url,
        "report_id": report_id,
        "category_from_file": category_from_file,
    }


# ---------------------------------------------------------------------------
# Main crawl
# ---------------------------------------------------------------------------


def crawl(
    limit_pages: int | None,
    skip_landing: bool,
    sleep_listing: float,
    sleep_landing: float,
) -> int:
    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    saved = 0
    skipped_country = 0
    page_num = 0

    with cr.Session() as sess, open(_OUT_PATH, "w", encoding="utf-8") as fh:
        sess.headers.update({
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://fas.usda.gov/",
        })

        while True:
            if limit_pages and page_num >= limit_pages:
                print(f"\n--limit-pages {limit_pages} reached.")
                break

            page_url = _SEARCH_URL if page_num == 0 else f"{_SEARCH_URL}&page={page_num}"
            print(f"\n[Page {page_num + 1}] {page_url}")

            html = _get_html(sess, page_url)
            if not html:
                break

            cards = _parse_listing(html)
            print(f"  Cards: {len(cards)}")

            if not cards:
                print("  No cards — end of results.")
                break

            for card in cards:
                title = card["title"]
                iso2 = _iso2_from_title(title)

                if not iso2:
                    skipped_country += 1
                    continue

                category = _category_from_title(title)

                # Date: "2026-05-18T15:00:00Z" → "20260518"
                dt_str = card["datetime_str"]
                pub_date = dt_str[:10].replace("-", "") if dt_str else ""

                record = {
                    "landing_url": card["landing_url"],
                    "title": title,
                    "country_iso2": iso2,
                    "category": category,
                    "publication_date": pub_date,
                    "pdf_url": "",
                    "post": "",
                    "country_name_in_url": "",
                    "report_id": "",
                    "filename_clean": "",
                }

                if skip_landing:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                    saved += 1
                    print(f"  ✓ {iso2}  {pub_date}  {title}")
                    continue

                # Fetch landing page for PDF URL
                lp_html = _get_html(sess, card["landing_url"])
                if lp_html:
                    lp_data = _parse_landing_page(lp_html, card["landing_url"])
                    if lp_data:
                        record.update(lp_data)
                        # Override category from filename if available
                        if lp_data.get("category_from_file"):
                            record["category"] = lp_data["category_from_file"]

                if record["pdf_url"]:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                    saved += 1
                    print(
                        f"  ✓ {iso2}  {pub_date}  {record['report_id'] or title}  "
                        f"→ {record['pdf_url'].split('/')[-1]}"
                    )
                else:
                    print(f"  ✗ No PDF for {title} ({card['landing_url']})")

                time.sleep(sleep_landing)

            # Check for next page
            if not _has_next_page(html):
                print("\nNo next-page link — end of results.")
                break

            page_num += 1
            time.sleep(sleep_listing)

    print(f"\nDone. Saved: {saved}, Skipped (non-target country): {skipped_country}")
    print(f"Output: {_OUT_PATH}")
    return saved


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fast HTTP GAIN coffee crawler (curl_cffi + BeautifulSoup, no browser)."
    )
    parser.add_argument(
        "--limit-pages",
        type=int,
        default=None,
        metavar="N",
        help="Stop after N listing pages (for testing, e.g. --limit-pages 2).",
    )
    parser.add_argument(
        "--skip-landing",
        action="store_true",
        help="Skip fetching landing pages (records will have empty pdf_url). For structure testing.",
    )
    parser.add_argument(
        "--sleep-listing",
        type=float,
        default=1.5,
        help="Sleep seconds between listing page fetches (default: 1.5).",
    )
    parser.add_argument(
        "--sleep-landing",
        type=float,
        default=1.0,
        help="Sleep seconds between landing page fetches (default: 1.0).",
    )
    args = parser.parse_args()

    print("USDA GAIN HTTP Crawler (curl_cffi + BeautifulSoup)")
    print(f"Search URL: {_SEARCH_URL}")
    if args.limit_pages:
        print(f"Limit: {args.limit_pages} pages")
    print(f"Target countries: {sorted(TARGET_ISO2)}")
    print()

    n = crawl(
        limit_pages=args.limit_pages,
        skip_landing=args.skip_landing,
        sleep_listing=args.sleep_listing,
        sleep_landing=args.sleep_landing,
    )

    if n == 0:
        print("\nWARNING: No records saved. Check the search URL or HTML structure.")
        raise SystemExit(1)

    print(f"\nNext step: python scratch/gain/build_manifest.py --source playwright")


if __name__ == "__main__":
    main()
