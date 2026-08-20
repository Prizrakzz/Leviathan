#!/usr/bin/env python
"""PRICE_AND_PLAYBOOKS W1a / D1 -- the CEPEA history ONE-SHOT (raw landing only).

WHY AN ARCHIVE ROUTE AT ALL
---------------------------
CEPEA's own series pages are ``.aspx`` and they are Cloudflare-403 to plain ``requests``, to a FULL
Chrome header set (``sec-ch-ua``, ``Sec-Fetch-*``, ``Upgrade-Insecure-Requests``) and via WebFetch.
As of 2026-07-29 the origin serves an **interactive Turnstile challenge**, which we do not and will
not defeat -- that route is closed, permanently, by policy and not by capability.
**Only the ``.php`` widget is open**, and it returns the last value only. So the series cannot be
read from the origin at all -- but web.archive.org holds snapshots of the ``.aspx`` downloads, and
one snapshot per indicator carries the whole series *to its capture date*::

    id 23 arabica  cafe.aspx?id=23  @20170708153249   386,048 B   1996-09-02 .. 2017-07-07 (5,189 rows)
    id 77 corn     milho.aspx?id=77 @20171027074000   246,784 B   2004-08-02 .. 2017-10-26 (3,296 rows)

Those spans are MEASURED off the landed bytes, not inferred from the capture date -- see the next
section for why that distinction cost us a nine-year hole.

This job is a ONE-SHOT: two GETs, two objects, done. It is not a walk and it is not scheduled.

A WAYBACK TIMESTAMP IS A REQUEST, NOT A GUARANTEE
--------------------------------------------------
``/web/{ts}id_/{url}`` does not fail when ``ts`` has no capture: it **silently 200s with the
NEAREST capture**. The first cut of this job asked for ``20250608143948`` / ``20250614163045``,
timestamps that do not exist in the CDX index, and Wayback served the 2017 captures -- which then
landed under 2025-shaped keys and were described in this docstring as 2025 data. The row counts
looked plausible (5,193 / 3,300 raw rows) so nothing tripped. The CDX index is unambiguous: the
newest captures of these two export URLs that exist AT ALL are from 2017 (2 distinct digests for
id=23, 3 for id=77). We had a nine-year hole and a docstring that claimed thirteen months.

So :func:`fetch_snapshot` now returns the SERVED capture timestamp (parsed off the redirect URL,
cross-checked against ``Memento-Datetime``) and :func:`main` refuses to land bytes whose served
capture is not the pinned one. Provenance in the key is now a fact rather than a hope.

THE RESIDUAL GAP IS ~9 YEARS, AND IT IS ACCEPTED, NOT ENGINEERED AROUND
-----------------------------------------------------------------------
Between the 2017 captures and the daily widget's first run (2026-07-28) there is a **~9-year hole**
in both series. It is a hole in the MIDDLE, not a stale tail, so it breaks continuity for any
recent-basis work -- treat CEPEA history as 1996/2004-2017 plus forward accumulation, and check
:data:`CEPEA_SNAPSHOTS` spans before reaching for a window inside the gap. Filling it needs a
different, legitimately-accessible republisher of the two indicators; IPEADATA was swept and
carries none (3,585-series catalog, zero CEPEA/ESALQ). Nothing here fabricates a value to fill it,
and nothing should.

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

THE EXISTENCE PROBE FAILS CLOSED -- AND THIS IS THE WEAKEST OF THE EIGHT VERDICTS (2026-08-20)
-----------------------------------------------------------------------------------------------
``raw_exists`` gates the only PUT here, and the estate house idiom
(``except Exception: return False``) answers "absent" to a throttle, a 5xx, an expired token or a
denied head -- so a transient ``HeadObject`` failure makes the producer believe a landed object is
missing and PUT over it.

**Are these bytes re-derivable? YES, genuinely -- so this is NOT the EEX argument and it is not the
``fetch_cepea_daily.py`` argument either, and pretending otherwise would be dishonest.** An archive
is immutable by construction, the capture is PINNED from the CDX index, and :func:`wrong_capture`
refuses any body whose SERVED capture is not the pinned one. Re-fetching ``20170708153249`` returns
``20170708153249``. Even the raw_meta vintage argument that carried the daily leg is weak here: this
object's provenance is the WAYBACK CAPTURE INSTANT, which is pinned, verified and written into the
key -- not the fetch instant, which is the only irreproducible field in its ``raw_meta``.

It is narrowed anyway, on three grounds that do not need unrecoverability:

  1. THE COST OF FAILING CLOSED IS ZERO ON THIS LEG. It is a hand-run ONE-SHOT of two GETs. Exit 1
     costs a re-run and nothing else -- there is no schedule to burn, no window to miss and no
     cadence to keep. Free insurance is worth buying even against an unlikely loss.
  2. NOTHING COMPARES THE RE-FETCHED BYTES TO THE LANDED ONES. The OLE magic sniff and the 50 KB
     ``MIN_RAW_FILE_SIZES['cepea_wayback']`` floor both judge the NEW body in isolation; there is
     no byte comparison and no ``_divergence/`` record on this leg (``fetch_eex_freight.py`` has
     both). So a re-landing is unconditional, and whatever Wayback hands back that day wins.
  3. ``--force`` MUST MEAN SOMETHING. Under the swallow idiom a non-force run silently becomes a
     forced one whenever S3 throttles, which makes the flag's guarantee a coin flip.

So only a genuine 404 means absent; any other ``HeadObject`` error takes that INDICATOR out as a
recorded failure and the run exits 1. Exit 1 is Class D EXIT in
``infra/terraform/modules/batch/main.tf`` ``local.producer_retry_rules``, terminal after one
attempt -- archive.org is a library and must never see a retry storm.

Usage
-----
    python jobs/ingest/fetch_cepea_wayback_history.py --dry-run
    python jobs/ingest/fetch_cepea_wayback_history.py
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
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

# The two curated snapshots: the NEWEST captures that exist in the CDX index for each export URL
# (enumerated 2026-07-29 with collapse=digest, filter=statuscode:200). The timestamp is part of the
# raw key, so re-running lands the same object rather than a second copy -- which is exactly why it
# has to be the SERVED capture and not a wished-for date. ``last_row`` is measured off the landed
# bytes; the pair (first_row, last_row) is this leg's honest coverage claim.
CEPEA_SNAPSHOTS: dict[int, dict[str, str]] = {
    23: {"ts": "20170708153249",
         "target": "https://www.cepea.esalq.usp.br/br/indicador/series/cafe.aspx?id=23",
         "first_row": "1996-09-02", "last_row": "2017-07-07"},
    77: {"ts": "20171027074000",
         "target": "https://www.cepea.esalq.usp.br/br/indicador/series/milho.aspx?id=77",
         "first_row": "2004-08-02", "last_row": "2017-10-26"},
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

# The only S3 error codes that mean "this key is genuinely not there". Everything else raises --
# see raw_exists(). Mirrors fetch_eex_freight._ABSENT_ERROR_CODES.
_ABSENT_ERROR_CODES = frozenset({"404", "NotFound", "NoSuchKey"})


def snapshot_url(indicator_id: int) -> str:
    snap = CEPEA_SNAPSHOTS[int(indicator_id)]
    return _WAYBACK_FMT.format(ts=snap["ts"], target=snap["target"])


def looks_like_a_series_workbook(payload: bytes) -> Optional[str]:
    if not payload.startswith(_OLE_MAGIC):
        return (f"the response is not a legacy OLE workbook (first bytes {payload[:16]!r}) -- "
                f"web.archive.org served its HTML placeholder, so this capture is not there")
    return None


def wrong_capture(indicator_id: int, served: Optional[str]) -> Optional[str]:
    """None when the served capture is the pinned one, else why the bytes must not be landed.

    This is the guard the first cut lacked. An unmatched timestamp does not 404 -- it 200s with the
    nearest capture, and those bytes then wear the requested timestamp in the raw key forever.
    """
    wanted = CEPEA_SNAPSHOTS[int(indicator_id)]["ts"]
    if served is None:
        return ("the response carries neither a capture timestamp in its URL nor a "
                "Memento-Datetime header, so the capture it came from cannot be established")
    if served != wanted:
        return (f"wayback served capture {served}, not the pinned {wanted} -- an unmatched "
                f"timestamp silently redirects to the NEAREST capture, so these bytes are some "
                f"other day's series. Re-pin CEPEA_SNAPSHOTS from the CDX index rather than "
                f"landing them under the wrong provenance")
    return None


def served_capture_ts(resp: "requests.Response") -> Optional[str]:
    """The capture Wayback ACTUALLY served, or None if the response does not say.

    Wayback redirects an unmatched timestamp to the nearest capture, so the served timestamp lives
    in the final URL (``/web/{ts}id_/``). ``Memento-Datetime`` carries the same instant in RFC-1123
    and is used as a cross-check: if the two disagree the response is not trustworthy at all.
    """
    served = None
    match = re.search(r"/web/(\d{14})(?:id_)?/", resp.url or "")
    if match:
        served = match.group(1)
    memento = resp.headers.get("Memento-Datetime")
    if memento:
        try:
            stamp = parsedate_to_datetime(memento).astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
        except (TypeError, ValueError):
            stamp = None
        if stamp and served and stamp != served:
            raise ValueError(f"wayback disagrees with itself: URL says capture {served}, "
                             f"Memento-Datetime says {stamp}")
        served = served or stamp
    return served


def fetch_snapshot(indicator_id: int, *, timeout: int = _TIMEOUT) -> tuple[bytes, Optional[str]]:
    """The archived bytes AND the capture timestamp Wayback actually served."""
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
                return resp.content, served_capture_ts(resp)
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
    """True when the object is already landed. **Only a genuine 404 means "absent".**

    THIS DIVERGES FROM THE ESTATE HOUSE IDIOM ON PURPOSE -- see the module docstring's verdict, and
    note that it is the WEAKEST of the eight: an archive is immutable, the capture is pinned and
    :func:`wrong_capture` verifies what was served, so these bytes really are re-derivable. What the
    narrowing buys is that ``--force`` keeps meaning something (the swallow silently forces a
    non-force run on any throttle) on a leg where nothing compares the re-fetched bytes with the
    landed ones -- and on a two-GET one-shot, failing closed costs a re-run and nothing at all.

    The 403-instead-of-404 trap does NOT apply on this leg: ``batch_job_role`` carries
    ``s3:ListBucket`` on the bucket (infra/terraform/modules/iam/main.tf, sid
    ``ListDataLakeBucket``), so a HeadObject against a key that does not exist answers 404 rather
    than AccessDenied -- the narrowing cannot brick a first-ever capture.
    """
    from botocore.exceptions import ClientError
    from leviathan.storage.s3 import get_thread_local_s3_client

    try:
        get_thread_local_s3_client(region).head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        error = exc.response.get("Error") or {}
        code = str(error.get("Code") or "")
        status = (exc.response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
        # HeadObject has no body, so botocore reports the missing-key case as "404"/"NotFound"
        # rather than the "NoSuchKey" a GetObject would raise. Accept all three spellings.
        if code in _ABSENT_ERROR_CODES or status == 404:
            return False
        raise


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
            print(f"id {ind} ({CEPEA_INDICATORS[ind]}), "
                  f"series {snap['first_row']} .. {snap['last_row']}")
            print(f"  url : {snapshot_url(ind)}")
            print(f"  key : {raw_cepea_wayback_key(ind, snap['ts'])}")
        print("(dry-run -- no HTTP, no writes)")
        print("NOTE the residual gap is ~9 YEARS (2017 capture -> the daily widget's first run, "
              "2026-07-28), it is a hole in the MIDDLE of the series, and it is ACCEPTED: the "
              "origin is Turnstile-fenced and no republisher has been found. Do not read a window "
              "inside the gap and do not fabricate one.")
        return 0

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    landed = skipped = 0
    failures: list[str] = []
    for i, ind in enumerate(indicators):
        key = raw_cepea_wayback_key(ind, CEPEA_SNAPSHOTS[ind]["ts"])
        if not args.force:
            # THE ONLY raw_exists CALL SITE ON THIS LEG, and it sits ABOVE the try below, so the
            # per-indicator guard cannot catch it -- hence its own. An unanswerable probe is read
            # neither as "absent" (a silent overwrite) nor as "already landed" (a silent skip): the
            # INDICATOR is taken out as a RECORDED FAILURE, nothing is fetched for it, the other
            # indicator still runs, and the run exits 1 below. There is no exit-0 fall-through to
            # worry about here -- `if failures: return 1` is the last word.
            try:
                already_landed = raw_exists(bucket, key, aws_region)
            except Exception as exc:  # noqa: BLE001 -- raw_exists fails CLOSED and may raise here
                logger.error(
                    "CEPEA wayback indicator %s: the raw existence probe could not answer (%s: %s) "
                    "-- indicator SKIPPED and the run marked failed. Nothing fetched, NOTHING "
                    "WRITTEN: an unanswerable probe must never be read as 'absent' and PUT over a "
                    "landed capture", ind, type(exc).__name__, exc,
                )
                failures.append(f"{ind}: existence probe {type(exc).__name__}")
                continue
            if already_landed:
                skipped += 1
                continue
        if i:
            time.sleep(_SLEEP_SECONDS)
        try:
            payload, served = fetch_snapshot(ind)
            for bad in (looks_like_a_series_workbook(payload), wrong_capture(ind, served)):
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
