"""Discover UNICA biweekly bulletins on Wayback Machine not yet in the manifest.

Usage (from repo root):
    python jobs/ingest/discover_unica_wayback.py                   # report only
    python jobs/ingest/discover_unica_wayback.py --update-manifest # also append to manifest
    python jobs/ingest/discover_unica_wayback.py --no-liveness-check  # skip HEAD requests

Phases
------
A  Query CDX API for all unicadata.com.br/arquivos/pdfs/* snapshots (status 200).
   Reports new-to-manifest bulletin counts per harvest_year.
B  HEAD-check each new URL against the live unicadata.com.br server to determine
   whether the original URL still works or needs a Wayback replay URL.
C  Save full results to scratch/unica_cdx_results.json.
   With --update-manifest, append new entries to the manifest YAML.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.parent
MANIFEST_PATH = REPO_ROOT / "configs" / "sources" / "unica_biweekly_manifest.yaml"
SOURCES_PATH = REPO_ROOT / "configs" / "sources" / "unica_biweekly_sources.yaml"
RESULTS_PATH = REPO_ROOT / "data" / "metadata" / "unica_cdx_results.json"

# ---------------------------------------------------------------------------
# CDX API
# ---------------------------------------------------------------------------

# Query year-by-year to avoid large wildcard timeouts on the CDX API.
# unicadata PDFs live at: unicadata.com.br/arquivos/pdfs/YYYY/MM/{hash}.pdf
_CDX_YEAR_TMPL = (
    "https://web.archive.org/cdx/search/cdx"
    "?url=unicadata.com.br/arquivos/pdfs/{year}/*"
    "&output=json"
    "&fl=timestamp,original,statuscode"
    "&filter=statuscode:200"
    "&collapse=original"
    "&limit=2000"
)

# Calendar years to probe: 2012â€“2026 (maps to harvest seasons 2012/13â€“2026/27)
_CDX_YEARS = list(range(2012, 2027))

# Seconds to wait between HEAD requests â€” be polite to both servers.
_HEAD_TIMEOUT_S = 15
_SLEEP_BETWEEN_HEADS_S = 0.4
_SLEEP_BETWEEN_CDX_S = 1.5   # polite gap between per-year CDX calls

# ---------------------------------------------------------------------------
# Harvest-year logic (mirrors fetch_unica_biweekly.py)
# ---------------------------------------------------------------------------

def _pub_ym_to_harvest_year(pub_year: int, pub_month: int) -> str:
    """Map publication year/month â†’ UNICA harvest year string (e.g. '2024/2025').

    Brazil's milling season runs Aprilâ€“November.  Bulletins published Janâ€“Mar
    belong to the season that started the previous April.
    """
    season_start = pub_year - 1 if pub_month <= 3 else pub_year
    return f"{season_start}/{season_start + 1}"


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

_PDF_URL_RE = re.compile(
    r"/arquivos/pdfs/(\d{4})/(\d{2})/([0-9a-f]{16,})\.pdf", re.IGNORECASE
)


def _parse_pdf_url(original_url: str) -> dict | None:
    """Return parsed fields from a unicadata PDF URL, or None if no match."""
    m = _PDF_URL_RE.search(original_url)
    if not m:
        return None
    pub_year, pub_month, pdf_hash = int(m.group(1)), int(m.group(2)), m.group(3)
    return {
        "pub_year": pub_year,
        "pub_month": pub_month,
        "pdf_hash": pdf_hash,
        "published_ym": f"{pub_year:04d}/{pub_month:02d}",
        "harvest_year": _pub_ym_to_harvest_year(pub_year, pub_month),
    }


# ---------------------------------------------------------------------------
# CDX fetch
# ---------------------------------------------------------------------------

def fetch_cdx() -> list[dict]:
    """Fetch CDX records for unicadata PDFs, querying one calendar year at a time.

    Per-year queries are smaller and much faster than a single wildcard query
    across all years (which reliably times out on the CDX API).
    """
    all_records: list[dict] = []
    for year in _CDX_YEARS:
        url = _CDX_YEAR_TMPL.format(year=year)
        print(f"  CDX {year}: {url}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "research-bot/1.0"})
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read())
        except Exception as exc:
            print(f"  CDX {year}: ERROR â€” {exc}")
            time.sleep(_SLEEP_BETWEEN_CDX_S)
            continue

        if not data or len(data) <= 1:
            print(f"  CDX {year}: 0 results")
            time.sleep(_SLEEP_BETWEEN_CDX_S)
            continue

        fields = data[0]
        records = [dict(zip(fields, row)) for row in data[1:]]
        print(f"  CDX {year}: {len(records)} snapshots")
        all_records.extend(records)
        time.sleep(_SLEEP_BETWEEN_CDX_S)

    return all_records


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def load_manifest() -> list[dict]:
    raw = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    return (raw.get("bulletins") or []) if raw else []


def _known_hashes(bulletins: list[dict]) -> set[str]:
    """Extract PDF hashes from the pdf_url field of all known bulletins."""
    hashes: set[str] = set()
    for b in bulletins:
        url = b.get("pdf_url") or ""
        m = _PDF_URL_RE.search(url)
        if m:
            hashes.add(m.group(3))
    return hashes


# ---------------------------------------------------------------------------
# Liveness check
# ---------------------------------------------------------------------------

def head_check(url: str) -> int:
    """Return HTTP status code for HEAD request, or 0 on network error."""
    try:
        req = urllib.request.Request(
            url,
            method="HEAD",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=_HEAD_TIMEOUT_S) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Manifest append
# ---------------------------------------------------------------------------

_YAML_ENTRY_TMPL = """\
  - harvest_year: "{harvest_year}"
    idm: "pdf_{pdf_hash}"
    bulletin_num: None
    published_ym: "{published_ym}"
    pdf_url: '{pdf_url}'
    download_url: null
"""


def append_to_manifest(new_entries: list[dict]) -> None:
    """Append new bulletin entries to the manifest YAML, preserving header comments."""
    original = MANIFEST_PATH.read_text(encoding="utf-8")

    # Sort for a clean, predictable YAML ordering
    sorted_entries = sorted(new_entries, key=lambda x: (x["harvest_year"], x["published_ym"]))

    blocks = [_YAML_ENTRY_TMPL.format(**e) for e in sorted_entries]
    updated = original.rstrip() + "\n" + "".join(blocks)
    MANIFEST_PATH.write_text(updated, encoding="utf-8")
    print(f"Appended {len(new_entries)} entries to {MANIFEST_PATH.name}.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Probe Wayback Machine CDX for UNICA biweekly PDFs not in the manifest."
    )
    parser.add_argument(
        "--update-manifest",
        action="store_true",
        help="Append new entries to configs/sources/unica_biweekly_manifest.yaml",
    )
    parser.add_argument(
        "--no-liveness-check",
        action="store_true",
        help="Skip HEAD requests to unicadata.com.br (faster, but pdf_url may be stale)",
    )
    args = parser.parse_args()

    # â”€â”€ Phase A: CDX fetch â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print("=== Phase A: Fetching CDX records from Wayback Machine ===")
    cdx_records = fetch_cdx()
    print(f"CDX records returned: {len(cdx_records)}")

    # Parse PDF URLs
    parsed: list[dict] = []
    skipped = 0
    for rec in cdx_records:
        info = _parse_pdf_url(rec["original"])
        if info:
            parsed.append({**rec, **info})
        else:
            skipped += 1
    print(f"Parsed as PDF URLs: {len(parsed)}  (skipped non-matching: {skipped})")

    # CDX coverage by harvest_year
    cdx_by_year: defaultdict[str, list] = defaultdict(list)
    for p in parsed:
        cdx_by_year[p["harvest_year"]].append(p)
    print("\n--- CDX archive coverage by harvest_year ---")
    for yr in sorted(cdx_by_year):
        print(f"  {yr}: {len(cdx_by_year[yr])} snapshots archived")

    # â”€â”€ Load manifest â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    bulletins = load_manifest()
    known = _known_hashes(bulletins)
    existing_by_year = Counter(b["harvest_year"] for b in bulletins)
    print(f"\nManifest: {len(bulletins)} bulletins ({len(known)} with parseable hash)")
    print("\n--- Existing manifest counts by harvest_year ---")
    for yr in sorted(existing_by_year):
        print(f"  {yr}: {existing_by_year[yr]}")

    # â”€â”€ Filter to new entries â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    new = [p for p in parsed if p["pdf_hash"] not in known]
    print(f"\nNew bulletins not in manifest: {len(new)}")

    new_by_year: defaultdict[str, list] = defaultdict(list)
    for p in new:
        new_by_year[p["harvest_year"]].append(p)
    if new_by_year:
        print("\n--- New bulletins by harvest_year ---")
        for yr in sorted(new_by_year):
            print(f"  {yr}: {len(new_by_year[yr])} new")
    else:
        print("  (nothing new found in CDX)")

    # â”€â”€ Phase B: Liveness check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if not args.no_liveness_check and new:
        print(f"\n=== Phase B: Liveness check ({len(new)} URLs) ===")
        live_count = 0
        dead_count = 0
        for i, entry in enumerate(new):
            status = head_check(entry["original"])
            entry["live_status"] = status
            if status == 200:
                live_count += 1
            else:
                dead_count += 1
            if i % 5 == 0 or status != 200:
                tag = "LIVE" if status == 200 else f"DEAD({status})"
                print(f"  [{i+1:3d}/{len(new)}] {tag:12s}  ...{entry['original'][-65:]}")
            time.sleep(_SLEEP_BETWEEN_HEADS_S)

        print(f"\nLive (original URL works): {live_count}")
        print(f"Dead (need Wayback replay): {dead_count}")

        # Breakdown by harvest_year for dead URLs
        dead_entries = [e for e in new if e.get("live_status") != 200]
        if dead_entries:
            dead_by_year = Counter(e["harvest_year"] for e in dead_entries)
            print("\n--- Dead URLs by harvest_year ---")
            for yr in sorted(dead_by_year):
                print(f"  {yr}: {dead_by_year[yr]} dead")
    else:
        for entry in new:
            entry["live_status"] = None
        print("\nLiveness check skipped.")

    # â”€â”€ Save results â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)    RESULTS_PATH.write_text(
        json.dumps(new, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nResults saved â†’ {RESULTS_PATH} ({len(new)} entries)")

    # â”€â”€ Phase C: Manifest update â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if args.update_manifest and new:
        to_add: list[dict] = []
        for e in new:
            if e.get("live_status") == 200 or e.get("live_status") is None:
                pdf_url = e["original"]
            else:
                # Fall back to Wayback replay URL for dead originals
                pdf_url = f"https://web.archive.org/web/{e['timestamp']}/{e['original']}"
            to_add.append({
                "harvest_year": e["harvest_year"],
                "pdf_hash": e["pdf_hash"],
                "published_ym": e["published_ym"],
                "pdf_url": pdf_url,
            })
        append_to_manifest(to_add)

        print("\nNext: run the ingestion job to download and upload new PDFs:")
        print("  python jobs/ingest/fetch_unica_biweekly.py --skip-existing-s3")

    elif not args.update_manifest and new:
        print(f"\nRe-run with --update-manifest to append {len(new)} new entries to the manifest.")
    else:
        print("\nManifest is already up to date â€” nothing to add.")

    # â”€â”€ Final combined coverage table â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    all_years = sorted(set(cdx_by_year) | set(existing_by_year))
    print("\n=== Final coverage summary ===")
    print(f"  {'Season':<14}  {'In manifest':>12}  {'New from CDX':>13}  {'CDX total':>10}")
    print(f"  {'-'*14}  {'-'*12}  {'-'*13}  {'-'*10}")
    for yr in all_years:
        existing = existing_by_year.get(yr, 0)
        new_n = len(new_by_year.get(yr, []))
        cdx_n = len(cdx_by_year.get(yr, []))
        print(f"  {yr:<14}  {existing:>12}  {new_n:>13}  {cdx_n:>10}")


if __name__ == "__main__":
    main()
