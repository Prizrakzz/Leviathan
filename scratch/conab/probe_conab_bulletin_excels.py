"""Scrape all CONAB bulletin pages to collect the per-survey Excel URLs.

Each page at safra-de-cafe/No-levantamento-de-cafe-safra-YYYY/ has both
a PDF and a .xls/.xlsx forecast data file.  This script collects all
(survey_no, safra_year, xls_url) tuples from pages listed on the main
café safra page (paginated).

Run from project root:
    .venv\\Scripts\\python.exe scratch/conab/probe_conab_bulletin_excels.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from curl_cffi import requests as cr

_ROOT = Path(__file__).parent.parent.parent
_BASE = "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe"

_SURVEY_LINK_RE = re.compile(
    r'href="(https://www\.gov\.br/conab/pt-br/atuacao/informacoes-agropecuarias/'
    r'safras/safra-de-cafe/(\d)o-levantamento-de-cafe-safra-(\d{4})/[^"]+)"',
    re.IGNORECASE,
)
_XLS_RE = re.compile(r'href="(https://www\.gov\.br[^"]+\.xlsx?)"', re.IGNORECASE)


def _get_html(url: str) -> str:
    r = cr.get(url, impersonate="chrome124", timeout=25, allow_redirects=True)
    r.raise_for_status()
    return r.text


def main() -> None:
    results: list[dict] = []

    # Collect survey detail-page URLs from paginated listing.
    # Plone pagination: main page, then safra-de-cafe-1, safra-de-cafe-2, ...
    page_urls = [_BASE] + [f"{_BASE}/safra-de-cafe-{i}" for i in range(1, 30)]

    survey_links: dict[str, tuple[str, str]] = {}  # url → (survey_no, safra_year)
    print("Collecting survey page links...")
    for pg_url in page_urls:
        try:
            html = _get_html(pg_url)
        except Exception as e:
            print(f"  {pg_url}: {e}")
            break
        found = _SURVEY_LINK_RE.findall(html)
        if not found:
            print(f"  {pg_url}: no survey links found — stopping pagination")
            break
        for full_url, survey_no, safra_year in found:
            if full_url not in survey_links:
                survey_links[full_url] = (survey_no, safra_year)
        print(f"  {pg_url}: {len(found)} links  (total so far: {len(survey_links)})")
        time.sleep(1)

    print(f"\nTotal unique survey pages: {len(survey_links)}")

    # Visit each survey page and look for Excel files
    for url, (survey_no, safra_year) in sorted(survey_links.items(), reverse=True):
        print(f"  {survey_no}º Safra {safra_year}: {url}")
        try:
            html = _get_html(url)
        except Exception as e:
            print(f"    ERROR: {e}")
            time.sleep(2)
            continue

        xls_links = _XLS_RE.findall(html)
        for xls_url in xls_links:
            print(f"    XLS: {xls_url}")
            results.append(
                {
                    "safra_year": int(safra_year),
                    "survey_no": int(survey_no),
                    "xls_url": xls_url,
                    "source_page": url,
                }
            )
        time.sleep(1)

    # Write output
    out = _ROOT / "data" / "conab" / "conab_bulletin_excels.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {len(results)} Excel URLs → {out}")


if __name__ == "__main__":
    main()
