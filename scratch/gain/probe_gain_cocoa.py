"""Dedicated GAIN Cocoa crawler.

Cocoa is not in the FAS GAIN taxonomy sidebar (no commodity ID), so we cannot use
the commodity filter. This script paginates all GAIN reports (47,000+ total) filtered
by title substring "cocoa" and target countries (CI, GH, CM, ID, NG, EC, PE).

Strategy for efficiency:
- Start from page 0 (newest first — FAS sorts newest-first)
- Keep paginating while new cocoa records are found
- Bail out once we see N consecutive pages with zero cocoa matches
  (because GAIN titles always start with "Country: Category", cocoa reports
   clump by country. Once we're past the cocoa report date range, gaps appear.)

Usage
-----
    python scratch/gain/probe_gain_cocoa.py --output scratch/gain/crawl_cocoa.jsonl

    # Limit test:
    python scratch/gain/probe_gain_cocoa.py --limit-pages 20 --skip-landing
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

_IMPERSONATE = "chrome124"
_BASE_URL = "https://fas.usda.gov"
_SEARCH_URL = (
    "https://fas.usda.gov/data/search"
    "?reports%5B0%5D=report_type%3A10251"  # GAIN only, no commodity filter
)

_TARGET_COUNTRIES = {"CI", "GH", "CM", "ID", "NG", "EC", "PE"}
_TITLE_FILTER = "cocoa"

# Stop when this many consecutive pages have zero cocoa matches
_MAX_EMPTY_PAGES_IN_A_ROW = 15

COUNTRY_NAME_TO_ISO2: dict[str, str] = {
    "cote d'ivoire": "CI",
    "côte d'ivoire": "CI",
    "ivory coast": "CI",
    "ghana": "GH",
    "cameroon": "CM",
    "indonesia": "ID",
    "nigeria": "NG",
    "ecuador": "EC",
    "peru": "PE",
    # Belt: also catch these if they show up
    "brazil": "BR",
    "colombia": "CO",
    "dominican republic": "DO",
}


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


def _parse_listing(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for card in soup.select(".c-card"):
        link_el = card.select_one(".c-card__url")
        title_el = card.select_one(".c-card__title")
        time_el = card.select_one("time[datetime]")
        if not link_el or not title_el:
            continue
        href = link_el.get("href", "")
        results.append({
            "landing_url": urljoin(_BASE_URL, href),
            "title": title_el.get_text(strip=True),
            "datetime_str": time_el.get("datetime", "") if time_el else "",
        })
    return results


def _has_next_page(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    return bool(
        soup.select_one("a[rel='next']")
        or soup.select_one(".pager__item--next a")
        or soup.select_one("li.next a")
    )


def _iso2_from_title(title: str) -> str | None:
    part = title.split(":")[0].strip().lower() if ":" in title else title.lower()
    for key, iso2 in COUNTRY_NAME_TO_ISO2.items():
        if key in part:
            return iso2
    return None


_PDF_RE = re.compile(r"\b([A-Z]{2})(\d{4})-(\d{4})\b")


def _parse_landing(html: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    pdf_el = (
        soup.select_one("a[href*='gain-report']")
        or soup.select_one("a[href$='.pdf']")
    )
    if not pdf_el:
        return None
    pdf_url = urljoin(_BASE_URL, pdf_el.get("href", ""))
    decoded = unquote(pdf_url)
    filename = decoded.rstrip("/").split("/")[-1].replace(" ", "_")
    report_id = ""
    m = _PDF_RE.search(filename)
    if m:
        report_id = m.group(0)
    return {"pdf_url": pdf_url, "filename_clean": filename, "report_id": report_id}


def crawl(
    limit_pages: int | None,
    skip_landing: bool,
    sleep_listing: float,
    sleep_landing: float,
    out_path: Path,
) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    saved = 0
    page_num = 0
    empty_run = 0

    with cr.Session() as sess, open(out_path, "w", encoding="utf-8") as fh:
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

            page_cocoa = 0
            for card in cards:
                title = card["title"]
                if _TITLE_FILTER not in title.lower():
                    continue
                iso2 = _iso2_from_title(title)
                if not iso2 or iso2 not in _TARGET_COUNTRIES:
                    continue

                dt_str = card["datetime_str"]
                pub_date = dt_str[:10].replace("-", "") if dt_str else ""
                category = title.split(":", 1)[1].strip() if ":" in title else title

                record: dict = {
                    "landing_url": card["landing_url"],
                    "title": title,
                    "country_iso2": iso2,
                    "category": category,
                    "publication_date": pub_date,
                    "pdf_url": "",
                    "filename_clean": "",
                    "report_id": "",
                }

                if not skip_landing:
                    lp_html = _get_html(sess, card["landing_url"])
                    if lp_html:
                        lp = _parse_landing(lp_html)
                        if lp:
                            record.update(lp)
                    time.sleep(sleep_landing)

                if skip_landing or record["pdf_url"]:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                    saved += 1
                    page_cocoa += 1
                    print(
                        f"  [OK] {iso2}  {pub_date}  {record.get('report_id') or title}"
                        + (f"  -> {record['pdf_url'].split('/')[-1]}" if record["pdf_url"] else "")
                    )

            if page_cocoa == 0:
                empty_run += 1
                print(f"  (no cocoa matches — empty run {empty_run}/{_MAX_EMPTY_PAGES_IN_A_ROW})")
                if empty_run >= _MAX_EMPTY_PAGES_IN_A_ROW:
                    print(f"\n{_MAX_EMPTY_PAGES_IN_A_ROW} consecutive empty pages — stopping.")
                    break
            else:
                empty_run = 0

            if not _has_next_page(html):
                print("\nNo next-page link — end of results.")
                break

            page_num += 1
            time.sleep(sleep_listing)

    print(f"\nDone. Saved: {saved}")
    print(f"Output: {out_path}")
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description="GAIN Cocoa crawler (no taxonomy ID — title filter).")
    parser.add_argument("--output", default="scratch/gain/crawl_cocoa.jsonl")
    parser.add_argument("--limit-pages", type=int, default=None)
    parser.add_argument("--skip-landing", action="store_true")
    parser.add_argument("--sleep-listing", type=float, default=1.5)
    parser.add_argument("--sleep-landing", type=float, default=1.0)
    args = parser.parse_args()

    out_path = Path(args.output)
    print("USDA GAIN Cocoa Crawler")
    print(f"Target countries: {sorted(_TARGET_COUNTRIES)}")
    print(f"Title filter: '{_TITLE_FILTER}'")
    print(f"Output: {out_path}")
    print(f"Early stop: {_MAX_EMPTY_PAGES_IN_A_ROW} consecutive empty pages\n")

    n = crawl(
        limit_pages=args.limit_pages,
        skip_landing=args.skip_landing,
        sleep_listing=args.sleep_listing,
        sleep_landing=args.sleep_landing,
        out_path=out_path,
    )
    if n == 0:
        print("\nWARNING: No records saved.")
        raise SystemExit(1)
    print(f"\nNext: python scratch/gain/build_manifest.py --source-name usda_gain_cocoa --input {out_path}")


if __name__ == "__main__":
    main()
