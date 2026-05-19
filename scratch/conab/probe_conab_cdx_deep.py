"""Discover pre-2013 CONAB coffee bulletin PDFs via Wayback CDX API.

Queries CDX for all archived item/download URLs from the old
conab.gov.br Joomla site that were captured as application/pdf with
HTTP 200.  Filters to gid_hashes NOT already in conab_joomla_gids.json,
downloads each full PDF via Wayback if_ modifier, classifies by
(safra_year, levantamento) using pdfplumber, and writes
data/conab/conab_cdx_gids.json in the same schema as
conab_joomla_gids.json.

Run from project root:
    .venv\\Scripts\\python.exe scratch/conab/probe_conab_cdx_deep.py [--dry-run]
"""
from __future__ import annotations

import argparse
import io
import json
import re
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

import pdfplumber

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parent.parent.parent
_KNOWN_GIDS_PATH = _ROOT / "data" / "conab" / "conab_joomla_gids.json"
_OUTPUT_PATH = _ROOT / "data" / "conab" / "conab_cdx_gids.json"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_SSL_CTX = ssl.create_default_context()
_PDF_MAGIC = b"%PDF"
_CDX_API = "https://web.archive.org/cdx/search/cdx"
_CONAB_DL_PREFIX = (
    "www.conab.gov.br/info-agro/safras/cafe/"
    "boletim-da-safra-de-cafe/item/download"
)

# Regex patterns for cover-page classification (from probe_gid_titles.py)
_LEV_RE = re.compile(r"(\d)\s*[oºo°]\.?\s*[Ll]evantamento", re.IGNORECASE)
_SAFRA_RE = re.compile(r"[Ss]afra\s+(\d{4})", re.IGNORECASE)
_SAFRA_LOOSE_RE = re.compile(r"\bsafra\b.*?(\d{4})", re.IGNORECASE | re.DOTALL)

# ---------------------------------------------------------------------------
# CDX discovery
# ---------------------------------------------------------------------------


def _cdx_query_all_downloads(timeout: int = 90) -> list[dict]:
    """Return list of {gid_hash, wayback_ts, original_url} from CDX."""
    # Build query string manually — urllib.parse.urlencode encodes slashes in
    # the `url=` value as %2F which breaks CDX prefix lookups.
    import urllib.parse as _up
    filters = "filter=mimetype%3Aapplication%2Fpdf&filter=statuscode%3A200"
    qs = (
        f"url={_CONAB_DL_PREFIX}*"
        f"&matchType=prefix"
        f"&output=json"
        f"&fl=original%2Ctimestamp"
        f"&{filters}"
        f"&collapse=original"
        f"&limit=1000"
    )
    cdx_url = f"{_CDX_API}?{qs}"
    print(f"CDX query: {cdx_url[:120]}...")

    req = urllib.request.Request(cdx_url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
        rows = json.loads(resp.read())

    results: list[dict] = []
    for row in rows:
        # CDX may include a header row like ["original", "timestamp"]
        if not row or not row[1][:8].isdigit():
            continue
        original_url, ts = row[0], row[1]
        m = re.search(r"/item/download/(\d+_[a-f0-9]+)", original_url)
        if m:
            results.append(
                {
                    "gid_hash": m.group(1),
                    "wayback_ts": ts,
                    "original_url": original_url,
                }
            )
    print(f"CDX returned {len(results)} unique PDF captures")
    return results


# ---------------------------------------------------------------------------
# PDF fetching
# ---------------------------------------------------------------------------


def _fetch_pdf(original_url: str, ts: str, timeout: int = 60) -> Optional[bytes]:
    """Download PDF via Wayback if_ modifier (full file, no Range header)."""
    wb_url = f"https://web.archive.org/web/{ts}if_/{original_url}"
    try:
        req = urllib.request.Request(wb_url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
            data = resp.read()
            if data and data[:4] == _PDF_MAGIC:
                return data
            print(f"    Bad magic: {data[:8]!r}")
            return None
    except Exception as exc:
        print(f"    FETCH ERROR: {exc}")
        return None


# ---------------------------------------------------------------------------
# PDF classification
# ---------------------------------------------------------------------------


def _classify_pdf(data: bytes) -> tuple[Optional[int], Optional[int]]:
    """Return (levantamento, safra_year) from PDF cover-page text.

    Returns (None, None) if classification fails.
    """
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if not pdf.pages:
                return None, None
            text = pdf.pages[0].extract_text() or ""
    except Exception as exc:
        print(f"    pdfplumber error: {exc}")
        return None, None

    lev_m = _LEV_RE.search(text)
    safra_m = _SAFRA_RE.search(text) or _SAFRA_LOOSE_RE.search(text)
    lev = int(lev_m.group(1)) if lev_m else None
    safra = int(safra_m.group(1)) if safra_m else None
    return lev, safra


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show discovered gid_hashes without downloading or classifying PDFs.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=2.0,
        metavar="S",
        help="Polite delay between Wayback requests in seconds (default: 2.0).",
    )
    args = parser.parse_args()

    # Load known gid_hashes from Joomla listing scrape
    known_raw: list[dict] = json.loads(_KNOWN_GIDS_PATH.read_text(encoding="utf-8"))
    known_hashes: set[str] = {e["gid_hash"] for e in known_raw}
    print(f"Loaded {len(known_hashes)} known gid_hashes from {_KNOWN_GIDS_PATH.name}")

    # CDX discovery
    all_captures = _cdx_query_all_downloads()
    time.sleep(2)

    # Filter to new-only
    new_captures = [c for c in all_captures if c["gid_hash"] not in known_hashes]
    print(f"New gid_hashes (not in joomla gids): {len(new_captures)}")

    if args.dry_run:
        print("\nDRY RUN — discovered gid_hashes:")
        for c in sorted(new_captures, key=lambda x: x["wayback_ts"]):
            print(f"  gid={c['gid_hash']:<45}  ts={c['wayback_ts'][:8]}")
        return

    if not new_captures:
        print("Nothing new to classify — writing empty output.")
        _OUTPUT_PATH.write_text("[]", encoding="utf-8")
        return

    # Classify each new PDF
    results: list[dict] = []
    unclassified: list[str] = []

    for i, capture in enumerate(new_captures, 1):
        gid = capture["gid_hash"]
        ts = capture["wayback_ts"]
        original = capture["original_url"]
        print(f"\n[{i}/{len(new_captures)}] gid={gid}  ts={ts[:8]}")

        data = _fetch_pdf(original, ts)
        if data is None:
            print("    SKIP — no valid PDF bytes")
            unclassified.append(gid)
            time.sleep(args.sleep_seconds)
            continue

        print(f"    Got {len(data):,} bytes", end="  ")
        lev, safra = _classify_pdf(data)

        if lev is not None and safra is not None:
            entry = {
                "safra_year": safra,
                "levantamento": lev,
                "label": f"CDX-discovered  gid={gid}",
                "gid_hash": gid,
                "wayback_snap_ts": ts,
            }
            results.append(entry)
            print(f"→  {lev}º Safra {safra}")
        else:
            print(f"→  UNCLASSIFIED (lev={lev}, safra={safra})")
            unclassified.append(gid)

        time.sleep(args.sleep_seconds)

    # Sort newest-first so fetch_conab_historical skips recent already-ingested ones fast
    results.sort(key=lambda x: (x["safra_year"], x["levantamento"]), reverse=True)

    # Write output
    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_PATH.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nSaved {len(results)} classified entries → {_OUTPUT_PATH}")

    # Coverage summary
    by_year: dict[int, list[int]] = {}
    for e in results:
        by_year.setdefault(e["safra_year"], []).append(e["levantamento"])

    print("\nCoverage by safra year:")
    for year in sorted(by_year.keys(), reverse=True):
        levs = sorted(set(by_year[year]))
        print(f"  Safra {year}: levantamentos {levs}")

    if unclassified:
        print(
            f"\nUnclassified ({len(unclassified)}): "
            f"{unclassified[:5]}{'...' if len(unclassified) > 5 else ''}"
        )


if __name__ == "__main__":
    main()
