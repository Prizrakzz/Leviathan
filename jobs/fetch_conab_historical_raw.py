"""Fetch historical CONAB Boletim da Safra de Café PDFs to raw S3.

Discovery input
---------------
Reads conab_joomla_gids.json produced by probe_wayback_conab.py.
Each entry maps a (safra_year, levantamento) to a Joomla item/download
gid+hash URL that served the PDF on the old conab.gov.br Joomla site.
Multiple gid candidates may exist per bulletin (e.g. original upload
and a later re-upload under a different Joomla article ID).

Download strategy (tried in order per bulletin)
------------------------------------------------
1. Wayback Machine — exact snapshot timestamp from the listing page.
   The Wayback crawler often co-crawls linked resources at the same
   session, so this timestamp gives the highest hit probability.

2. Wayback Machine — best available capture via CDX API per-URL lookup.
   Queries web.archive.org/cdx for any 200-status capture of the
   original conab.gov.br download URL, then fetches that snapshot.

3. Wayback Machine — no specific timestamp (Wayback redirects to nearest).
   Catches captures not indexed under a 200 status in CDX.

4. Direct conab.gov.br — via curl_cffi (TLS impersonation).
   The main domain redirects to gov.br/conab, but deep /item/download/
   paths may still resolve on the old server.

All four strategies are tried for each gid candidate.  If the first
candidate gid fails all strategies, the next candidate is tried.

S3 key mapping
--------------
  safra_year N  → crop_year = "{N-1}_{str(N)[2:]}"  e.g. 2022 → "2021_22"
  levantamento X → survey_number = X
  key = raw_conab_key(crop_year, survey_number)

Manifest update
---------------
Successfully fetched bulletins are appended to
configs/sources/conab_archive.yaml so that fetch_conab_raw.py can
re-download from the verified Wayback URL on future runs without
needing to repeat the CDX lookups.

Idempotency
-----------
--skip-existing-s3  skips keys already present in S3.
--dry-run           prints candidate URLs, no downloads.
--limit N           process at most N distinct bulletins (use 1 to smoke-test).
"""
from __future__ import annotations

import argparse
import json
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

import yaml
from curl_cffi import requests as curl_requests

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_conab_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PDF_MAGIC = b"%PDF"
_IMPERSONATE = "chrome124"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

_JOOMLA_DOWNLOAD_BASE = (
    "https://www.conab.gov.br/info-agro/safras/cafe/"
    "boletim-da-safra-de-cafe/item/download"
)
_GID_JSON_PATH = Path(__file__).parent.parent / "data" / "conab" / "conab_joomla_gids.json"
_MANIFEST_PATH = (
    Path(__file__).parent.parent / "configs" / "sources" / "conab_archive.yaml"
)

_SSL_CTX = ssl.create_default_context()

# ---------------------------------------------------------------------------
# Crop-year helpers
# ---------------------------------------------------------------------------


def _safra_to_crop_year(safra_year: int) -> str:
    """CONAB marketing year runs April–March.

    safra 2022 = April 2021–March 2022 → crop_year "2021_22"
    safra 2018 = April 2017–March 2018 → crop_year "2017_18"
    """
    return f"{safra_year - 1}_{str(safra_year)[2:]}"


# ---------------------------------------------------------------------------
# Wayback CDX lookup
# ---------------------------------------------------------------------------


def _cdx_lookup(original_url: str, timeout: int = 20) -> Optional[str]:
    """Return the earliest confirmed-PDF Wayback capture timestamp, or None."""
    api_url = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={urllib.parse.quote(original_url, safe='')}"
        "&output=json&fl=timestamp&limit=1"
        "&filter=statuscode:200&filter=mimetype:application/pdf"
    )
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
            rows = json.loads(resp.read())
            # CDX returns [[header], [ts]] or [] — skip any header row
            for row in rows:
                ts = row[0] if row else None
                if ts and len(ts) >= 14 and ts[:14].isdigit():
                    return ts[:14]
    except Exception as exc:
        logger.debug("CDX lookup failed %s: %s", original_url[-60:], exc)
    return None


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------


def _wayback_get(url: str, timeout: int = 90) -> Optional[bytes]:
    """Fetch a URL from Wayback Machine via urllib (no TLS impersonation needed)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
            data = resp.read()
            if data and len(data) > 512:
                return data
    except Exception as exc:
        logger.debug("Wayback GET failed %s: %s", url[-70:], exc)
    return None


def _direct_get(
    url: str, session: curl_requests.Session, timeout: int = 90
) -> Optional[bytes]:
    """Fetch directly from conab.gov.br using curl_cffi (TLS impersonation)."""
    try:
        resp = session.get(
            url, impersonate=_IMPERSONATE, timeout=timeout, allow_redirects=True
        )
        if resp.status_code == 200 and len(resp.content) > 512:
            return resp.content
    except Exception as exc:
        logger.debug("Direct GET failed %s: %s", url[-70:], exc)
    return None


def _download_bulletin(
    gid_hash: str,
    snap_ts: Optional[str],
    session: curl_requests.Session,
) -> tuple[Optional[bytes], Optional[str]]:
    """Try all download strategies for one gid_hash.

    Returns (pdf_bytes, source_url) on success, (None, None) on failure.

    Key insight: Wayback Machine's ``if_`` modifier bypasses HTML playback
    injection and serves the raw captured bytes directly.  Without it,
    Wayback wraps the content in the toolbar and follows stored redirects
    to the live site (which now serves HTML, not PDFs).  With ``if_``,
    requesting any nearby timestamp works because Wayback redirects
    internally to the nearest capture and then serves those raw bytes.
    """
    original_url = f"{_JOOMLA_DOWNLOAD_BASE}/{gid_hash}"

    # Build strategy list
    strategies: list[tuple[str, str]] = []

    # 1. Wayback with listing-page snapshot timestamp + if_ modifier.
    #    Wayback redirects internally to the nearest actual capture and
    #    serves the raw bytes (PDF) without following stored redirects.
    if snap_ts:
        strategies.append(
            ("wayback_snap_if", f"https://web.archive.org/web/{snap_ts}if_/{original_url}")
        )

    # 2. CDX lookup for the exact capture timestamp + if_ modifier.
    #    Falls back to this when the listing snap_ts misses.
    cdx_ts = _cdx_lookup(original_url)
    if cdx_ts and cdx_ts != snap_ts:
        strategies.append(
            ("wayback_cdx_if", f"https://web.archive.org/web/{cdx_ts}if_/{original_url}")
        )

    # 3. Direct conab.gov.br (deep download routes may bypass top-level redirect)
    strategies.append(("direct_conab", original_url))

    for strategy, url in strategies:
        logger.debug("    Trying %s: %s", strategy, url[-70:])

        if "wayback" in strategy:
            data = _wayback_get(url)
        else:
            data = _direct_get(url, session)

        if data and data[:4] == _PDF_MAGIC:
            logger.info(
                "    ✓ %s  (%.1f KB)  via %s",
                gid_hash[:20],
                len(data) / 1024,
                strategy,
            )
            return data, url

        if data:
            # Got bytes but not a PDF — log a snippet to help diagnose
            logger.debug(
                "    Non-PDF response via %s: %s…", strategy, data[:80]
            )

    return None, None


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def _manifest_existing_keys(manifest_path: Path) -> set[tuple[str, int]]:
    """Return set of (crop_year, survey_number) already in the manifest."""
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    return {
        (str(e["crop_year"]), int(e["survey_number"]))
        for e in (data.get("surveys") or [])
    }


def _append_to_manifest(new_entries: list[dict], manifest_path: Path) -> None:
    """Append historical bulletin entries to conab_archive.yaml.

    Appends as plain text to preserve all existing YAML comments.
    Groups new entries by crop_year, newest-first.
    """
    if not new_entries:
        return

    by_year: dict[str, list[dict]] = {}
    for e in new_entries:
        by_year.setdefault(e["crop_year"], []).append(e)

    lines: list[str] = [
        "\n"
        "  # ── Historical bulletins (Wayback Machine, pre-2023) ─────────────────────────\n"
    ]
    for crop_year in sorted(by_year.keys(), reverse=True):
        safra_year = int(crop_year[:4]) + 1
        year_entries = sorted(
            by_year[crop_year], key=lambda x: x["survey_number"], reverse=True
        )
        lines.append(
            f"\n  # ── Safra {safra_year} (crop year {crop_year}) "
            f"──────────────────────────────────────\n"
        )
        for e in year_entries:
            lines.append(f'  - crop_year: "{e["crop_year"]}"\n')
            lines.append(f'    survey_number: {e["survey_number"]}\n')
            lines.append(f'    pdf_url: "{e["pdf_url"]}"\n')

    with open(manifest_path, "a", encoding="utf-8") as fh:
        fh.writelines(lines)

    logger.info(
        "Appended %d historical entries to %s", len(new_entries), manifest_path.name
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch historical CONAB coffee bulletin PDFs from Wayback Machine → S3. "
            "Reads conab_joomla_gids.json (run probe_wayback_conab.py first)."
        )
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip bulletins whose S3 key already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print all candidate URLs without downloading.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=2.0,
        help="Polite delay between download requests in seconds (default: 2.0).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process at most N distinct bulletins — use 1 for a smoke test.",
    )
    args = parser.parse_args()

    # -----------------------------------------------------------------------
    # Load gid candidates
    # -----------------------------------------------------------------------
    if not _GID_JSON_PATH.exists():
        parser.error(
            f"Not found: {_GID_JSON_PATH}\n"
            "  Run: .venv\\Scripts\\python.exe probe_wayback_conab.py"
        )

    raw_entries: list[dict] = json.loads(_GID_JSON_PATH.read_text(encoding="utf-8"))
    logger.info("Loaded %d gid entries from %s", len(raw_entries), _GID_JSON_PATH.name)

    # Group by (safra_year, levantamento) → list of candidate gid entries
    # Multiple gids per bulletin = multiple upload events on the old Joomla site
    candidates: dict[tuple[int, int], list[dict]] = {}
    for e in raw_entries:
        key = (int(e["safra_year"]), int(e["levantamento"]))
        candidates.setdefault(key, []).append(e)

    # Process most-recent bulletins first
    sorted_keys = sorted(candidates.keys(), reverse=True)

    # -----------------------------------------------------------------------
    # Dry run
    # -----------------------------------------------------------------------
    if args.dry_run:
        print(
            f"Dry run: {len(sorted_keys)} distinct bulletins, "
            f"{len(raw_entries)} total gid candidates"
        )
        for safra, lev in sorted_keys:
            crop_year = _safra_to_crop_year(safra)
            s3_key = raw_conab_key(crop_year, lev)
            print(f"  {lev}º Safra {safra}  ({crop_year})  →  {s3_key}")
            for c in candidates[(safra, lev)]:
                print(f"    gid: {c['gid_hash']}  snap_ts: {c.get('wayback_snap_ts')}")
        return

    # -----------------------------------------------------------------------
    # Download & upload
    # -----------------------------------------------------------------------
    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    existing_in_manifest = _manifest_existing_keys(_MANIFEST_PATH)

    if args.limit:
        sorted_keys = sorted_keys[: args.limit]

    uploaded = skipped = errors = 0
    missing: list[str] = []
    new_manifest_entries: list[dict] = []

    with curl_requests.Session() as session:
        for safra_year, levantamento in sorted_keys:
            crop_year = _safra_to_crop_year(safra_year)
            survey_number = levantamento
            s3_key = raw_conab_key(crop_year, survey_number)
            label = f"{levantamento}º Safra {safra_year} (crop_year={crop_year})"

            try:
                if args.skip_existing_s3 and s3_object_exists(bucket, s3_key, region):
                    logger.info("Skipping — already in S3: %s", s3_key)
                    skipped += 1
                    continue

                logger.info("Downloading %s …", label)

                pdf_bytes: Optional[bytes] = None
                source_url: Optional[str] = None

                # Try every candidate gid for this bulletin until one works
                for candidate in candidates[(safra_year, levantamento)]:
                    pdf_bytes, source_url = _download_bulletin(
                        candidate["gid_hash"],
                        candidate.get("wayback_snap_ts"),
                        session,
                    )
                    if pdf_bytes is not None:
                        break

                if pdf_bytes is None:
                    logger.warning("All strategies failed for %s", label)
                    missing.append(label)
                    errors += 1
                    time.sleep(args.sleep_seconds)
                    continue

                check_min_file_size(pdf_bytes, "conab", context=source_url)

                upload_bytes_to_s3(pdf_bytes, bucket, s3_key, region)
                write_raw_s3_metadata(
                    bucket, s3_key, pdf_bytes, source_url, "application/pdf", region
                )

                logger.info(
                    "Uploaded %s  (%.1f MB)  →  s3://%s/%s",
                    label,
                    len(pdf_bytes) / 1_048_576,
                    bucket,
                    s3_key,
                )
                uploaded += 1

                # Queue for manifest append (only if not already recorded)
                if (crop_year, survey_number) not in existing_in_manifest:
                    new_manifest_entries.append(
                        {
                            "crop_year": crop_year,
                            "survey_number": survey_number,
                            "pdf_url": source_url,
                        }
                    )

            except Exception as exc:  # noqa: BLE001
                logger.error("Failed %s: %s", label, exc)
                missing.append(label)
                errors += 1

            time.sleep(args.sleep_seconds)

    # -----------------------------------------------------------------------
    # Persist manifest updates
    # -----------------------------------------------------------------------
    if new_manifest_entries:
        _append_to_manifest(new_manifest_entries, _MANIFEST_PATH)

    # -----------------------------------------------------------------------
    # Final summary
    # -----------------------------------------------------------------------
    logger.info(
        "Done.  uploaded=%d  skipped=%d  errors=%d", uploaded, skipped, errors
    )

    if missing:
        logger.warning(
            "Bulletins not retrieved (%d) — Wayback has no capture or all strategies failed:",
            len(missing),
        )
        for item in sorted(missing):
            logger.warning("  MISSING: %s", item)
    else:
        logger.info("All bulletins retrieved successfully.")


if __name__ == "__main__":
    main()
