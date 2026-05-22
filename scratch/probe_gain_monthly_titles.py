"""Probe FAS GAIN to verify exact title strings for monthly/semi-annual categories.

Samples a handful of month URLs across different years and prints all unique
card titles found. Use the output to confirm (or correct) the title_filter
values planned for Phase 4 COMMODITIES entries.

Run:
    python scratch/probe_gain_monthly_titles.py

Takes ~30-60 seconds (no Batch required — runs locally).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Make the leviathan package importable from the workspace root
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parents[1]))

from curl_cffi import requests as cr
from jobs.batch.gain_backfill_task import _get_html, _parse_listing, _has_next_page, _BASE_URL

# ---------------------------------------------------------------------------
# Month URLs to sample.
# Spread across years to catch any FAS naming drift over time.
# ---------------------------------------------------------------------------

SAMPLE_MONTHS = [
    # Semi-annual release windows — targeted months for oilseeds/sugar/cocoa
    "2024-05",  # May 2024 — peak semi-annual window
    "2024-11",  # Nov 2024 — peak semi-annual window
    "2023-05",
    "2023-11",
    "2022-05",
    "2022-11",
    "2020-05",
    "2018-11",
    "2015-05",
    # Monthly update months for grain/cotton
    "2024-03",
    "2023-08",
    "2021-06",
    "2010-11",  # legacy
]

MAX_PAGES_PER_MONTH = 8  # paginate up to N pages per month to find all categories

_SEARCH_DATE = (
    "https://fas.usda.gov/data/search"
    "?reports%5B0%5D=report_type%3A10251"
    "&reports%5B1%5D=report_datetime%3A{ym}"
)

# Keywords to highlight in output
HIGHLIGHT_KEYWORDS = [
    "grain and feed monthly",
    "oilseeds",
    "sugar",
    "cotton",
    "coffee semi",
    "cocoa semi",
    "citrus",
]


def main() -> None:
    all_titles: dict[str, set[str]] = {}  # month -> set of titles

    with cr.Session() as sess:
        sess.headers.update({
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://fas.usda.gov/",
        })
        # Warm up session
        print("Warming up session...")
        _get_html(sess, _BASE_URL)
        time.sleep(1.0)

        for ym in SAMPLE_MONTHS:
            base_url = _SEARCH_DATE.format(ym=ym)
            print(f"\n--- Sampling {ym} (paginating up to {MAX_PAGES_PER_MONTH} pages) ---")
            month_titles: set[str] = set()
            page_num = 0
            while page_num < MAX_PAGES_PER_MONTH:
                url = base_url if page_num == 0 else f"{base_url}&page={page_num}"
                html = _get_html(sess, url)
                if not html:
                    print(f"  [FAILED] No response on page {page_num}")
                    break
                cards = _parse_listing(html)
                if not cards:
                    break
                print(f"  page {page_num}: {len(cards)} cards")
                for c in cards:
                    month_titles.add(c["title"])
                if not _has_next_page(html):
                    break
                page_num += 1
                time.sleep(1.5)
            all_titles[ym] = month_titles
            time.sleep(1.5)

    # ---------------------------------------------------------------------------
    # Print results
    # ---------------------------------------------------------------------------

    print("\n" + "=" * 70)
    print("ALL UNIQUE TITLES PER SAMPLED MONTH")
    print("=" * 70)

    for ym, titles in all_titles.items():
        print(f"\n[{ym}]")
        for t in sorted(titles):
            marker = ""
            tl = t.lower()
            for kw in HIGHLIGHT_KEYWORDS:
                if kw in tl:
                    marker = "  *** MATCH ***"
                    break
            print(f"  {t}{marker}")

    # Aggregate: all unique titles across all months
    aggregate: set[str] = set()
    for titles in all_titles.values():
        aggregate |= titles

    print("\n" + "=" * 70)
    print("AGGREGATE: ALL UNIQUE TITLES (SORTED, ALL MONTHS COMBINED)")
    print("=" * 70)

    categories: list[str] = []
    for t in sorted(aggregate):
        # Strip the country prefix (everything before the first colon)
        if ":" in t:
            category = t.split(":", 1)[1].strip()
        else:
            category = t
        categories.append(category)

    for c in sorted(set(categories)):
        marker = ""
        cl = c.lower()
        for kw in HIGHLIGHT_KEYWORDS:
            if kw in cl:
                marker = "  *** MATCH ***"
                break
        print(f"  {c}{marker}")

    print("\n" + "=" * 70)
    print("PHASE 4 TITLE FILTER VERIFICATION")
    print("=" * 70)

    filters_to_check = [
        ("grain and feed monthly",              "grain_monthly / grain_monthly_a / grain_monthly_b"),
        ("oilseeds and products semi-annual",   "oilseeds_monthly"),
        ("sugar semi-annual",                   "sugar_semiannual"),
        ("cotton and products monthly",         "cotton_monthly_a / cotton_monthly_b"),
        ("coffee semi-annual",                  "coffee_semiannual"),
        ("cocoa semi-annual",                   "cocoa_semiannual"),
    ]

    all_cats_lower = {c.lower() for c in categories}
    for filt, job_name in filters_to_check:
        matched = [c for c in sorted(set(categories)) if filt in c.lower()]
        status = "OK" if matched else "NOT FOUND"
        print(f"\n  [{status}] title_filter='{filt}'  →  {job_name}")
        if matched:
            for m in matched:
                print(f"      Matched: '{m}'")
        else:
            # Show partial matches to help debug
            partial = [c for c in sorted(set(categories)) if filt.split()[0] in c.lower()]
            if partial:
                print(f"      Partial matches on first word:")
                for p in partial[:10]:
                    print(f"        '{p}'")
            else:
                print(f"      No partial matches either — category may not exist in sampled months")


if __name__ == "__main__":
    main()
