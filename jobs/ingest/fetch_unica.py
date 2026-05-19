"""Fetch UNICA (Brazilian CS) production-and-milling HTML pages to raw S3.

Discovery
---------
Although the UNICADATA portal (unicadata.com.br) is JavaScript-rendered for
interactive use, the production-and-milling table for a given harvest year is
rendered *server-side* by PHP when the full form-submission URL is supplied
directly.  The required parameters are:

    https://unicadata.com.br/historico-de-producao-e-moagem.php
        ?idMn=32          ← Production and Milling section
        &tipoHistorico=4  ← Per-Harvest view
        &idioma=2         ← English language
        &idTabela=2495    ← constant page-type identifier (verified May 2026)
        &safra=2020/2021  ← harvest year label (YYYY/YYYY format)
        &acao=visualizar  ← "show results" action

This means a standard ``urllib`` GET is sufficient — no Playwright or headless
browser is required.

Idempotency
-----------
Pass ``--skip-existing-s3`` to skip harvest years already uploaded.

"""
from __future__ import annotations

import argparse
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import unica_raw_key
from leviathan.storage.raw_metadata import write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent / "configs" / "sources" / "unica_sources.yaml"
)

# Base URL and the constant page-type identifier for the Per-Harvest view.
_BASE_URL = "https://unicadata.com.br/historico-de-producao-e-moagem.php"
_IDTABELA = "2495"

# Minimum plausible HTML size; a real table page is typically >20 KB.
_MIN_HTML_BYTES = 5_000

_REQUEST_TIMEOUT_S = 30


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------

def _build_url(harvest_year: str) -> str:
    params = urllib.parse.urlencode(
        {
            "idMn": "32",
            "tipoHistorico": "4",
            "idioma": "2",
            "idTabela": _IDTABELA,
            "safra": harvest_year,
            "acao": "visualizar",
        }
    )
    return f"{_BASE_URL}?{params}"


def _fetch_harvest_year(harvest_year: str) -> bytes:
    """Return the raw HTML bytes for *harvest_year* from UNICADATA.

    Raises:
        RuntimeError: If the response is too small or contains no ``<table>``.
        urllib.error.URLError: On network errors.
    """
    url = _build_url(harvest_year)
    logger.debug("GET %s", url)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_S) as resp:
        html_bytes: bytes = resp.read()

    if len(html_bytes) < _MIN_HTML_BYTES:
        raise RuntimeError(
            f"Response too small ({len(html_bytes):,} bytes) for harvest_year={harvest_year}."
        )
    if b"<table" not in html_bytes.lower():
        raise RuntimeError(
            f"No <table> tag in response for harvest_year={harvest_year}. "
            "The year may not be available in the current data set."
        )
    return html_bytes




# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download UNICA production-and-milling HTML pages to raw S3. "
            "Uses plain HTTP GET — no headless browser required. "
            "One HTML file per harvest year."
        )
    )
    parser.add_argument(
        "--harvest-years",
        nargs="+",
        metavar="YYYY/YYYY",
        default=None,
        help=(
            "One or more harvest years to fetch, e.g. --harvest-years 2020/2021. "
            "Defaults to all years listed in configs/sources/unica_sources.yaml."
        ),
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip harvest years whose S3 key already exists (safe for re-runs).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print harvest years that would be fetched without downloading anything.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=2.0,
        help="Polite delay between requests in seconds (default: 2.0).",
    )
    args = parser.parse_args()

    # -----------------------------------------------------------------------
    # Load manifest
    # -----------------------------------------------------------------------
    manifest_data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8"))
    all_harvest_years: list[str] = [str(y) for y in manifest_data["harvest_years"]]

    harvest_years = args.harvest_years if args.harvest_years else all_harvest_years
    logger.info(
        "Loaded %d harvest years from manifest %s",
        len(all_harvest_years),
        _MANIFEST_PATH.name,
    )

    # -----------------------------------------------------------------------
    # Dry run
    # -----------------------------------------------------------------------
    if args.dry_run:
        print(f"Manifest: {_MANIFEST_PATH.name}  ({len(all_harvest_years)} total harvest years)")
        print(f"Would fetch {len(harvest_years)} harvest year(s):")
        for hy in harvest_years:
            s3_key = unica_raw_key(hy)
            print(f"  {hy}  →  s3://{{bucket}}/{s3_key}")
        return

    # -----------------------------------------------------------------------
    # Download & upload
    # -----------------------------------------------------------------------
    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    uploaded = skipped = errors = 0

    for idx, harvest_year in enumerate(harvest_years):
        s3_key = unica_raw_key(harvest_year)

        try:
            if args.skip_existing_s3 and s3_object_exists(bucket, s3_key, region):
                logger.info("Skipping — already in S3: %s", s3_key)
                skipped += 1
                continue

            logger.info("Fetching harvest_year=%s …", harvest_year)

            html_bytes = _fetch_harvest_year(harvest_year)

            upload_bytes_to_s3(html_bytes, bucket, s3_key, region)
            write_raw_s3_metadata(
                bucket, s3_key, html_bytes, _build_url(harvest_year), "text/html", region
            )

            logger.info(
                "Uploaded harvest_year=%s  (%.1f KB) → s3://%s/%s",
                harvest_year,
                len(html_bytes) / 1_024,
                bucket,
                s3_key,
            )
            uploaded += 1

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed harvest_year=%s: %s", harvest_year, exc)
            errors += 1

        if idx < len(harvest_years) - 1:
            time.sleep(args.sleep_seconds)

    logger.info(
        "UNICA fetch complete. uploaded=%d  skipped=%d  errors=%d",
        uploaded,
        skipped,
        errors,
    )
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

