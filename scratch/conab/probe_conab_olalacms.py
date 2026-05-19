"""Discover pre-2013 CONAB coffee bulletin PDFs from OlalaCMS Wayback snapshots.

Phases
------
1a. CDX listing-page sweep  — query all Wayback snapshots of the old CONAB
    OlalaCMS bulletin listing page (conteudos.php?a=1253) from 2005-2013.
    For each snapshot, fetch the HTML via the Wayback ``if_`` modifier and
    extract every OlalaCMS/uploads/arquivos/ file link.

1b. CDX direct file sweep  — prefix-query CDX for any files crawled directly
    under www.conab.gov.br/OlalaCMS/uploads/arquivos/.  Catches files that
    Wayback indexed independently rather than through the listing page.

2.  Coffee filter  — keep only filenames containing "cafe" or "coffee" and
    not containing known non-coffee commodity keywords.

3.  Per-file CDX verify  — for each coffee filename not already found via the
    direct sweep, query CDX for the best available capture timestamp.

4.  Parse metadata  — extract safra_year and pub_month from the OlalaCMS
    filename prefix ``{YY}_{MM}_{DD}_{HH}_{mm}_{ss}_{original}.ext``.
    pub_month is stored as ``levantamento`` (survey proxy for pre-2013 data).

5.  Write manifest  — data/conab/conab_olalacms_gids.json.

Usage
-----
    python scratch/conab/probe_conab_olalacms.py [--dry-run]
    python scratch/conab/probe_conab_olalacms.py --output path/to/out.json
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
import ssl
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CDX_API   = "https://web.archive.org/cdx/search/cdx"
_OLALA_BASE = "http://www.conab.gov.br/OlalaCMS/uploads/arquivos"
_FROM      = "20050101"
_TO        = "20130101"
_UA        = "Mozilla/5.0 (compatible; research-bot)"
_SSL_CTX   = ssl.create_default_context()
_SLEEP     = 1.5   # seconds between Wayback calls (polite)

_ROOT   = Path(__file__).parent.parent.parent
_OUTPUT = _ROOT / "data" / "conab" / "conab_olalacms_gids.json"

# The listing page URL had at least two common variants in the archive.
_LISTING_URLS = [
    "http://www.conab.gov.br/conteudos.php?a=1253&t=",
    "http://www.conab.gov.br/conteudos.php?a=1253",
]

# Coffee keywords — filename must contain at least one (case-insensitive).
_COFFEE_INCLUDE = {"cafe", "coffee"}

# Non-coffee commodity keywords — filename must NOT contain any of these.
_COFFEE_EXCLUDE = {
    "cana", "graos", "milho", "algodao", "soja",
    "ingles", "espanhol", "english", "spanish",
    "acucar", "borracha", "trigo", "cacau",
    "arroz", "feijao", "mandioca",
}

# Only these extensions are useful for downstream processing.
_VALID_EXTENSIONS = {".pdf", ".doc", ".docx"}


# ---------------------------------------------------------------------------
# CDX helpers
# ---------------------------------------------------------------------------

def _cdx_get(params: dict, label: str = "") -> list[list[str]]:
    """Call CDX API with given params; return data rows (header stripped)."""
    url = _CDX_API + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=30) as r:
            rows = json.loads(r.read().decode())
        return [row for row in rows[1:] if row]
    except Exception as exc:
        tag = f" [{label}]" if label else ""
        print(f"  CDX error{tag}: {exc}  url={url[-90:]}")
        return []


def _cdx_listing_timestamps(listing_url: str) -> list[str]:
    """Return all CDX snapshot timestamps for the listing page URL."""
    rows = _cdx_get(
        {
            "url": listing_url,
            "matchType": "exact",
            "output": "json",
            "fl": "timestamp",
            "from": _FROM,
            "to": _TO,
            "filter": "statuscode:200",
            "limit": "50",
        },
        label=listing_url[-40:],
    )
    return [r[0] for r in rows]


def _cdx_direct_files() -> dict[str, str]:
    """Prefix-query CDX for all OlalaCMS/uploads/arquivos/ captures.

    Returns {filename: best_timestamp}.
    """
    rows = _cdx_get(
        {
            "url": f"{_OLALA_BASE}/",
            "matchType": "prefix",
            "output": "json",
            "fl": "timestamp,original",
            "from": _FROM,
            "to": _TO,
            "filter": "statuscode:200",
            "limit": "500",
            "collapse": "original",   # one entry per unique URL
        },
        label="OlalaCMS prefix",
    )
    result: dict[str, str] = {}
    for row in rows:
        ts, original = row[0], row[1]
        fn = original.split("/arquivos/", 1)[-1].split("?")[0].strip("/")
        if fn and fn not in result:
            result[fn] = ts
    return result


def _cdx_best_ts_for_file(filename: str) -> str | None:
    """CDX lookup for the best available direct capture of one OlalaCMS file."""
    original_url = f"{_OLALA_BASE}/{filename}"
    # Try with 200 filter first
    rows = _cdx_get(
        {
            "url": original_url,
            "matchType": "exact",
            "output": "json",
            "fl": "timestamp",
            "filter": "statuscode:200",
            "limit": "1",
        },
    )
    if rows:
        return rows[0][0]
    # Fallback: no status filter (may have 302 stored)
    rows = _cdx_get(
        {
            "url": original_url,
            "matchType": "exact",
            "output": "json",
            "fl": "timestamp",
            "limit": "1",
        },
    )
    return rows[0][0] if rows else None


# ---------------------------------------------------------------------------
# Wayback fetch
# ---------------------------------------------------------------------------

def _wayback_fetch_html(ts: str, original_url: str) -> str | None:
    """Fetch a Wayback snapshot via the if_ modifier (preserves original hrefs)."""
    wb_url = f"https://web.archive.org/web/{ts}if_/{original_url}"
    try:
        req = urllib.request.Request(wb_url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=45) as r:
            html = r.read().decode("utf-8", errors="replace")
        print(f"    [200  {len(html):>8,} chars]  ts={ts}")
        return html
    except Exception as exc:
        print(f"    [ERR] ts={ts}: {exc}")
        return None


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

def _extract_olala_filenames(html: str) -> list[str]:
    """Extract OlalaCMS/uploads/arquivos filenames from a listing page HTML."""
    # Pattern 1: bare path in any attribute or text
    raw = re.findall(r"OlalaCMS/uploads/arquivos/([^\s\"'<>&\r\n]+)", html, re.I)
    # Pattern 2: href with full path (redundant but catches edge cases)
    hrefs = re.findall(
        r'href="[^"]*OlalaCMS/uploads/arquivos/([^\s"&]+)"', html, re.I
    )
    seen: set[str] = set()
    result: list[str] = []
    for fn in raw + hrefs:
        fn = fn.strip("/").split("?")[0]
        if fn and fn not in seen:
            seen.add(fn)
            result.append(fn)
    return result


# ---------------------------------------------------------------------------
# Coffee filter
# ---------------------------------------------------------------------------

def _is_coffee(filename: str) -> bool:
    """Return True if the filename looks like a coffee document worth keeping."""
    lower = filename.lower()
    # Must be a document format, not an image, spreadsheet, etc.
    if not any(lower.endswith(ext) for ext in _VALID_EXTENSIONS):
        return False
    # Must contain at least one coffee keyword
    if not any(kw in lower for kw in _COFFEE_INCLUDE):
        return False
    # Must not contain a non-coffee commodity keyword
    if any(kw in lower for kw in _COFFEE_EXCLUDE):
        return False
    return True


def _bulletin_score(filename: str) -> int:
    """Higher score = more likely to be a quarterly survey bulletin (not an annual report)."""
    lower = filename.lower()
    if "boletim_cafe" in lower or "boletimcafe" in lower:
        return 3
    if "boletim" in lower:
        return 2
    if "relat" in lower:
        return 1
    return 0


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------

def _parse_olala_filename(filename: str) -> dict | None:
    """Parse the OlalaCMS upload-timestamp prefix from a filename.

    Format: ``{YY}_{MM}_{DD}_{HH}_{mm}_{ss}_{original_name}.ext``

    Returns a dict with keys ``safra_year``, ``pub_month``, ``label``,
    or ``None`` if the filename doesn't match the expected pattern.
    """
    parts = filename.split("_", 6)
    if len(parts) < 7:
        return None
    try:
        yy = int(parts[0])
        mm = int(parts[1])
        # Validate reasonable ranges
        _dd = int(parts[2])  # noqa: F841 — just to confirm it's numeric
    except ValueError:
        return None
    if not (5 <= yy <= 12 and 1 <= mm <= 12):
        # yy should be 05-12 for 2005-2012 pre-2013 data
        return None

    safra_year = 2000 + yy
    pub_month  = mm

    # Everything after the 6-part timestamp is the original filename
    original = parts[6]
    # Strip trailing dots and file extension for the label
    label = re.sub(r"\.+\w{2,5}$", "", original).rstrip(".")

    return {"safra_year": safra_year, "pub_month": pub_month, "label": label}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Discover pre-2013 CONAB OlalaCMS coffee bulletin PDFs via Wayback."
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print discovered entries without writing the output JSON.",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=_OUTPUT,
        metavar="PATH",
        help=f"Output JSON path (default: {_OUTPUT})",
    )
    args = ap.parse_args()

    # ── Phase 1a: listing-page CDX sweep ─────────────────────────────────────
    print("=" * 60)
    print("Phase 1a: CDX listing-page sweep")
    print("=" * 60)
    listing_hits: dict[str, str] = {}   # filename -> listing page snap_ts

    for listing_url in _LISTING_URLS:
        print(f"\nQuerying CDX for: {listing_url}")
        timestamps = _cdx_listing_timestamps(listing_url)
        print(f"  Found {len(timestamps)} snapshot(s): {timestamps}")
        time.sleep(_SLEEP)

        for ts in timestamps:
            print(f"\n  Fetching listing page ts={ts} ...")
            html = _wayback_fetch_html(ts, listing_url)
            time.sleep(_SLEEP)
            if not html:
                continue
            fns = _extract_olala_filenames(html)
            new = 0
            for fn in fns:
                if fn not in listing_hits:
                    listing_hits[fn] = ts
                    new += 1
            print(f"  Extracted {len(fns)} filename(s) ({new} new)")
            for fn in fns:
                print(f"    {fn}")

    print(f"\n1a total: {len(listing_hits)} unique OlalaCMS filenames from listing pages")

    # ── Phase 1b: direct CDX file sweep ──────────────────────────────────────
    print("\n" + "=" * 60)
    print("Phase 1b: CDX direct OlalaCMS file sweep")
    print("=" * 60)
    direct_hits = _cdx_direct_files()
    time.sleep(_SLEEP)
    print(f"  CDX returned {len(direct_hits)} unique direct file captures")
    for fn, ts in sorted(direct_hits.items()):
        print(f"    {ts}  {fn}")

    # ── Merge ─────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Merge")
    print("=" * 60)
    all_filenames: dict[str, dict] = {}
    for fn, ts in listing_hits.items():
        all_filenames[fn] = {"listing_ts": ts, "cdx_ts": direct_hits.get(fn)}
    for fn, ts in direct_hits.items():
        if fn not in all_filenames:
            all_filenames[fn] = {"listing_ts": None, "cdx_ts": ts}

    print(f"  Total unique filenames (merged): {len(all_filenames)}")

    # ── Phase 2: coffee filter ────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Phase 2: Coffee filter")
    print("=" * 60)
    coffee_fns = {fn: meta for fn, meta in all_filenames.items() if _is_coffee(fn)}
    excluded   = len(all_filenames) - len(coffee_fns)
    print(f"  Coffee: {len(coffee_fns)}   Excluded (non-coffee/unparseable): {excluded}")
    for fn in sorted(coffee_fns):
        meta = coffee_fns[fn]
        src  = "CDX" if meta["cdx_ts"] else "listing"
        print(f"  + [{src}]  {fn}")

    # ── Phase 3: per-file CDX verification ───────────────────────────────────
    print("\n" + "=" * 60)
    print("Phase 3: Per-file CDX verification (files without direct timestamp)")
    print("=" * 60)
    for fn, meta in coffee_fns.items():
        if not meta["cdx_ts"]:
            print(f"  Probing CDX for: {fn}")
            ts = _cdx_best_ts_for_file(fn)
            meta["cdx_ts"] = ts
            print(f"    -> {ts}")
            time.sleep(_SLEEP)

    # ── Phase 4: parse metadata + build entries ───────────────────────────────
    print("\n" + "=" * 60)
    print("Phase 4: Parse metadata")
    print("=" * 60)
    entries: list[dict] = []
    seen_keys: set[tuple[int, int]] = set()

    for fn in sorted(coffee_fns):
        meta   = coffee_fns[fn]
        parsed = _parse_olala_filename(fn)
        if not parsed:
            print(f"  SKIP (unparseable prefix): {fn}")
            continue

        best_ts = meta["cdx_ts"] or meta["listing_ts"]

        # Skip files that score 0 — they are price tables or other non-bulletin docs.
        if _bulletin_score(fn) == 0:
            print(f"  SKIP (non-bulletin, score=0): {fn}")
            continue

        key = (parsed["safra_year"], parsed["pub_month"])

        if key in seen_keys:
            # Duplicate (year, month) — prefer higher-score bulletin, break ties by recency
            new_score = _bulletin_score(fn)
            for e in entries:
                if e["safra_year"] == parsed["safra_year"] and e["pub_month"] == parsed["pub_month"]:
                    cur_score = _bulletin_score(e["filename"])
                    prefer_new = new_score > cur_score or (
                        new_score == cur_score
                        and best_ts is not None
                        and (e["wayback_snap_ts"] is None or best_ts > e["wayback_snap_ts"])
                    )
                    if prefer_new:
                        e.update(
                            filename=fn,
                            olalacms_url=f"{_OLALA_BASE}/{fn}",
                            wayback_snap_ts=best_ts,
                            label=parsed["label"],
                        )
                    break
            print(
                f"  DUP  safra={parsed['safra_year']} month={parsed['pub_month']:02d}"
                f"  score={new_score}: {fn}"
            )
            continue

        seen_keys.add(key)
        entry = {
            "safra_year":      parsed["safra_year"],
            "levantamento":    parsed["pub_month"],   # pub_month as levantamento proxy
            "pub_month":       parsed["pub_month"],
            "label":           parsed["label"],
            "filename":        fn,
            "olalacms_url":    f"{_OLALA_BASE}/{fn}",
            "wayback_snap_ts": best_ts,
        }
        entries.append(entry)
        print(
            f"  safra={parsed['safra_year']}  month={parsed['pub_month']:02d}"
            f"  ts={best_ts}  {fn[:70]}"
        )

    entries.sort(key=lambda e: (e["safra_year"], e["pub_month"]))

    print(f"\nTotal entries: {len(entries)}")

    # Corpus summary: (safra_year, month) distribution
    print("\nCorpus distribution (safra_year x pub_month):")
    by_year: dict[int, list[int]] = {}
    for e in entries:
        by_year.setdefault(e["safra_year"], []).append(e["pub_month"])
    for yr in sorted(by_year):
        months = sorted(by_year[yr])
        print(f"  {yr}: months {months}")

    # ── Phase 5: write manifest ───────────────────────────────────────────────
    if args.dry_run:
        print(f"\n[dry-run] Would write {len(entries)} entries to: {args.output}")
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {len(entries)} entries -> {args.output}")


if __name__ == "__main__":
    main()
