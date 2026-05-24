"""Fetch pre-2013 CONAB Boletim da Safra de Café PDFs (OlalaCMS era) to raw S3.

Discovery input
---------------
Reads conab_olalacms_gids.json produced by
``scratch/conab/probe_conab_olalacms.py``.  Each entry maps a
(safra_year, pub_month) to an OlalaCMS file URL that served the bulletin
on the old conab.gov.br site.

OlalaCMS URL pattern
--------------------
  http://www.conab.gov.br/OlalaCMS/uploads/arquivos/{filename}

where ``filename`` is the OlalaCMS upload-timestamp-prefixed name, e.g.::

    11_09_13_12_12_02_boletim_cafe_-_setembro_-_2011..pdf

File-format handling
--------------------
Pre-2013 bulletins are predominantly PDFs but the Wayback Machine may have
captured some as OLE2 Word documents (magic ``d0cf11e0``).  Both are
accepted; the file extension is detected from the magic bytes and reflected
in the S3 key filename.

Download strategy (tried in order per entry)
--------------------------------------------
1. Wayback with ``wayback_snap_ts`` + ``if_`` modifier (raw bytes).
2. Wayback with CDX-looked-up timestamp + ``if_`` modifier.
3. Direct conab.gov.br via curl_cffi (TLS impersonation).

S3 key mapping
--------------
  safra_year N  → crop_year = "{N-1}_{str(N)[2:]}"   e.g. 2011 → "2010_11"
  pub_month  M  → survey_number = M  (1-12, not the quarterly 1-4 scheme)
  key = raw_conab_key(crop_year, survey_number, ext)

Idempotency
-----------
--skip-existing-s3  skips entries whose S3 key already exists.
--dry-run           prints candidate URLs without downloading.
--limit N           process at most N entries (smoke test).
"""
from __future__ import annotations

import argparse
import logging
import json
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path

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

# Magic bytes → (content_type, file_extension)
_VALID_MAGICS: dict[bytes, tuple[str, str]] = {
    b"%PDF":                               ("application/pdf",      ".pdf"),
    bytes.fromhex("d0cf11e0"):             ("application/msword",   ".doc"),
    bytes.fromhex("504b0304"):             (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
}

_IMPERSONATE = "chrome124"
_UA          = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

_OLALA_BASE   = "http://www.conab.gov.br/OlalaCMS/uploads/arquivos"
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_GID_JSON_PATH = _PROJECT_ROOT / "data" / "conab" / "conab_olalacms_gids.json"
_MANIFEST_PATH = _PROJECT_ROOT / "configs" / "sources" / "conab_archive.yaml"

_SSL_CTX = ssl.create_default_context()

# ---------------------------------------------------------------------------
# Crop-year helper (shared with fetch_conab_historical.py)
# ---------------------------------------------------------------------------


def _safra_to_crop_year(safra_year: int) -> str:
    """CONAB marketing year runs April-March.

    safra 2011 = April 2010 - March 2011  -> crop_year "2010_11"
    safra 2008 = April 2007 - March 2008  -> crop_year "2007_08"
    """
    return f"{safra_year - 1}_{str(safra_year)[2:]}"


# ---------------------------------------------------------------------------
# Magic detection
# ---------------------------------------------------------------------------


def _detect_format(data: bytes) -> tuple[str, str] | None:
    """Return (content_type, ext) if data starts with a known valid magic, else None."""
    for magic, fmt in _VALID_MAGICS.items():
        if data[:len(magic)] == magic:
            return fmt
    return None


# ---------------------------------------------------------------------------
# Wayback CDX lookup
# ---------------------------------------------------------------------------


def _cdx_lookup(original_url: str, timeout: int = 20) -> str | None:
    """Return the best Wayback capture timestamp for an OlalaCMS file URL.

    Unlike the Joomla job we do NOT filter by mimetype:application/pdf because
    OlalaCMS Word docs may be stored with mimetype application/octet-stream.
    """
    api_url = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={urllib.parse.quote(original_url, safe='')}"
        "&output=json&fl=timestamp&limit=1&filter=statuscode:200"
    )
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
            rows = json.loads(resp.read())
            for row in rows:
                ts = row[0] if row else None
                if ts and len(ts) >= 14 and ts[:14].isdigit():
                    return ts[:14]
    except Exception as exc:  # noqa: BLE001 — any network/HTTP error returns None; caller tries the next strategy
        logger.debug("CDX lookup failed %s: %s", original_url[-60:], exc)
    return None


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------


def _wayback_get(url: str, timeout: int = 90) -> bytes | None:
    """Fetch raw bytes from Wayback Machine via urllib."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
            data = resp.read()
            if data and len(data) > 512:
                return data
    except Exception as exc:  # noqa: BLE001 — any network/HTTP error returns None; caller tries the next strategy
        logger.debug("Wayback GET failed %s: %s", url[-70:], exc)
    return None


def _direct_get(
    url: str, session: curl_requests.Session, timeout: int = 90
) -> bytes | None:
    """Fetch directly from conab.gov.br using curl_cffi (TLS impersonation)."""
    try:
        resp = session.get(
            url, impersonate=_IMPERSONATE, timeout=timeout, allow_redirects=True
        )
        if resp.status_code == 200 and len(resp.content) > 512:
            return resp.content
    except Exception as exc:  # noqa: BLE001 — any network/HTTP error returns None; caller tries the next strategy
        logger.debug("Direct GET failed %s: %s", url[-70:], exc)
    return None


def _download_bulletin(
    olalacms_url: str,
    snap_ts: str | None,
    session: curl_requests.Session,
) -> tuple[bytes | None, str | None, str | None]:
    """Try all download strategies for one OlalaCMS file.

    Returns (file_bytes, source_url, file_ext) on success, or
    (None, None, None) on failure.
    """
    strategies: list[tuple[str, str]] = []

    if snap_ts:
        strategies.append(
            ("wayback_snap_if", f"https://web.archive.org/web/{snap_ts}if_/{olalacms_url}")
        )

    cdx_ts = _cdx_lookup(olalacms_url)
    if cdx_ts and cdx_ts != snap_ts:
        strategies.append(
            ("wayback_cdx_if", f"https://web.archive.org/web/{cdx_ts}if_/{olalacms_url}")
        )

    strategies.append(("direct_conab", olalacms_url))

    for strategy, url in strategies:
        logger.debug("    Trying %s: %s", strategy, url[-70:])

        if "wayback" in strategy:
            data = _wayback_get(url)
        else:
            data = _direct_get(url, session)

        if not data:
            continue

        fmt = _detect_format(data)
        if fmt:
            content_type, ext = fmt
            logger.info(
                "    OK %s  (%.1f KB)  fmt=%s  via %s",
                olalacms_url.split("/")[-1][:40],
                len(data) / 1024,
                ext,
                strategy,
            )
            return data, url, ext

        logger.debug("    Non-document response via %s: %s...", strategy, data[:80])

    return None, None, None


# ---------------------------------------------------------------------------
# Manifest helpers (shared logic with fetch_conab_historical.py)
# ---------------------------------------------------------------------------


def _manifest_existing_keys(manifest_path: Path) -> set[tuple[str, int]]:
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    return {
        (str(e["crop_year"]), int(e["survey_number"]))
        for e in (data.get("surveys") or [])
    }


def _append_to_manifest(new_entries: list[dict], manifest_path: Path) -> None:
    if not new_entries:
        return

    by_year: dict[str, list[dict]] = {}
    for e in new_entries:
        by_year.setdefault(e["crop_year"], []).append(e)

    lines: list[str] = [
        "\n",
        "  # -- Pre-2013 bulletins (OlalaCMS era, Wayback Machine) --\n",
    ]
    for crop_year in sorted(by_year.keys(), reverse=True):
        safra_year   = int(crop_year[:4]) + 1
        year_entries = sorted(by_year[crop_year], key=lambda x: x["survey_number"])
        lines.append(
            f"\n  # -- Safra {safra_year} (crop year {crop_year}) --\n"
        )
        for e in year_entries:
            lines.append(f'  - crop_year: "{e["crop_year"]}"\n')
            lines.append(f'    survey_number: {e["survey_number"]}  # pub_month\n')
            lines.append(f'    pdf_url: "{e["pdf_url"]}"\n')

    with open(manifest_path, "a", encoding="utf-8") as fh:
        fh.writelines(lines)

    logger.info("Appended %d pre-2013 entries to %s", len(new_entries), manifest_path.name)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description=(
            "Fetch pre-2013 CONAB coffee bulletin PDFs from Wayback Machine -> S3. "
            "Reads conab_olalacms_gids.json (run probe_conab_olalacms.py first)."
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
        help="Print candidate URLs without downloading.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=2.0,
        metavar="SECS",
        help="Delay between download requests in seconds (default: 2.0).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process at most N entries — use 1 for a smoke test.",
    )
    parser.add_argument(
        "--gid-file",
        type=Path,
        default=_GID_JSON_PATH,
        metavar="PATH",
        help=(
            "JSON file in conab_olalacms_gids.json format. "
            f"Default: {_GID_JSON_PATH}"
        ),
    )
    args = parser.parse_args()

    # -----------------------------------------------------------------------
    # Load manifest
    # -----------------------------------------------------------------------
    gid_file: Path = args.gid_file
    if not gid_file.exists():
        parser.error(
            f"Not found: {gid_file}\n"
            "  Run: .venv\\Scripts\\python.exe scratch\\conab\\probe_conab_olalacms.py"
        )

    raw_entries: list[dict] = json.loads(gid_file.read_text(encoding="utf-8"))
    logger.info("Loaded %d entries from %s", len(raw_entries), gid_file.name)

    # Sort oldest first so history builds in order; limit if requested
    sorted_entries = sorted(raw_entries, key=lambda e: (e["safra_year"], e["pub_month"]))
    if args.limit:
        sorted_entries = sorted_entries[: args.limit]

    # -----------------------------------------------------------------------
    # Dry run
    # -----------------------------------------------------------------------
    if args.dry_run:
        print(f"Dry run: {len(sorted_entries)} entries")
        for e in sorted_entries:
            crop_year     = _safra_to_crop_year(e["safra_year"])
            survey_number = e["levantamento"]
            s3_key        = raw_conab_key(crop_year, survey_number)  # .pdf default
            print(
                f"  safra={e['safra_year']}  month={e['pub_month']:02d}"
                f"  crop={crop_year}  -> {s3_key}"
            )
            print(f"    url: {e['olalacms_url']}")
            print(f"    ts:  {e.get('wayback_snap_ts')}")
        return

    # -----------------------------------------------------------------------
    # Download & upload
    # -----------------------------------------------------------------------
    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    existing_in_manifest = _manifest_existing_keys(_MANIFEST_PATH)

    uploaded = skipped = errors = 0
    missing: list[str] = []
    new_manifest_entries: list[dict] = []

    with curl_requests.Session() as session:
        for entry in sorted_entries:
            safra_year    = int(entry["safra_year"])
            pub_month     = int(entry["pub_month"])
            crop_year     = _safra_to_crop_year(safra_year)
            survey_number = pub_month
            olalacms_url  = entry["olalacms_url"]
            snap_ts       = entry.get("wayback_snap_ts")
            label         = f"safra {safra_year} month {pub_month:02d} ({crop_year})"

            try:
                if args.skip_existing_s3:
                    already_exists = False
                    for check_ext in (".pdf", ".doc", ".docx"):
                        check_key = raw_conab_key(crop_year, survey_number, ext=check_ext)
                        if s3_object_exists(bucket, check_key, region):
                            logger.info("Skipping - already in S3: %s", check_key)
                            skipped += 1
                            already_exists = True
                            break
                    if already_exists:
                        time.sleep(args.sleep_seconds)
                        continue

                logger.info("Downloading %s ...", label)

                file_bytes, source_url, file_ext = _download_bulletin(
                    olalacms_url, snap_ts, session
                )

                if file_bytes is None:
                    logger.warning("All strategies failed for %s", label)
                    missing.append(label)
                    errors += 1
                    time.sleep(args.sleep_seconds)
                    continue

                s3_key = raw_conab_key(crop_year, survey_number, ext=file_ext)
                fmt = _detect_format(file_bytes)
                content_type = fmt[0] if fmt else "application/octet-stream"

                check_min_file_size(file_bytes, "conab", context=source_url)
                upload_bytes_to_s3(file_bytes, bucket, s3_key, region)
                write_raw_s3_metadata(
                    bucket, s3_key, file_bytes, source_url, content_type, region
                )

                logger.info(
                    "Uploaded %s  (%.1f KB  %s)  ->  s3://%s/%s",
                    label,
                    len(file_bytes) / 1024,
                    file_ext,
                    bucket,
                    s3_key,
                )
                uploaded += 1

                if (crop_year, survey_number) not in existing_in_manifest:
                    new_manifest_entries.append(
                        {
                            "crop_year":     crop_year,
                            "survey_number": survey_number,
                            "pdf_url":       source_url,
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
    # Summary
    # -----------------------------------------------------------------------
    logger.info("Done.  uploaded=%d  skipped=%d  errors=%d", uploaded, skipped, errors)

    if missing:
        logger.warning(
            "Bulletins not retrieved (%d) - Wayback has no capture:",
            len(missing),
        )
        for item in sorted(missing):
            logger.warning("  MISSING: %s", item)
    else:
        logger.info("All bulletins retrieved successfully.")


if __name__ == "__main__":
    main()
