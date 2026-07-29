#!/usr/bin/env python
"""PRICE_AND_PLAYBOOKS W1a / D1 -- the CEPEA history ONE-SHOT (raw landing only).

WHY AN ARCHIVE ROUTE AT ALL
---------------------------
CEPEA's own series pages are ``.aspx`` and they are Cloudflare-403 to plain ``requests``, to a FULL
Chrome header set (``sec-ch-ua``, ``Sec-Fetch-*``, ``Upgrade-Insecure-Requests``) and via WebFetch.
**Only the ``.php`` widget is open**, and it returns the last value only. So the series cannot be
read from the origin at all -- but web.archive.org holds snapshots of the ``.aspx`` downloads, and
ONE snapshot per indicator carries the ENTIRE series to its capture date::

    id 23 arabica  cafe.aspx?id=23  @20250608143948   136,726 B   1996-09-02 .. 2025-06-08 (5,193+ rows)
    id 77 corn     milho.aspx?id=77 @20250614163045               2004-08-02 .. 2025-06-14 (5,200 rows)

This job is a ONE-SHOT: two GETs, two objects, done. It is not a walk and it is not scheduled.

THE RESIDUAL GAP IS ACCEPTED, NOT ENGINEERED AROUND
---------------------------------------------------
Between the snapshot dates and the first daily run there is a **~13-month hole** (2025-06 -> today).
That is documented and accepted in the plan; the daily widget accumulates forward from first run.
Nothing here fabricates a value to fill it, and nothing should.

THE PARSE GOTCHA LIVES IN THE TRANSFORM, NOT HERE
--------------------------------------------------
The archived workbooks are LibreOffice-generated and MALFORMED: ``pandas.read_excel`` and a plain
``xlrd`` open both raise ``CompDocError: Workbook corruption: seen[2] == 4``. They open only with
``xlrd.open_workbook(file_contents=..., ignore_workbook_corruption=True)``, which is what
``transforms.raw_to_bronze.cepea`` does. This job lands bytes and does not parse them.

S3 LAYOUT
---------
    raw/production/source=cepea/indicator={23|77}/history/wayback_{TS14}.xls
    raw_meta/<that key>_meta.json

Under ``history/`` so the one-shot and the daily captures never collide in a LIST, and keyed on the
snapshot timestamp so a re-run is idempotent rather than duplicative.

Usage
-----
    python jobs/ingest/fetch_cepea_wayback_history.py --dry-run
    python jobs/ingest/fetch_cepea_wayback_history.py
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests  # noqa: E402
from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.storage.paths import raw_cepea_wayback_key  # noqa: E402
from leviathan.transforms.raw_to_bronze.cepea import CEPEA_INDICATORS  # noqa: E402

logger = get_logger("fetch_cepea_wayback_history")

# The `id_` suffix on the timestamp asks Wayback for the ORIGINAL bytes without its rewriting
# banner -- mandatory when the artifact is a binary workbook.
_WAYBACK_FMT = "https://web.archive.org/web/{ts}id_/{target}"

# The two curated snapshots. Each carries the whole series to its capture date; the timestamp is
# part of the raw key, so re-running lands the same object rather than a second copy.
CEPEA_SNAPSHOTS: dict[int, dict[str, str]] = {
    23: {"ts": "20250608143948",
         "target": "https://www.cepea.esalq.usp.br/br/indicador/series/cafe.aspx?id=23",
         "first_row": "1996-09-02"},
    77: {"ts": "20250614163045",
         "target": "https://www.cepea.esalq.usp.br/br/indicador/series/milho.aspx?id=77",
         "first_row": "2004-08-02"},
}

_SOURCE_LABEL = "cepea_wayback"
_CONTENT_TYPE = "application/vnd.ms-excel"
_TIMEOUT = 120
_SLEEP_SECONDS = 2.5
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = 10
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

# Legacy OLE compound-document magic. Wayback serves an HTML "not archived" page with HTTP 200 when
# a capture is missing, so the magic check is the real presence test.
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def snapshot_url(indicator_id: int) -> str:
    snap = CEPEA_SNAPSHOTS[int(indicator_id)]
    return _WAYBACK_FMT.format(ts=snap["ts"], target=snap["target"])


def looks_like_a_series_workbook(payload: bytes) -> Optional[str]:
    if not payload.startswith(_OLE_MAGIC):
        return (f"the response is not a legacy OLE workbook (first bytes {payload[:16]!r}) -- "
                f"web.archive.org served its HTML placeholder, so this capture is not there")
    return None


def fetch_snapshot(indicator_id: int, *, timeout: int = _TIMEOUT) -> bytes:
    url = snapshot_url(indicator_id)
    backoff = _BACKOFF_SECONDS
    last_error: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS:
                logger.warning("wayback id=%s returned HTTP %d (attempt %d/%d) -- retrying in %ds",
                               indicator_id, resp.status_code, attempt, _MAX_ATTEMPTS, backoff)
            else:
                resp.raise_for_status()
                return resp.content
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= _MAX_ATTEMPTS:
                break
            logger.warning("wayback id=%s fetch failed (attempt %d/%d): %s -- retrying in %ds",
                           indicator_id, attempt, _MAX_ATTEMPTS, exc, backoff)
        time.sleep(backoff)
        backoff *= 2
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"failed to fetch {url} after {_MAX_ATTEMPTS} attempts")


def land_bytes(bucket: str, key: str, data: bytes, *, source_url: str, region: str) -> None:
    from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
    from leviathan.storage.s3 import upload_bytes_to_s3

    check_min_file_size(data, _SOURCE_LABEL, context=key)
    upload_bytes_to_s3(data, bucket, key, region)
    write_raw_s3_metadata(bucket, key, data, source_url, _CONTENT_TYPE, region)
    logger.info("raw written -> s3://%s/%s (%d bytes)", bucket, key, len(data))


def raw_exists(bucket: str, key: str, region: str) -> bool:
    from leviathan.storage.s3 import get_thread_local_s3_client
    try:
        get_thread_local_s3_client(region).head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        stream=sys.stderr)
    load_env()
    ap = argparse.ArgumentParser(
        description="CEPEA series history via web.archive.org -> raw S3 (W1a, one-shot)")
    ap.add_argument("--indicator", action="append", type=int, dest="indicators", default=None,
                    choices=sorted(CEPEA_SNAPSHOTS),
                    help="repeatable; default is every curated snapshot")
    ap.add_argument("--force", action="store_true", help="re-fetch and overwrite an existing object")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--aws-region", default=None, dest="aws_region")
    ap.add_argument("--dry-run", action="store_true", help="print the URLs and keys; no HTTP")
    args = ap.parse_args(argv)

    indicators = args.indicators or sorted(CEPEA_SNAPSHOTS)

    if args.dry_run:
        for ind in indicators:
            snap = CEPEA_SNAPSHOTS[ind]
            print(f"id {ind} ({CEPEA_INDICATORS[ind]}), series from {snap['first_row']}")
            print(f"  url : {snapshot_url(ind)}")
            print(f"  key : {raw_cepea_wayback_key(ind, snap['ts'])}")
        print("(dry-run -- no HTTP, no writes)")
        print("NOTE the ~13-month residual gap (snapshot -> today) is ACCEPTED and is covered by "
              "forward accumulation from the daily widget's first run")
        return 0

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    landed = skipped = 0
    failures: list[str] = []
    for i, ind in enumerate(indicators):
        key = raw_cepea_wayback_key(ind, CEPEA_SNAPSHOTS[ind]["ts"])
        if not args.force and raw_exists(bucket, key, aws_region):
            skipped += 1
            continue
        if i:
            time.sleep(_SLEEP_SECONDS)
        try:
            payload = fetch_snapshot(ind)
            bad = looks_like_a_series_workbook(payload)
            if bad:
                raise ValueError(f"{snapshot_url(ind)}: {bad}")
            land_bytes(bucket, key, payload, source_url=snapshot_url(ind), region=aws_region)
            landed += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("FAILED CEPEA wayback snapshot for indicator %s", ind)
            failures.append(f"{ind}: {type(exc).__name__}")

    logger.info("CEPEA wayback done: landed=%d skipped_existing=%d failed=%d",
                landed, skipped, len(failures))
    if failures:
        logger.error("failed indicator(s): %s", ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
