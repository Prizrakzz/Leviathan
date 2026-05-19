"""Probe: discover pre-2013 CONAB PDF gid_hashes from old Wayback snapshots.

Strategy
--------
1.  CDX-query for all archived snapshots of the CONAB Joomla listing page
    (both the base URL and its ?start= paginated versions) between 2005-2013.
2.  For each snapshot, fetch the Wayback HTML and parse out
    item/download/{gid_hash} links (same logic as probe_wayback_conab.py).
3.  Only keep entries where safra_year < 2013 (older than what we already have).
4.  Write results to data/conab/conab_pre2013_gids.json.

Usage
-----
    python scratch/conab/probe_conab_older_listings.py [--dry-run]

    --dry-run   Only query CDX and print snapshot timestamps; don't fetch pages.
"""
import argparse
import json
import re
import time
import urllib.request
import urllib.parse
import ssl
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────
_LISTING_BASE = (
    "https://www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe"
)
_CDX_API = "https://web.archive.org/cdx/search/cdx"
# We want snapshots from 2005 through end-2012 (pre-2013)
_CDX_FROM = "20050101"
_CDX_TO   = "20130101"

_ROOT       = Path(__file__).parent.parent.parent
_OUTPUT     = _ROOT / "data" / "conab" / "conab_pre2013_gids.json"
_KNOWN_GIDS = _ROOT / "data" / "conab" / "conab_joomla_gids.json"

_UA      = "Mozilla/5.0 (compatible; research-bot)"
_SSL_CTX = ssl.create_default_context()

# Pages to probe for each snapshot timestamp: main + up to 3 paginated pages
_PAGE_SUFFIXES = ["", "?start=10", "?start=20", "?start=30"]


# ── CDX helpers ─────────────────────────────────────────────────────────────
def _cdx_query(original_url: str) -> list[str]:
    """Return list of snapshot timestamps (14-digit) for the given URL."""
    # Build query manually to avoid urllib encoding slashes in the url= parameter
    params = (
        f"url={original_url}"
        f"&matchType=exact"
        f"&output=json"
        f"&fl=timestamp"
        f"&from={_CDX_FROM}"
        f"&to={_CDX_TO}"
        f"&filter=statuscode:200"
        f"&limit=50"
    )
    cdx_url = f"{_CDX_API}?{params}"
    try:
        req = urllib.request.Request(cdx_url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"  CDX error for {original_url}: {e}")
        return []
    # First row is header ["timestamp"]; rest are data rows
    if len(data) <= 1:
        return []
    return [row[0] for row in data[1:]]


def _cdx_query_prefix(url_prefix: str) -> list[tuple[str, str]]:
    """Return (timestamp, original_url) for all captures under a URL prefix."""
    params = (
        f"url={url_prefix}"
        f"&matchType=prefix"
        f"&output=json"
        f"&fl=timestamp,original"
        f"&from={_CDX_FROM}"
        f"&to={_CDX_TO}"
        f"&filter=statuscode:200"
        f"&limit=200"
        f"&collapse=timestamp:8"   # one per day max
    )
    cdx_url = f"{_CDX_API}?{params}"
    try:
        req = urllib.request.Request(cdx_url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"  CDX prefix error for {url_prefix}: {e}")
        return []
    if len(data) <= 1:
        return []
    return [(row[0], row[1]) for row in data[1:]]


# ── Wayback fetch ────────────────────────────────────────────────────────────
def _fetch_wayback(ts: str, original_url: str, timeout: int = 40) -> str | None:
    """Fetch Wayback snapshot using the if_ modifier (raw bytes, no rewriting)."""
    # With if_ modifier, Wayback injects minimal JS but preserves original hrefs
    wb_url = f"https://web.archive.org/web/{ts}if_/{original_url}"
    try:
        req = urllib.request.Request(wb_url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
            if resp.status != 200:
                print(f"  HTTP {resp.status}: {wb_url[-80:]}")
                return None
            raw = resp.read()
            html = raw.decode("utf-8", errors="replace")
            print(f"  [200 {len(html):>8,} chars] ts={ts} {original_url[-50:]}")
            return html
    except Exception as e:
        print(f"  [ERR] ts={ts}: {e}")
        return None


# ── Parse listing page ──────────────────────────────────────────────────────
def _parse_listing_page(html: str, snap_ts: str) -> list[dict]:
    """Extract Boletim download gid_hashes from a Joomla listing page snapshot."""
    entries: list[dict] = []

    # Find <h2> headings with levantamento + safra_year
    h2_pat = re.compile(r"<h2\b[^>]*>(.*?)</h2>", re.DOTALL | re.IGNORECASE)
    headings: list[tuple[int, int, int]] = []
    for m in h2_pat.finditer(html):
        text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        lev_m  = re.search(r"(\d)\s*[ºo°]", text)
        safra_m = re.search(r"Safra\s+(\d{4})", text, re.I)
        if lev_m and safra_m:
            headings.append((m.start(), int(lev_m.group(1)), int(safra_m.group(1))))

    if not headings:
        # Try alternate: look for text patterns without h2 association
        print("    (no h2 headings; attempting bare gid scan)")
        bare = re.findall(r"item/download/(\d+_[a-f0-9]{32})", html, re.I)
        print(f"    Bare gid scan found {len(bare)} raw gids (cannot associate with safra)")
        return entries

    # Find all item/download/{gid_hash} anchors
    anchor_pat = re.compile(
        r'<a\b[^>]*\bhref="[^"]*item/download/(\d+_[a-f0-9]{32})[^"]*"[^>]*>'
        r"(.*?)</a>",
        re.DOTALL | re.IGNORECASE,
    )
    for m in anchor_pat.finditer(html):
        gid_hash = m.group(1)
        label    = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if "boletim" not in label.lower():
            continue

        # Associate with nearest preceding heading
        for h_pos, lev, safra in reversed(headings):
            if h_pos < m.start():
                entries.append({
                    "safra_year":    safra,
                    "levantamento":  lev,
                    "label":         label,
                    "gid_hash":      gid_hash,
                    "wayback_snap_ts": snap_ts,
                })
                break

    return entries


# ── Main ────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Only query CDX and report; don't fetch listing pages")
    parser.add_argument("--min-year", type=int, default=2000,
                        help="Only keep gids with safra_year >= this (default 2000)")
    parser.add_argument("--max-year", type=int, default=2012,
                        help="Only keep gids with safra_year <= this (default 2012)")
    args = parser.parse_args()

    # Load known gids to avoid duplicates
    known: set[str] = set()
    if _KNOWN_GIDS.exists():
        for entry in json.loads(_KNOWN_GIDS.read_text()):
            known.add(entry["gid_hash"])
        print(f"Loaded {len(known)} known gid_hashes from {_KNOWN_GIDS.name}")

    # ── Step 1: CDX query for listing page snapshots ────────────────────────
    print(f"\nQuerying CDX for listing page snapshots ({_CDX_FROM}-{_CDX_TO})...")

    # Collect (ts, url) pairs — check main URL and paginated suffixes
    all_snapshots: list[tuple[str, str]] = []

    # Try exact match for main page and each paginated version
    for suffix in _PAGE_SUFFIXES:
        url = _LISTING_BASE + suffix
        clean_suffix = suffix.replace("?", "").replace("=", "")
        timestamps = _cdx_query(url)
        print(f"  {url[-70:]}  ->  {len(timestamps)} snapshots")
        for ts in timestamps:
            all_snapshots.append((ts, url))
        time.sleep(0.5)

    # Also try prefix match on the base URL (catches ?start= variants)
    print(f"\n  Trying prefix CDX query for {_LISTING_BASE[-60:]} ...")
    prefix_hits = _cdx_query_prefix(_LISTING_BASE)
    print(f"  -> {len(prefix_hits)} total prefix hits")
    # Deduplicate with exact hits
    seen_ts_url = {(ts, url) for ts, url in all_snapshots}
    for ts, orig in prefix_hits:
        if (ts, orig) not in seen_ts_url:
            all_snapshots.append((ts, orig))
            seen_ts_url.add((ts, orig))
        time.sleep(0.0)

    print(f"\nTotal CDX snapshots found: {len(all_snapshots)}")
    for ts, url in sorted(all_snapshots):
        print(f"  {ts}  {url[-70:]}")

    if args.dry_run or not all_snapshots:
        print("\n[dry-run] Stopping before page fetch.")
        return

    # ── Step 2: Fetch each snapshot and parse ───────────────────────────────
    print(f"\nFetching and parsing {len(all_snapshots)} snapshots...")
    all_entries: list[dict] = []
    seen_key: set[str] = set()

    for ts, url in sorted(all_snapshots):
        html = _fetch_wayback(ts, url)
        if html is None:
            time.sleep(2)
            continue

        entries = _parse_listing_page(html, ts)
        new_count = 0
        for e in entries:
            if e["safra_year"] < args.min_year or e["safra_year"] > args.max_year:
                continue
            key = f"{e['safra_year']}-{e['levantamento']}-{e['gid_hash']}"
            if key not in seen_key:
                seen_key.add(key)
                is_known = e["gid_hash"] in known
                all_entries.append(e)
                new_count += 1
                print(
                    f"    {'(known)' if is_known else 'NEW    '} "
                    f"{e['levantamento']}o Safra {e['safra_year']}  {e['gid_hash'][:35]}"
                )

        print(f"  -> {len(entries)} parsed, {new_count} in range [{args.min_year}-{args.max_year}]")
        time.sleep(2.5)  # polite delay

    # ── Step 3: Write output ─────────────────────────────────────────────────
    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT.write_text(
        json.dumps(sorted(all_entries, key=lambda e: (e["safra_year"], e["levantamento"])),
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nSaved {len(all_entries)} pre-2013 gids -> {_OUTPUT}")


if __name__ == "__main__":
    main()
