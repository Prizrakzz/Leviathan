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
import logging
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

from leviathan.common.config import get_required_env, load_env
from leviathan.common.dates import current_harvest_season, harvest_seasons_through
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
    _assert_data_rows(html_bytes, harvest_year)
    return html_bytes


# The empty-shell floor. Measured 2026-08-16 (D-SG M-8 probe): a REAL season page
# (2020/2021) carries 28 <tr> rows at ~25.7 KB; a post-2020 season returns a shell
# with a <table> tag, exactly 4 header rows and no data at ~21.9 KB -- which passes
# the size and <table> checks above. 8 sits between the two shapes with margin.
_MIN_TABLE_ROWS = 8

# The last season idTabela=2495 actually serves (D-SG M-8 probe, 2026-08-16: every later
# season returns an empty table shell). A manifest reaching this ceiling is COMPLETE.
_ENDPOINT_CEILING = "2020/2021"


def _assert_data_rows(html_bytes: bytes, harvest_year: str) -> None:
    """Refuse an empty table SHELL: a page whose <table> carries headers but no data.

    Uploading a shell as raw would ripple a zero-row season through bronze/silver
    silently -- the exact no-op class D-SG G2-1 exists to end.
    """
    rows = html_bytes.lower().count(b"<tr")
    if rows < _MIN_TABLE_ROWS:
        raise RuntimeError(
            f"Empty table shell for harvest_year={harvest_year}: {rows} <tr> row(s) "
            f"(floor {_MIN_TABLE_ROWS}). The endpoint serves no data for this season "
            "-- unicadata's idTabela=2495 data ceiling is 2020/2021; use unica_biweekly."
        )




# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
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
        "--through-current-season",
        action="store_true",
        help=(
            "Extend the manifest's harvest_years forward to the CURRENT open season derived "
            "from --asof, so the annual leg never freezes on a static list again. "
            "D-SG G2-1(a-i): configs/sources/unica_sources.yaml ended at 2020/2021, so five "
            "closed seasons and the open one were never fetched while the job exited 0."
        ),
    )
    parser.add_argument(
        "--asof",
        default=None,
        help="Scheduled-time ISO used to derive the current harvest season. Default: today (UTC).",
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

    season_now = current_harvest_season(args.asof)
    if args.harvest_years:
        harvest_years = args.harvest_years
    elif args.through_current_season:
        harvest_years = harvest_seasons_through(all_harvest_years[0], args.asof)
        added = [y for y in harvest_years if y not in all_harvest_years]
        logger.info(
            "through-current-season: manifest ends at %s, current season is %s, "
            "extending by %d season(s): %s",
            all_harvest_years[-1], season_now, len(added), added,
        )
    else:
        harvest_years = all_harvest_years
        # THE ENDPOINT CEILING EXCEPTION (D-SG M-8, measured 2026-08-16): idTabela=2495
        # serves NO data past _ENDPOINT_CEILING -- post-2020 seasons return empty 4-row
        # table shells (refused by _assert_data_rows). A manifest that reaches the ceiling
        # is therefore COMPLETE, not stale, and the bare path is the correct scheduled
        # config; the biweekly leg owns current seasons. The refusal below survives for
        # the day the manifest falls short of the ceiling itself.
        if season_now not in harvest_years and all_harvest_years[-1] != _ENDPOINT_CEILING:
            raise SystemExit(
                f"MANIFEST STALE: current harvest season {season_now} is absent from "
                f"{_MANIFEST_PATH.name} (which ends at {all_harvest_years[-1]}, below the "
                f"documented endpoint ceiling {_ENDPOINT_CEILING}). This fetch would "
                "re-download only closed seasons and exit 0 -- the D-SG G2-1(a-i) "
                "silent no-op. Pass --through-current-season, or extend harvest_years."
            )
        if season_now not in harvest_years:
            logger.info(
                "manifest ends at the documented endpoint ceiling %s (current season %s is "
                "served by unica_biweekly, not this endpoint) -- proceeding on the closed set",
                _ENDPOINT_CEILING, season_now,
            )
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

        except Exception as exc:  # noqa: BLE001 — any download, validation, or S3 error is logged; loop continues
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
    if uploaded == 0:
        raise SystemExit(
            f"ZERO-ADVANCE: {len(harvest_years)} harvest year(s) targeted and NOTHING was "
            "uploaded. This fetcher re-writes every target key on every run, so uploaded=0 "
            "means the target list was empty or every request was skipped -- never a healthy run."
        )


if __name__ == "__main__":
    main()

