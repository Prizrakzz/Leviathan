"""Fetch the NOAA CPC Oceanic Nino Index (ONI) file and write raw + bronze to S3 (SILVER-F057).

Source
------
NOAA Climate Prediction Center -- ONI ascii record (ERSSTv5, 30-year base periods)
    https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt

No authentication required.  Single ASCII text file (~30 KB) updated monthly in-place; the
full history from the DJF 1950 season is included in every release.  Because this is a single
tiny file with no WAF, no pagination and no URL discovery step, the ingest and bronze
transform are combined in one script -- the same pattern as ``fetch_noaa_iod.py``.

The source decision (why the CPC ascii file and not the website table / the raw Nino-3.4
monthly file) is recorded in ``docs/adr/ADR-002-noaa-oni-source.md``.

S3 layout
---------
    Raw:    raw/weather/source=noaa_oni/oni.ascii.txt         (overwrite)
    Bronze: bronze/weather/source=noaa_oni/part-000.parquet   (overwrite)

Both objects are overwritten on each run.

THE VINTAGE CAPTURE (data repairs 0929, lane ENSO)
--------------------------------------------------
NOAA rewrites its ENSO files in place and restates history (883 of 917 legacy seasons changed between
the 2026-07-26 and 2026-09-07 archive captures), and since 2026-02-01 its OFFICIAL index is a second
file, the Relative ONI (NWS PNS 26-05). The overwrite above keeps only today's legacy file. So every
run ALSO banks both files, never overwriting, under

    raw/weather/source=noaa_cpc_enso_captures/index_id=<id>/clock=<clock>/evidence=<UTC stamp>/sha256=<hex>.txt

where the key itself carries the publisher clock (NOAA's ``Last-Modified``) and the digest of the
decoded text, so an unchanged file re-captured is a no-op and a changed one is a new object. A body
without ``Last-Modified`` is banked under ``clock=undated`` and is never dated from our fetch time. A
capture failure is LOGGED (``ENSO_CAPTURE_FAILED``) and never fails this run: the served legacy leg
must not depend on the unserved vintages table. ``jobs/batch/noaa_oni_task.py --table
silver_noaa_enso_vintages`` builds the table from what is banked.

Two owner-run modes seed the history the live file no longer shows (neither is on a schedule):
    --archive-backfill : every web-archive capture of both files from the CDX index, each replay's
                         SERVED instant verified (a requested timestamp is a request, not a guarantee),
                         dated by NOAA's Last-Modified as the archive recorded it, else by the capture
                         instant (an upper bound).
    --seed-body/--seed-headers/--seed-url : bank ONE saved origin fetch whose response headers were saved
                         with it (NOAA's Last-Modified dates it; a saved Content-Length must equal the body).

Usage
-----
    python jobs/ingest/fetch_noaa_oni.py
    python jobs/ingest/fetch_noaa_oni.py --dry-run
    python jobs/ingest/fetch_noaa_oni.py --skip-existing-raw
    python jobs/ingest/fetch_noaa_oni.py --force-bronze
    python jobs/ingest/fetch_noaa_oni.py --archive-backfill --archive-from 2026 [--dry-run]
    python jobs/ingest/fetch_noaa_oni.py --seed-body RONI.ascii.txt --seed-headers roni_hdr.txt \
        --seed-url https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt [--dry-run]
"""
from __future__ import annotations

import argparse
import io
import logging
import re
import sys
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Optional

import requests

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_oni_key, raw_oni_key
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3
from leviathan.transforms.raw_to_bronze.noaa_oni import (
    ENSO_CAPTURE_PREFIX,
    ENSO_INDEX_FILES,
    ENSO_INDEX_FILES_BY_ID,
    EnsoCapture,
    capture_from_archive,
    capture_from_origin,
    decode_capture_body,
    extract_oni_bronze,
    parse_enso_index_text,
)

logger = get_logger("fetch_noaa_oni")

_ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
_TIMEOUT = 30

# Sanity check: the file's first line is the header " SEAS  YR   TOTAL   ANOM".
_EXPECTED_HEADER_TOKEN = "SEAS"

# Web-archive politeness (the pink-sheet backfill's figures: archive.org is a library, not a CDN).
_CDX_URL = "https://web.archive.org/cdx/search/cdx"
_REPLAY_FMT = "https://web.archive.org/web/{ts}id_/{url}"
_ARCHIVE_SLEEP_S = 2.5
_ARCHIVE_TIMEOUT_S = 90
_USER_AGENT = "Leviathan-ENSO-Vintages/1.0 (research; non-commercial)"
_SERVED_TS_RE = re.compile(r"/web/(\d{14})(?:id_)?/")


def _write_parquet(data: bytes, bucket: str, key: str, aws_region: str) -> None:
    import boto3
    from leviathan.storage.s3 import _BOTO_RETRY_CONFIG
    s3 = boto3.client("s3", region_name=aws_region, config=_BOTO_RETRY_CONFIG)
    s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType="application/octet-stream")


# ---------------------------------------------------------------------------
# The vintage capture (pure decisions here; the S3 writes go through `bank_capture`).
# ---------------------------------------------------------------------------

def validate_capture(cap: EnsoCapture) -> None:
    """Refuse (``ValueError``) a body that is not its declared file: a vintage is banked only if it
    parses against its own file's header, so an error page served with a 200 never becomes one."""
    index_file = ENSO_INDEX_FILES_BY_ID.get(cap.index_id)
    if index_file is None:
        raise ValueError(f"{cap.source_url!r} is not a declared ENSO index file")
    parse_enso_index_text(decode_capture_body(cap.body), index_file.header)


def _capture_meta(cap: EnsoCapture, mode: str, headers: Optional[dict] = None, **extra) -> dict:
    keep = ("Last-Modified", "Content-Length", "Content-Encoding", "Content-Type", "ETag", "Date",
            "Memento-Datetime", "X-Archive-Orig-Last-Modified")
    hdrs = {k: v for k, v in (headers or {}).items() if k in keep}
    return {"capture_mode": mode, "index_id": cap.index_id, "clock": cap.clock,
            "evidence_utc": None if cap.evidence_utc is None
            else cap.evidence_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "content_sha256": cap.sha256, "http_headers": hdrs, **extra}


def bank_capture(cap: EnsoCapture, *, exists: Callable[[str], bool], put: Callable[[str, bytes, dict], None],
                 meta: dict, dry_run: bool = False) -> str:
    """Bank one capture under its own key, NEVER overwriting; returns 'banked' | 'held' | 'dry-run'.

    ``exists``/``put`` are the storage seam (S3 in production, a dict or a directory in tests and
    in the offline proof)."""
    validate_capture(cap)
    key = cap.key
    if dry_run:
        logger.info("dry-run capture (not written): %s", key)
        return "dry-run"
    if exists(key):
        logger.info("capture already held: %s", key)
        return "held"
    put(key, cap.body, meta)
    logger.info("capture banked: %s (%d bytes, clock=%s)", key, len(cap.body), cap.clock)
    return "banked"


def _s3_storage(bucket: str, aws_region: str):
    from leviathan.storage.raw_metadata import write_raw_s3_metadata

    def exists(key: str) -> bool:
        return s3_object_exists(bucket, key, aws_region)

    def put(key: str, body: bytes, meta: dict) -> None:
        upload_bytes_to_s3(body, bucket, key, aws_region)
        write_raw_s3_metadata(bucket, key, body, meta.get("source_url", ""), "text/plain",
                              aws_region, extra=meta)
    return exists, put


def capture_live(get: Callable[[str], "requests.Response"], *, exists, put, dry_run: bool = False,
                 reuse: Optional[dict] = None) -> dict:
    """Capture BOTH declared ENSO files from NOAA. Never raises: each failure is logged and counted.

    ``reuse`` maps a URL to a response already fetched this run (the legacy GET above), so the legacy
    file is not fetched twice."""
    outcome: dict = {}
    for index_file in ENSO_INDEX_FILES:
        url = index_file.url
        try:
            resp = (reuse or {}).get(url) or get(url)
            resp.raise_for_status()
            headers = dict(resp.headers)
            cap = capture_from_origin(url, headers, resp.content)
            meta = _capture_meta(cap, "live", headers, source_url=url)
            outcome[url] = bank_capture(cap, exists=exists, put=put, meta=meta, dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001 -- a capture must never fail the served legacy leg
            logger.error("ENSO_CAPTURE_FAILED %s: %s: %s", url, type(exc).__name__, exc)
            outcome[url] = f"failed: {type(exc).__name__}: {exc}"
    return outcome


# ---------------------------------------------------------------------------
# Owner-run: the web-archive backfill and the seed of a saved origin fetch.
# ---------------------------------------------------------------------------

def served_capture_ts(final_url: str, memento_datetime: Optional[str]) -> Optional[str]:
    """The capture the archive ACTUALLY served (14 digits), from the replay URL, cross-checked
    against ``Memento-Datetime``; ``ValueError`` when the two disagree, ``None`` when neither says."""
    served = None
    m = _SERVED_TS_RE.search(final_url or "")
    if m:
        served = m.group(1)
    if memento_datetime:
        try:
            stamp = parsedate_to_datetime(memento_datetime).astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
        except (TypeError, ValueError):
            stamp = None
        if stamp and served and stamp != served:
            raise ValueError(f"archive disagrees with itself: URL {served}, Memento-Datetime {stamp}")
        served = served or stamp
    return served


def cdx_capture_timestamps(get_json: Callable[[str, dict], list], url: str, from_year: int) -> list[str]:
    """Every 200 capture of ``url`` from the CDX index, adjacent identical digests collapsed (the
    first of each run is the earliest evidence of that content)."""
    rows = get_json(_CDX_URL, {"url": url, "output": "json", "matchType": "exact",
                               "filter": "statuscode:200", "collapse": "digest", "from": str(from_year)})
    if not rows:
        return []
    head, body = rows[0], rows[1:]
    i_ts = head.index("timestamp")
    return [r[i_ts] for r in body]


def archive_backfill(get: Callable[[str], "requests.Response"], get_json: Callable[[str, dict], list], *,
                     from_year: int, exists, put, dry_run: bool = False,
                     sleep: Callable[[float], None] = time.sleep) -> dict:
    """Bank every verified archive capture of both ENSO files. Refusals are counted, never landed."""
    tally = {"banked": 0, "held": 0, "dry-run": 0, "refused": []}
    for index_file in ENSO_INDEX_FILES:
        url = index_file.url
        for ts in cdx_capture_timestamps(get_json, url, from_year):
            replay = _REPLAY_FMT.format(ts=ts, url=url)
            try:
                resp = get(replay)
                resp.raise_for_status()
                served = served_capture_ts(getattr(resp, "url", "") or "", resp.headers.get("Memento-Datetime"))
                if served != ts:
                    raise ValueError(f"requested capture {ts} but the archive served {served}")
                headers = dict(resp.headers)
                cap = capture_from_archive(url, served, headers, resp.content)
                meta = _capture_meta(cap, "archive", headers, source_url=url, replay_url=replay,
                                     served_capture=served)
                tally[bank_capture(cap, exists=exists, put=put, meta=meta, dry_run=dry_run)] += 1
            except Exception as exc:  # noqa: BLE001 -- one bad replay never stops the census
                logger.error("ENSO_ARCHIVE_REFUSED %s: %s: %s", replay, type(exc).__name__, exc)
                tally["refused"].append(f"{replay}: {type(exc).__name__}: {exc}")
            sleep(_ARCHIVE_SLEEP_S)
    return tally


def parse_saved_headers(text: str) -> dict:
    """``{name: value}`` from a saved HTTP response head (status line and blank lines skipped)."""
    out: dict = {}
    for line in text.splitlines():
        if ":" not in line or line.startswith("HTTP/"):
            continue
        name, value = line.split(":", 1)
        out[name.strip()] = value.strip()
    return out


def seed_from_saved(body: bytes, headers: dict, url: str, *, exists, put, dry_run: bool = False) -> str:
    """Bank one SAVED origin fetch. Its date is NOAA's own Last-Modified from the saved headers; a seed
    with no Last-Modified would carry no publisher clock and is refused."""
    if index_url_or_none(url) is None:
        raise ValueError(f"{url!r} is not a declared ENSO index file")
    cap = capture_from_origin(url, headers, body)       # also checks a saved Content-Length
    if cap.evidence_utc is None:
        raise ValueError("the saved headers carry no Last-Modified: a seed needs the publisher's clock")
    fetched = headers.get("Date")
    meta = _capture_meta(cap, "seed_saved_origin_fetch", headers, source_url=url, saved_fetch_date=fetched)
    return bank_capture(cap, exists=exists, put=put, meta=meta, dry_run=dry_run)


def index_url_or_none(url: str) -> Optional[str]:
    return url if any(f.url == url for f in ENSO_INDEX_FILES) else None


def _http_get(url: str) -> "requests.Response":
    return requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=_ARCHIVE_TIMEOUT_S)


def _http_get_json(url: str, params: dict) -> list:
    resp = requests.get(url, params=params, headers={"User-Agent": _USER_AGENT}, timeout=_ARCHIVE_TIMEOUT_S)
    resp.raise_for_status()
    return resp.json() if resp.text.strip() else []


def _legacy_raw_and_bronze(args, bucket: str, aws_region: str, r_key: str, b_key: str):
    """The served legacy flow, unchanged: raw overwrite + bronze overwrite. Returns the legacy
    response when it fetched one (the vintage capture reuses it), else None."""
    # ------------------------------------------------------------------
    # Fetch raw
    # ------------------------------------------------------------------
    resp = None
    raw_skipped = False
    if args.skip_existing_raw and s3_object_exists(bucket, r_key, aws_region):
        logger.info("Raw already exists -- skipping HTTP fetch: %s", r_key)
        raw_skipped = True
    else:
        logger.info("Fetching %s ...", _ONI_URL)
        resp = requests.get(_ONI_URL, timeout=_TIMEOUT)
        resp.raise_for_status()
        oni_bytes = resp.content

        header = oni_bytes[:40].decode("utf-8", errors="replace")
        if _EXPECTED_HEADER_TOKEN not in header:
            logger.error(
                "Response from %s does not look like the ONI ascii file "
                "(expected header token %r). Got: %r",
                _ONI_URL, _EXPECTED_HEADER_TOKEN, oni_bytes[:60],
            )
            sys.exit(1)

        logger.info("Downloaded %d bytes", len(oni_bytes))
        upload_bytes_to_s3(oni_bytes, bucket, r_key, aws_region)
        logger.info("Raw written -> s3://%s/%s", bucket, r_key)

    # ------------------------------------------------------------------
    # Bronze transform
    # ------------------------------------------------------------------
    if raw_skipped and not args.force_bronze:
        logger.info("Raw was skipped and --force-bronze not set -- skipping bronze write")
        return resp

    if raw_skipped:
        import boto3
        from leviathan.storage.s3 import _BOTO_RETRY_CONFIG, s3_download_with_retry
        s3_client = boto3.client("s3", region_name=aws_region, config=_BOTO_RETRY_CONFIG)
        oni_bytes = s3_download_with_retry(bucket, r_key, s3_client)
        logger.info("Re-read raw from S3 for bronze parse (%d bytes)", len(oni_bytes))

    df = extract_oni_bronze(oni_bytes)

    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    _write_parquet(buf.getvalue(), bucket, b_key, aws_region)
    logger.info(
        "Bronze written -> s3://%s/%s  rows=%d  years=%d-%d",
        bucket, b_key, len(df), int(df["year"].min()), int(df["year"].max()),
    )
    return resp


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(
        description="Fetch NOAA CPC ONI ascii file -> raw S3 + bronze Parquet"
    )
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--skip-existing-raw", action="store_true",
                        help="Skip the HTTP fetch if the raw S3 key already exists")
    parser.add_argument("--force-bronze", action="store_true",
                        help="Re-write bronze even if raw was skipped")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the S3 keys and row count without writing anything")
    parser.add_argument("--archive-backfill", action="store_true",
                        help="OWNER-RUN: bank every verified web-archive capture of both ENSO files")
    parser.add_argument("--archive-from", type=int, default=2026,
                        help="first year of the CDX census for --archive-backfill (default 2026)")
    parser.add_argument("--seed-body", default=None, help="OWNER-RUN: a saved origin body to bank")
    parser.add_argument("--seed-headers", default=None, help="the saved response head of --seed-body")
    parser.add_argument("--seed-url", default=None, help="the URL --seed-body was fetched from")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    exists, put = _s3_storage(bucket, aws_region)

    if args.seed_body or args.seed_headers or args.seed_url:
        if not (args.seed_body and args.seed_headers and args.seed_url):
            parser.error("--seed-body, --seed-headers and --seed-url go together")
        body = Path(args.seed_body).read_bytes()
        headers = parse_saved_headers(Path(args.seed_headers).read_text(encoding="utf-8"))
        result = seed_from_saved(body, headers, args.seed_url, exists=exists, put=put, dry_run=args.dry_run)
        print(f"seed {args.seed_url}: {result}")
        return

    if args.archive_backfill:
        tally = archive_backfill(_http_get, _http_get_json, from_year=args.archive_from,
                                 exists=exists, put=put, dry_run=args.dry_run)
        print(f"archive backfill: banked={tally['banked']} held={tally['held']} "
              f"dry-run={tally['dry-run']} refused={len(tally['refused'])}")
        for line in tally["refused"]:
            print(f"  refused: {line}")
        return

    r_key = raw_oni_key()
    b_key = bronze_oni_key()

    logger.info("ONI ingest  bucket=%s  raw=%s", bucket, r_key)

    if args.dry_run:
        print(f"Source URL : {_ONI_URL}")
        print(f"Raw key    : {r_key}")
        print(f"Bronze key : {b_key}")
        print(f"Captures   : {ENSO_CAPTURE_PREFIX} <- {', '.join(f.url for f in ENSO_INDEX_FILES)}")
        print("(dry-run -- no writes)")
        return

    legacy_resp = _legacy_raw_and_bronze(args, bucket, aws_region, r_key, b_key)
    outcome = capture_live(lambda u: requests.get(u, timeout=_TIMEOUT), exists=exists, put=put,
                           reuse={_ONI_URL: legacy_resp} if legacy_resp is not None else None)
    logger.info("ENSO capture outcome: %s", outcome)


if __name__ == "__main__":
    main()
