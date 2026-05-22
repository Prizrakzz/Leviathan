"""
Resolve wayback_needed=true entries in wb_cmo_outlook_manifest.yaml.

Phase 1  (--phase 1, default): DSpace 7 title search for 2014-2017 semi-annual reports.
Phase 2  (--phase 2): DSpace 7 collection bulk harvest for 2008-2013.
Phase 3  (--phase 3): Enhanced Wayback CDX for pre-2008 (and any unresolved 2008-2013).

Usage:
    python scratch/resolve_pre2018.py --phase 1           # probe only, print results
    python scratch/resolve_pre2018.py --phase 1 --patch   # probe + patch manifest

    python scratch/resolve_pre2018.py --phase 2 --patch
    python scratch/resolve_pre2018.py --phase 3 --patch
"""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

import requests
import yaml

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DSPACE_BASE = "https://openknowledge.worldbank.org/server/api"
WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"
OK_BASE = "https://openknowledge.worldbank.org"

MANIFEST_PATH = (
    Path(__file__).parent.parent / "configs" / "sources" / "wb_cmo_outlook_manifest.yaml"
)

SLEEP_S = 1.0  # between DSpace API calls

# ---------------------------------------------------------------------------
# DSpace 7 helpers  (shared across Phase 1 and 2)
# ---------------------------------------------------------------------------

def _dspace_title_search(title: str, session: requests.Session, expected_year: int | None = None) -> str | None:
    """Return DSpace 7 REST API content URL for the first PDF bitstream matching title.

    Only accepts items whose name contains BOTH 'commodity' AND 'outlook'.
    Optionally validates that dc.date.issued is within ±2 years of expected_year.
    """
    resp = session.get(
        f"{DSPACE_BASE}/discover/search/objects",
        params={"query": title, "size": 10},
        timeout=30,
    )
    resp.raise_for_status()
    objects = (
        resp.json()
        .get("_embedded", {})
        .get("searchResult", {})
        .get("_embedded", {})
        .get("objects", [])
    )
    if not objects:
        return None

    for obj_wrapper in objects:
        obj = obj_wrapper.get("_embedded", {}).get("indexableObject", {})
        item_name = obj.get("name", "")
        item_uuid = obj.get("uuid")
        if not item_uuid:
            continue

        name_lower = item_name.lower()
        # Must mention BOTH 'commodity' AND 'outlook' to be a CMO Outlook report
        if not ("commodity" in name_lower and "outlook" in name_lower):
            continue

        # Optional date guard: reject if issued year is more than 2 years off
        if expected_year is not None:
            issued = _item_issued_year(obj)
            if issued is not None and abs(issued - expected_year) > 2:
                print(f"    skip: {item_name!r} (issued {issued}, expected ~{expected_year})")
                continue

        bitstream_url = _bitstream_from_item(item_uuid, item_name, session)
        if bitstream_url:
            return bitstream_url

    return None


def _item_issued_year(obj: dict) -> int | None:
    """Extract year from dc.date.issued in DSpace 7 search result object."""
    metadata = obj.get("metadata", {})
    for key in ("dc.date.issued", "dc.date.available"):
        vals = metadata.get(key, [])
        if vals:
            raw = vals[0].get("value", "")
            m = re.match(r"(\d{4})", raw)
            if m:
                return int(m.group(1))
    return None


def _bitstream_from_item(item_uuid: str, item_name: str, session: requests.Session) -> str | None:
    """Walk item → bundles → ORIGINAL → bitstreams → first PDF UUID."""
    r2 = session.get(f"{DSPACE_BASE}/core/items/{item_uuid}/bundles", timeout=30)
    r2.raise_for_status()
    for bundle in r2.json().get("_embedded", {}).get("bundles", []):
        if bundle.get("name") != "ORIGINAL":
            continue
        bitstreams_href = bundle.get("_links", {}).get("bitstreams", {}).get("href")
        if not bitstreams_href:
            continue
        r3 = session.get(bitstreams_href, timeout=30)
        r3.raise_for_status()
        for bit in r3.json().get("_embedded", {}).get("bitstreams", []):
            if bit.get("name", "").lower().endswith(".pdf"):
                uuid = bit["uuid"]
                print(f"    ✓ found PDF bitstream: {bit['name']!r} on item {item_name!r}")
                return f"{OK_BASE}/server/api/core/bitstreams/{uuid}/content"
    return None


# ---------------------------------------------------------------------------
# Phase 1: DSpace 7 title search  (2014-2017)
# ---------------------------------------------------------------------------

def phase1(entries: list[dict], session: requests.Session) -> list[dict]:
    """Search DSpace 7 by publication title for each 2014-2017 entry.

    Returns list of dicts with keys: release_date, url, notes.
    """
    year_min, year_max = 2014, 2017
    candidates = [
        e for e in entries
        if e.get("wayback_needed") and year_min <= int(e["release_date"][:4]) <= year_max
    ]
    print(f"\n[Phase 1] {len(candidates)} entries to resolve (2014-2017)\n")

    results = []
    for entry in candidates:
        release_date = entry["release_date"]
        label = entry["label"]          # e.g. "January", "April", "October"
        year = release_date[:4]
        title = f"Commodity Markets Outlook {label} {year}"

        year = int(release_date[:4])
        print(f"  {release_date}  searching: {title!r}")
        try:
            url = _dspace_title_search(title, session, expected_year=year)
        except Exception as exc:
            print(f"    ✗ API error: {exc}")
            url = None

        if url:
            results.append({
                "release_date": release_date,
                "url": url,
                "notes": f"DSpace 7 title search: {title!r}",
            })
            print(f"    → {url}")
        else:
            print(f"    ✗ not found")
            results.append({"release_date": release_date, "url": None, "notes": None})

        time.sleep(SLEEP_S)

    return results


# ---------------------------------------------------------------------------
# Phase 2: DSpace 7 collection bulk harvest  (2008-2013)
# ---------------------------------------------------------------------------

_CMO_COLLECTION_SEARCH_QUERY = "Commodity Markets Outlook"

def _find_cmo_collection_uuid(session: requests.Session) -> str | None:
    """Find the CMO Outlook collection UUID via DSpace 7 search."""
    resp = session.get(
        f"{DSPACE_BASE}/discover/search/objects",
        params={
            "query": _CMO_COLLECTION_SEARCH_QUERY,
            "dsoType": "collection",
            "size": 10,
        },
        timeout=30,
    )
    resp.raise_for_status()
    objects = (
        resp.json()
        .get("_embedded", {})
        .get("searchResult", {})
        .get("_embedded", {})
        .get("objects", [])
    )
    for obj_wrapper in objects:
        obj = obj_wrapper.get("_embedded", {}).get("indexableObject", {})
        name = obj.get("name", "")
        if "commodity" in name.lower() and "outlook" in name.lower():
            uuid = obj.get("uuid")
            print(f"  Found CMO collection: {name!r} → {uuid}")
            return uuid
    # Print all found collections for debugging
    print(f"  No exact match — found collections:")
    for obj_wrapper in objects:
        obj = obj_wrapper.get("_embedded", {}).get("indexableObject", {})
        print(f"    {obj.get('name')!r} → {obj.get('uuid')}")
    return None


def _list_collection_items(collection_uuid: str, session: requests.Session) -> list[dict]:
    """Paginate all items in a DSpace 7 collection."""
    items = []
    page = 0
    page_size = 100
    while True:
        resp = session.get(
            f"{DSPACE_BASE}/core/collections/{collection_uuid}/items",
            params={"size": page_size, "page": page, "embed": "metadata"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("_embedded", {}).get("items", [])
        items.extend(batch)
        print(f"  Page {page}: {len(batch)} items (total so far: {len(items)})")
        page_info = data.get("page", {})
        total_pages = page_info.get("totalPages", 1)
        if page + 1 >= total_pages or not batch:
            break
        page += 1
        time.sleep(0.5)
    return items


def _item_date(item: dict) -> str | None:
    """Extract dc.date.issued or dc.date.available from item metadata."""
    metadata = item.get("metadata", {})
    for key in ("dc.date.issued", "dc.date.available", "dc.date.accessioned"):
        vals = metadata.get(key, [])
        if vals:
            raw = vals[0].get("value", "")
            # Normalise to YYYY-MM
            m = re.match(r"(\d{4})-(\d{2})", raw)
            if m:
                return f"{m.group(1)}-{m.group(2)}"
            m = re.match(r"(\d{4})", raw)
            if m:
                return m.group(1)  # year only
    return None


def phase2(entries: list[dict], session: requests.Session) -> list[dict]:
    """Bulk harvest DSpace 7 collection for 2008-2013 entries."""
    year_min, year_max = 2008, 2013
    candidates = {
        e["release_date"]: e
        for e in entries
        if e.get("wayback_needed") and year_min <= int(e["release_date"][:4]) <= year_max
    }
    print(f"\n[Phase 2] {len(candidates)} entries to resolve (2008-2013)\n")

    print("  Looking up CMO Outlook collection …")
    coll_uuid = _find_cmo_collection_uuid(session)
    time.sleep(0.5)

    results = []

    if coll_uuid:
        print(f"\n  Listing items in collection {coll_uuid} …")
        all_items = _list_collection_items(coll_uuid, session)
        print(f"\n  Total items in collection: {len(all_items)}")

        # Build a lookup: release_date → item
        date_to_item: dict[str, dict] = {}
        for item in all_items:
            d = _item_date(item)
            if d and d in candidates:
                # Prefer exact YYYY-MM match; may collide — keep first
                if d not in date_to_item:
                    date_to_item[d] = item

        for release_date, entry in sorted(candidates.items()):
            item = date_to_item.get(release_date)
            if not item:
                print(f"  {release_date}  ✗ no collection item matched")
                results.append({"release_date": release_date, "url": None, "notes": None})
                continue

            item_uuid = item.get("uuid")
            item_name = item.get("name", "")
            print(f"  {release_date}  → item {item_name!r} ({item_uuid})")
            url = _bitstream_from_item(item_uuid, item_name, session)
            if url:
                results.append({
                    "release_date": release_date,
                    "url": url,
                    "notes": f"DSpace 7 collection item: {item_name!r}",
                })
                print(f"    → {url}")
            else:
                print(f"    ✗ no PDF bitstream found")
                results.append({"release_date": release_date, "url": None, "notes": None})
            time.sleep(SLEEP_S)

    else:
        # Collection not found — fall back to per-entry title search
        print("\n  Collection not found — falling back to per-entry title search …\n")
        for release_date, entry in sorted(candidates.items()):
            label = entry["label"]
            year = release_date[:4]
            title = f"Commodity Markets Outlook {label} {year}"
            print(f"  {release_date}  searching: {title!r}")
            try:
                url = _dspace_title_search(title, session, expected_year=int(release_date[:4]))
            except Exception as exc:
                print(f"    ✗ API error: {exc}")
                url = None

            if url:
                results.append({
                    "release_date": release_date,
                    "url": url,
                    "notes": f"DSpace 7 title search fallback: {title!r}",
                })
                print(f"    → {url}")
            else:
                print(f"    ✗ not found")
                results.append({"release_date": release_date, "url": None, "notes": None})
            time.sleep(SLEEP_S)

    return results


# ---------------------------------------------------------------------------
# Phase 3: Enhanced Wayback CDX  (pre-2008 + unresolved 2008-2013)
# ---------------------------------------------------------------------------

# Old-style DSpace 5/6 bitstream path pattern in Wayback-archived HTML
_LEGACY_BITSTREAM_RE = re.compile(
    r"/bitstream/handle/\d+/\d+/[^\"'\s>]+\.pdf",
    re.IGNORECASE,
)
# New-style DSpace 7
_DSPACE7_BITSTREAM_RE = re.compile(
    r"openknowledge\.worldbank\.org/bitstreams/([0-9a-f-]{36})/download",
    re.IGNORECASE,
)


def _cdx_query(params: dict, session: requests.Session) -> list[tuple[str, str]]:
    """Run a CDX query; return list of (timestamp, original_url) pairs."""
    try:
        resp = session.get(WAYBACK_CDX, params=params, timeout=30)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        print(f"    CDX error: {exc}")
        return []
    # rows[0] is the header
    return [(r[0], r[1]) for r in rows[1:]] if len(rows) > 1 else []


def _resolve_wayback_url(ts: str, original: str, session: requests.Session) -> str | None:
    """Try to get a downloadable PDF URL from a Wayback replay of a landing page."""
    landing = f"https://web.archive.org/web/{ts}/{original}"
    try:
        resp = session.get(landing, timeout=30)
        resp.raise_for_status()
        text = resp.text
    except Exception as exc:
        print(f"    Wayback fetch failed: {exc}")
        return None

    # DSpace 7 bitstream link in archived HTML
    m7 = _DSPACE7_BITSTREAM_RE.search(text)
    if m7:
        uuid = m7.group(1)
        return f"{OK_BASE}/server/api/core/bitstreams/{uuid}/content"

    # DSpace 5/6 legacy bitstream path
    m56 = _LEGACY_BITSTREAM_RE.search(text)
    if m56:
        path = m56.group(0)
        return f"https://web.archive.org/web/{ts}/{OK_BASE}{path}"

    # If the original URL itself ends in .pdf it IS the PDF
    if original.lower().endswith(".pdf"):
        return landing

    return None


def _wayback_search_one(
    year: int, month: int, label: str, session: requests.Session
) -> str | None:
    """Try multiple CDX patterns to find a Wayback snapshot for a given release."""
    # Wide date window: ±4 months, clamped to year boundaries
    from_year = year if month > 4 else year - 1
    from_month = max(1, month - 4)
    to_year = year if month < 9 else year + 1
    to_month = min(12, month + 4)

    from_date = f"{from_year}{from_month:02d}01"
    to_date = f"{to_year}{to_month:02d}28"

    strategies = [
        # 1. Direct PDF on openknowledge
        {
            "url": "openknowledge.worldbank.org/bitstream/handle/10986/*/CMO*Outlook*.pdf",
            "matchType": "prefix",
            "output": "json",
            "filter": "statuscode:200",
            "fl": "timestamp,original",
            "limit": "5",
            "from": from_date,
            "to": to_date,
            "collapse": "original",
        },
        # 2. Landing page on openknowledge (commodity+outlook in path)
        {
            "url": "openknowledge.worldbank.org/*commodity*outlook*",
            "matchType": "prefix",
            "output": "json",
            "filter": "statuscode:200",
            "fl": "timestamp,original",
            "limit": "5",
            "from": from_date,
            "to": to_date,
            "collapse": "original",
        },
        # 3. documents.worldbank.org
        {
            "url": "documents.worldbank.org/*commodity*markets*outlook*",
            "matchType": "prefix",
            "output": "json",
            "filter": "statuscode:200",
            "fl": "timestamp,original",
            "limit": "5",
            "from": from_date,
            "to": to_date,
            "collapse": "original",
        },
        # 4. openknowledge handle search
        {
            "url": f"openknowledge.worldbank.org/handle/10986/*",
            "matchType": "prefix",
            "output": "json",
            "filter": ["statuscode:200", f"original:.*commodity.*outlook.*"],
            "fl": "timestamp,original",
            "limit": "5",
            "from": from_date,
            "to": to_date,
            "collapse": "original",
        },
    ]

    for i, params in enumerate(strategies, 1):
        hits = _cdx_query(params, session)
        if not hits:
            continue

        for ts, original in hits:
            print(f"    CDX strategy {i}: {original}")
            # If it's a direct PDF, wrap in Wayback replay and return
            if original.lower().endswith(".pdf"):
                replay = f"https://web.archive.org/web/{ts}/{original}"
                print(f"    → direct PDF: {replay}")
                return replay

            # Otherwise fetch the archived landing page and extract bitstream
            url = _resolve_wayback_url(ts, original, session)
            if url:
                print(f"    → resolved: {url}")
                return url

        time.sleep(0.3)

    return None


def phase3(entries: list[dict], session: requests.Session, year_max: int = 2013) -> list[dict]:
    """Enhanced Wayback CDX search for entries up to year_max that are still unresolved."""
    candidates = [
        e for e in entries
        if e.get("wayback_needed") and int(e["release_date"][:4]) <= year_max
    ]
    print(f"\n[Phase 3] {len(candidates)} entries to resolve (pre-{year_max + 1})\n")

    _MONTH_MAP = {
        "January": 1, "February": 2, "March": 3, "April": 4,
        "May": 5, "June": 6, "July": 7, "August": 8,
        "September": 9, "October": 10, "November": 11, "December": 12,
    }

    results = []
    for entry in candidates:
        release_date = entry["release_date"]
        label = entry["label"]
        year = int(release_date[:4])
        month = _MONTH_MAP.get(label, int(release_date[5:7]))

        print(f"  {release_date}  ({label} {year})")
        url = _wayback_search_one(year, month, label, session)

        if url:
            results.append({
                "release_date": release_date,
                "url": url,
                "notes": f"Wayback CDX: {label} {year}",
            })
        else:
            print(f"    ✗ not found in Wayback")
            results.append({"release_date": release_date, "url": None, "notes": None})

        time.sleep(SLEEP_S)

    return results


# ---------------------------------------------------------------------------
# Manifest patching
# ---------------------------------------------------------------------------

def patch_manifest(resolved: list[dict]) -> None:
    """Write resolved URLs back into the manifest YAML using text replacement."""
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    patched = 0
    skipped = 0

    for r in resolved:
        if not r.get("url"):
            skipped += 1
            continue

        release_date = r["release_date"]
        url = r["url"]
        notes = r["notes"] or ""

        # Find the block for this release_date and replace url / wayback_needed / notes
        # We target the three lines that always appear together in that entry's block.
        old_url_line = f'    url: ""'
        new_url_line = f'    url: "{url}"'

        # Build a pattern that uniquely identifies the block for this release_date
        old_block = (
            f'  - release_date: "{release_date}"\n'
            f'    release_type: '
        )

        # The block starts at release_date; we need to replace url + wayback_needed + notes.
        # Use a regex on the full text to find the specific entry and do all three replacements
        # within its scope (from its release_date line to the blank line after notes).

        entry_pattern = re.compile(
            r"(  - release_date: \"" + re.escape(release_date) + r"\".*?"
            r'    url: )""'
            r"(.*?    wayback_needed: )true"
            r'(.*?    notes: )"[^"]*"',
            re.DOTALL,
        )

        def replacer(m: re.Match) -> str:
            escaped_url = url.replace('"', '\\"')
            escaped_notes = notes.replace('"', '\\"')
            return (
                m.group(1) + f'"{escaped_url}"'
                + m.group(2) + "false"
                + m.group(3) + f'"{escaped_notes}"'
            )

        new_text, n = entry_pattern.subn(replacer, text)
        if n == 1:
            text = new_text
            patched += 1
            print(f"  Patched {release_date}")
        elif n == 0:
            print(f"  WARNING: could not find block for {release_date} in manifest")
        else:
            print(f"  WARNING: multiple matches for {release_date} — skipping")

    MANIFEST_PATH.write_text(text, encoding="utf-8")
    print(f"\nManifest updated: {patched} patched, {skipped} skipped (no URL found)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", type=int, default=1, choices=[1, 2, 3],
        help="Which resolution phase to run (default: 1)",
    )
    parser.add_argument(
        "--patch", action="store_true",
        help="Write resolved URLs back to the manifest YAML",
    )
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "application/json"})

    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries: list[dict] = manifest["reports"]

    if args.phase == 1:
        results = phase1(entries, session)
    elif args.phase == 2:
        results = phase2(entries, session)
    else:
        results = phase3(entries, session)

    resolved = [r for r in results if r.get("url")]
    unresolved = [r for r in results if not r.get("url")]

    print(f"\n--- Summary ---")
    print(f"  Resolved:   {len(resolved)}")
    print(f"  Unresolved: {len(unresolved)}")
    if unresolved:
        print(f"  Still needed: {[r['release_date'] for r in unresolved]}")

    if args.patch and resolved:
        print(f"\nPatching manifest …")
        patch_manifest(resolved)
    elif resolved and not args.patch:
        print(f"\nRun with --patch to write these URLs back to the manifest.")


if __name__ == "__main__":
    main()
