"""Probe MPOC Market Highlights articles.

Spiders the Market Highlights index at:
    https://mpoc.org.my/market-insight/market-highlights/

Follows ?page=N pagination until no more article links are found, then
writes a JSON index of all discovered articles to:
    data/mpoc/market_highlights_index.json

Each entry in the JSON:
    {
        "slug": "the-rise-of-aseans-foodservice-industry-...",
        "url":  "https://mpoc.org.my/the-rise-of-...",
        "title": "The Rise of ASEAN's Foodservice Industry: ..."
    }

This index is the input for the market_highlights entries in
configs/sources/mpoc_archive.yaml.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

_BASE_URL = "https://mpoc.org.my"
_INDEX_URL = "https://mpoc.org.my/market-insight/market-highlights/"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_OUT_PATH = (
    Path(__file__).parent.parent.parent
    / "data"
    / "mpoc"
    / "market_highlights_index.json"
)
_MAX_PAGES = 50  # safety cap


def _extract_articles(html: str, base_url: str) -> list[dict]:
    """Extract article links and titles from a Market Highlights index page."""
    soup = BeautifulSoup(html, "html.parser")
    articles = []

    # MPOC uses WordPress; article links are typically <h2> or <h3> anchors
    # with a link to a single post. We look for links that are not navigation,
    # category, or utility links — i.e., links whose path doesn't contain
    # known non-article segments.
    _SKIP_PATHS = {
        "/market-insight/",
        "/market-insight/market-highlights/",
        "/about-mpoc/",
        "/contact-us/",
        "/sitemap",
        "/privacy",
        "#",
        "",
    }

    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        # Must be on mpoc.org.my, not an anchor-only link, not a skip path
        if parsed.netloc not in ("mpoc.org.my", "www.mpoc.org.my"):
            continue
        if parsed.path in _SKIP_PATHS:
            continue
        if "market-highlights" in parsed.path and parsed.path.endswith("/market-highlights/"):
            continue
        # Skip pagination links, category pages, utility pages
        if any(
            seg in parsed.path
            for seg in [
                "/page/",
                "/category/",
                "/tag/",
                "/wp-content/",
                "/wp-admin/",
                "market-insight",
                "daily-palm-oil",
                "stock-comparison",
                "palm-oil-link",
                "media-release",
                "sustainability",
                "nutrition",
                "about-palm-oil",
                "mpoc-event",
                "annual-report",
            ]
        ):
            continue
        if full_url in seen:
            continue

        # Title: prefer text inside heading tags; fall back to link text
        title = a.get_text(strip=True)
        if not title or len(title) < 10:
            continue

        slug = parsed.path.strip("/").split("/")[-1]
        seen.add(full_url)
        articles.append({"slug": slug, "url": full_url, "title": title})

    return articles


def main() -> None:
    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": _UA})

    all_articles: list[dict] = []
    seen_slugs: set[str] = set()

    print(f"Spidering Market Highlights index: {_INDEX_URL}")

    for page_num in range(1, _MAX_PAGES + 1):
        url = _INDEX_URL if page_num == 1 else f"{_INDEX_URL}page/{page_num}/"

        try:
            resp = session.get(url, timeout=20, allow_redirects=True)
        except Exception as exc:
            print(f"  Page {page_num}: ERROR {exc}")
            break

        if resp.status_code == 404:
            print(f"  Page {page_num}: 404 — end of pagination")
            break
        if resp.status_code != 200:
            print(f"  Page {page_num}: HTTP {resp.status_code} — stopping")
            break

        articles = _extract_articles(resp.text, _BASE_URL)
        new_articles = [a for a in articles if a["slug"] not in seen_slugs]

        if not new_articles:
            print(f"  Page {page_num}: no new articles found — end of index")
            break

        for a in new_articles:
            seen_slugs.add(a["slug"])
            all_articles.append(a)

        print(f"  Page {page_num}: {len(new_articles)} new articles (total: {len(all_articles)})")
        time.sleep(0.75)

    # Deduplicate by slug preserving order
    seen: set[str] = set()
    deduped = []
    for a in all_articles:
        if a["slug"] not in seen:
            seen.add(a["slug"])
            deduped.append(a)

    _OUT_PATH.write_text(json.dumps(deduped, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nTotal articles found: {len(deduped)}")
    print(f"Saved → {_OUT_PATH}")


if __name__ == "__main__":
    main()
