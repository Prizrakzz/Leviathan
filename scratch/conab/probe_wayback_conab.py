"""Probe: scrape CONAB boletim listing pages from the Wayback Machine.

The old Joomla site (conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe)
was archived 63 times between 2019 and 2025.  All 4 paginated listing pages (10
entries each) are independently captured.  This script fetches them, extracts each
Joomla item/download gid+hash pair, and writes conab_joomla_gids.json.

That JSON is then consumed by jobs/fetch_conab_historical_raw.py, which tries to
download each PDF from Wayback (or directly from conab.gov.br as a fallback).

Confirmed Wayback snapshots used
---------------------------------
Page 1 (start=0)   Dec 2022  20221219095715  — safra 2020-2022 (re-uploaded 45xxx gids)
Page 1 (start=0)   Feb 2021  20210206051321  — safra 2018-2021 (original gids, longer-lived)
Page 2 (start=10)  Dec 2022  20221219095715  — safra 2017-2019
Page 3 (start=20)  Dec 2022  20221219095715  — safra 2014-2016
Page 4 (start=30)  Dec 2022  20221219095715  — safra ~2011-2013 (may 404 → skipped)

Having two sets of gids for safra 2018-2021 is intentional: the re-uploaded 45xxx gids
are more recent, while the original gids (33xxx-35xxx) existed for longer and may have
a higher chance of having been crawled by Wayback independently.  The fetch job tries
all candidate gids until one succeeds.
"""
import json
import re
import ssl
import time
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_LISTING_BASE = (
    "https://www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe"
)

# (wayback_ts, page_url_suffix, label)
_LISTING_PAGES = [
    ("20221219095715", "",         "page1-dec2022"),
    ("20210206051321", "",         "page1-feb2021"),   # original gid IDs
    ("20221219095715", "?start=10", "page2-dec2022"),
    ("20221219095715", "?start=20", "page3-dec2022"),
    ("20221219095715", "?start=30", "page4-dec2022"),  # unconfirmed; attempt anyway
]

_OUTPUT_PATH = Path("conab_joomla_gids.json")
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_SSL_CTX = ssl.create_default_context()

# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def _fetch_wayback(ts: str, original_url: str, timeout: int = 30) -> str | None:
    wb_url = f"https://web.archive.org/web/{ts}/{original_url}"
    try:
        req = urllib.request.Request(wb_url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
            if resp.status != 200:
                print(f"  [HTTP {resp.status}] {wb_url[-80:]}")
                return None
            html = resp.read().decode("utf-8", errors="replace")
            print(f"  [200  {len(html):7d} chars] {wb_url[-80:]}")
            return html
    except Exception as exc:
        print(f"  [ERR] {wb_url[-80:]}: {exc}")
        return None

# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def _parse_listing_page(html: str) -> list[dict]:
    """Extract (levantamento, safra_year, gid_hash, wayback_snap_ts, label)
    for every 'Boletim' download link found on a listing page.

    Skips 'Tabela de dados' / spreadsheet links.
    Associates each link with the nearest preceding h2 heading.
    """
    entries: list[dict] = []

    # ── Find all <h2> headings with their byte positions ────────────────────
    # Joomla HTML: <h2 class="item-heading"><a href="...">Xº Levantamento…</a></h2>
    h2_pat = re.compile(r"<h2\b[^>]*>(.*?)</h2>", re.DOTALL | re.IGNORECASE)
    headings: list[tuple[int, int, int]] = []  # (char_offset, levantamento, safra_year)
    for m in h2_pat.finditer(html):
        text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        lev_m = re.search(r"(\d)\s*[ºo°]", text)
        safra_m = re.search(r"Safra\s+(\d{4})", text, re.I)
        if lev_m and safra_m:
            headings.append((m.start(), int(lev_m.group(1)), int(safra_m.group(1))))

    if not headings:
        print("    WARNING: no headings found — page may be empty or an error page")
        return entries

    # ── Find all <a> tags pointing to item/download ──────────────────────────
    # Wayback rewrites hrefs to absolute Wayback URLs:
    #   href="/web/YYYYMMDDHHMMSS/https://www.conab.gov.br/.../item/download/GID_HASH"
    # OR with full base:
    #   href="https://web.archive.org/web/YYYYMMDDHHMMSS/https://www.conab.gov.br/.../..."
    anchor_pat = re.compile(
        r'<a\b[^>]*\bhref="([^"]*item/download/(\d+_[a-f0-9]+))[^"]*"[^>]*>'
        r"(.*?)</a>",
        re.DOTALL | re.IGNORECASE,
    )
    for m in anchor_pat.finditer(html):
        href = m.group(1)
        gid_hash = m.group(2)
        label = re.sub(r"<[^>]+>", "", m.group(3)).strip()

        # Keep only bulletin PDFs; skip data-table spreadsheet links
        label_lower = label.lower()
        if "boletim" not in label_lower:
            continue

        # Extract Wayback snapshot timestamp from the href
        ts_m = re.search(r"/web/(\d{14})/", href)
        snap_ts = ts_m.group(1) if ts_m else None

        # Associate with the nearest h2 heading that precedes this anchor
        heading: tuple[int, int] | None = None
        for h_pos, lev, safra in reversed(headings):
            if h_pos < m.start():
                heading = (lev, safra)
                break
        if heading is None:
            continue

        entries.append(
            {
                "safra_year": heading[1],
                "levantamento": heading[0],
                "label": label,
                "gid_hash": gid_hash,
                "wayback_snap_ts": snap_ts,
            }
        )

    return entries

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    all_entries: list[dict] = []
    seen: set[str] = set()  # deduplicate on safra_year + levantamento + gid_hash

    for ts, suffix, label in _LISTING_PAGES:
        original_url = _LISTING_BASE + suffix
        print(f"\n─── {label} ({original_url[-55:]}) ───")

        html = _fetch_wayback(ts, original_url)
        if html is None:
            print(f"  Skipping {label} — fetch failed")
            time.sleep(1.0)
            continue

        entries = _parse_listing_page(html)
        new = 0
        for e in entries:
            key = f"{e['safra_year']}-{e['levantamento']}-{e['gid_hash']}"
            if key not in seen:
                seen.add(key)
                all_entries.append(e)
                new += 1
        print(f"  Parsed {len(entries)} Boletim links; {new} new unique gids")
        for e in entries:
            tag = "NEW" if f"{e['safra_year']}-{e['levantamento']}-{e['gid_hash']}" in seen else "DUP"
            print(
                f"    [{tag}] {e['levantamento']}º Safra {e['safra_year']}"
                f"  {e['gid_hash'][:30]}  {e['label'][:50]}"
            )

        time.sleep(2.0)  # polite delay between Wayback requests

    # Sort: most recent first
    all_entries.sort(key=lambda x: (x["safra_year"], x["levantamento"]), reverse=True)

    _OUTPUT_PATH.write_text(
        json.dumps(all_entries, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nSaved {len(all_entries)} gid entries → {_OUTPUT_PATH}")

    # Coverage summary
    by_year: dict[int, list[int]] = {}
    for e in all_entries:
        by_year.setdefault(e["safra_year"], []).append(e["levantamento"])

    print("\nCoverage by safra year:")
    for year in sorted(by_year.keys(), reverse=True):
        levs = sorted(set(by_year[year]), reverse=True)
        print(f"  Safra {year}: levantamentos {levs} ({len(by_year[year])} gid candidates)")

    # Warn about gaps vs. expected 4 bulletins per safra
    gap_years = sorted(
        {y for y, levs in by_year.items() if len(set(levs)) < 4},
        reverse=True,
    )
    if gap_years:
        print(f"\nIncomplete safra years (< 4 levantamentos found): {gap_years}")
    print(
        "\nNext step: run  .venv\\Scripts\\python.exe jobs\\fetch_conab_historical_raw.py --dry-run"
    )


if __name__ == "__main__":
    main()
