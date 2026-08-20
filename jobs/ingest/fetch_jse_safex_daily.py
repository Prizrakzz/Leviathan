#!/usr/bin/env python
"""PRICE_AND_PLAYBOOKS W1a / D1 -- the JSE/SAFEX agri MTM producer (raw landing only).

SOURCE
------
    https://clientportal.jse.co.za/_layouts/15/DownloadHandler.ashx
        ?FileName=/Safex/amdmtm/NEW%20DAYAGR.xls

One legacy-OLE workbook (81,920 B, sheet ``Sheet1``, 140x11) carrying every listed delivery month of
all 31 JSE commodity-derivative contract sections. This leg keeps two of them
(``WHITE MAIZE FUTURE`` / ``YELLOW MAIZE FUTURE``, EXACT match) -- but the RAW object is the
upstream bytes VERBATIM, whole workbook, no filtering: raw is a faithful capture and the section
selection is the transform's job.

DISCOVERY PATH, RECORDED SO NOBODY RE-WALKS IT
----------------------------------------------
``?RequestNode=/Safex`` enumerates the portal's node tree. Three findings worth keeping:

  * **``/Safex/Mtm`` -- the node the PUBLIC JSE site links to -- is EMPTY.**
  * ``/Safex/mtmdata/MTM All.xls`` is *financial* derivatives and is stale, dated 2019-04-25.
  * **The live agri file is under ``/Safex/amdmtm``.** That is the URL above and nothing else.

Also public and richer if it is ever wanted: ``/Safex/APDStats/AMDFULL.xls`` (1.47 MB, 10,273 rows,
option strikes + margin + turnover). Not used here.

THERE IS NO HISTORY. NONE. THIS IS THE MOST CONSEQUENTIAL FACT IN W1a
---------------------------------------------------------------------
The portal object is **overwritten every single day**, and Wayback does not rescue it: the CDX index
holds exactly ONE capture of ``NEW DAYAGR.xls`` in its entire history (``20240714021022``). The
house wayback-backfill pattern (``fetch_usda_wap_wayback.py``, ``discover_unica_wayback.py``) is
simply unavailable on this leg.

**So JSE price history starts the day this producer first runs, and every missed run is data that no
one can ever recover.** Cadence discipline matters more here than anywhere else in the wave.

Plan gate 8 makes that a CODE requirement rather than a policy line: this job **fails** if it is
ever asked to backfill. An explicit ``NotImplementedError`` is strictly better than an empty result,
because an empty result on a table with no freshness alarm yet is indistinguishable from a holiday.

IDEMPOTENCE, AND THE PROBE THAT FAILS CLOSED
--------------------------------------------
The raw key is per FETCH DAY (``as_of_date=``), not per trade date -- the fetch date is the only
immutability this leg will ever have, because the source object has no version of its own. A day
whose object already exists is skipped without an HTTP request unless ``--force``. The SESSION date
comes from the sheet's own header and is the transform's business.

**VERDICT 2026-08-20 -- THIS LEG TAKES THE EEX FAIL-CLOSED PROBE AT FULL STRENGTH, and the section
above this one is the whole argument.** ``fetch_bursa_fcpo.py``'s own docstring names this producer
as the no-history precedent ("gate 8"), and the recoverability question has already been answered
here in the hardest possible terms: the portal object is overwritten every single day and the CDX
index holds ONE capture of it in its entire history. There is no date parameter, no archive, no
vendor backfill and -- by :func:`refuse_backfill` -- no code path that may pretend otherwise.

``raw_exists`` gates the only PUT on this leg's raw data plane. The estate house idiom
(``except Exception: return False``) answers "absent" to a throttle, a 5xx, an expired token or a
denied head, so a transient ``HeadObject`` failure would make the producer believe today's landed
capture is missing and PUT a later intraday render of the same overwritten object over it. The
bytes destroyed that way are gone at any price. So only a genuine 404 means absent; every other
head error fails the run (exit 1) with NOTHING fetched and nothing written.

Failing is cheap and the failure is terminal, by design: exit 1 is Class D EXIT in
``infra/terraform/modules/batch/main.tf`` ``local.producer_retry_rules`` (with the mandatory
terminal ``on_reason = "*"`` rule behind it), so a nonzero exit is terminal after ONE attempt and
cannot become a retry storm against the portal.

S3 LAYOUT
---------
    raw/production/source=jse_safex/year={YYYY}/as_of_date={YYYY-MM-DD}/NEW_DAYAGR.xls
    raw_meta/<that key>_meta.json      (sha256, size, the true source URL with its space intact)

Usage
-----
    python jobs/ingest/fetch_jse_safex_daily.py
    python jobs/ingest/fetch_jse_safex_daily.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests  # noqa: E402
from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.storage.paths import raw_jse_safex_key  # noqa: E402

logger = get_logger("fetch_jse_safex_daily")

JSE_URL = ("https://clientportal.jse.co.za/_layouts/15/DownloadHandler.ashx"
           "?FileName=/Safex/amdmtm/NEW%20DAYAGR.xls")
_SOURCE_LABEL = "jse_safex"
_CONTENT_TYPE = "application/vnd.ms-excel"
_TIMEOUT = 60
_MAX_ATTEMPTS = 4
_BACKOFF_SECONDS = 5
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

# The only S3 error codes that mean "this key is genuinely not there". Everything else raises --
# see raw_exists(). Mirrors fetch_eex_freight._ABSENT_ERROR_CODES.
_ABSENT_ERROR_CODES = frozenset({"404", "NotFound", "NoSuchKey"})

# Legacy OLE compound-document magic. A portal error page served with HTTP 200 fails here rather
# than landing as a "workbook" that the transform then cannot open.
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_BACKFILL_MESSAGE = (
    "JSE has no history; series starts at first run. The portal object is overwritten daily and "
    "web.archive.org holds exactly ONE capture of NEW DAYAGR.xls ever (20240714021022), so there "
    "is no source to walk. Refusing to pretend otherwise -- an empty result here would be "
    "indistinguishable from a public holiday"
)


def refuse_backfill() -> None:
    """PLAN GATE 8. Raised by any code path that asks this leg for history."""
    raise NotImplementedError(_BACKFILL_MESSAGE)


def looks_like_the_agri_workbook(payload: bytes) -> Optional[str]:
    """None if the bytes are a plausible JSE agri workbook, else the reason they are not."""
    if not payload.startswith(_OLE_MAGIC):
        head = payload[:64]
        return (f"the response is not a legacy OLE workbook (first bytes {head[:16]!r}) -- the "
                f"portal served an error page or an HTML redirect with HTTP 200")
    return None


def fetch_workbook(*, timeout: int = _TIMEOUT) -> bytes:
    """The current agri MTM workbook. Bounded exponential-backoff retry on 429/5xx.

    A 404 is NOT an absence here the way a CZCE 404 is: this URL is a single overwritten object, so
    a 404 means the portal moved it and the leg is broken. It raises."""
    import time

    backoff = _BACKOFF_SECONDS
    last_error: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = requests.get(JSE_URL, timeout=timeout)
            if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS:
                logger.warning("JSE returned HTTP %d (attempt %d/%d) -- retrying in %ds",
                               resp.status_code, attempt, _MAX_ATTEMPTS, backoff)
            else:
                resp.raise_for_status()
                return resp.content
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= _MAX_ATTEMPTS:
                break
            logger.warning("JSE fetch failed (attempt %d/%d): %s -- retrying in %ds",
                           attempt, _MAX_ATTEMPTS, exc, backoff)
        time.sleep(backoff)
        backoff *= 2
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"failed to fetch {JSE_URL} after {_MAX_ATTEMPTS} attempts")


def land_bytes(bucket: str, key: str, data: bytes, *, source_url: str, region: str) -> None:
    """Upload one raw artifact + its ``write_raw_s3_metadata`` companion, after the size floor.

    NOTE that ``check_min_file_size`` returns SILENTLY when the source key is absent from
    ``MIN_RAW_FILE_SIZES`` -- a missing entry is a DISABLED floor, not an error -- so
    ``constants.MIN_RAW_FILE_SIZES['jse_safex']`` is part of this producer, not decoration."""
    from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
    from leviathan.storage.s3 import upload_bytes_to_s3

    check_min_file_size(data, _SOURCE_LABEL, context=key)
    upload_bytes_to_s3(data, bucket, key, region)
    write_raw_s3_metadata(bucket, key, data, source_url, _CONTENT_TYPE, region)
    logger.info("raw written -> s3://%s/%s (%d bytes)", bucket, key, len(data))


def raw_exists(bucket: str, key: str, region: str) -> bool:
    """True when the object is already landed. **Only a genuine 404 means "absent".**

    THIS DIVERGES FROM THE ESTATE HOUSE IDIOM ON PURPOSE -- see the module docstring's verdict.
    ``except Exception: return False`` turns a throttle, a 5xx or an expired credential into
    "nothing is landed", which is a licence to PUT over the only copy of a day that the portal
    overwrites nightly and that web.archive.org captured exactly ONCE, ever.

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
    ap = argparse.ArgumentParser(description="JSE/SAFEX NEW DAYAGR.xls -> raw S3 (W1a)")
    # --mode exists ONLY so that an operator or a scheduler copying the CZCE/MIAX invocation gets
    # the plan's gate-8 error instead of a silent no-op. There is no backfill to run.
    ap.add_argument("--mode", choices=["incremental", "backfill"], default="incremental")
    ap.add_argument("--as-of", default=None, dest="as_of",
                    help="the FETCH date used in the raw key (default: today, UTC). The SESSION "
                         "date is read from the sheet's own header by the transform")
    ap.add_argument("--force", action="store_true",
                    help="re-fetch and overwrite today's capture if it already exists")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--aws-region", default=None, dest="aws_region")
    ap.add_argument("--dry-run", action="store_true", help="print the URL and key; no HTTP, no writes")
    args = ap.parse_args(argv)

    if args.mode == "backfill":
        logger.error("%s", _BACKFILL_MESSAGE)
        refuse_backfill()

    as_of = args.as_of or datetime.now(tz=timezone.utc).date().isoformat()
    key = raw_jse_safex_key(as_of)

    if args.dry_run:
        print(f"url    : {JSE_URL}")
        print(f"as_of  : {as_of}")
        print(f"key    : {key}")
        print("(dry-run -- no HTTP, no writes)")
        return 0

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    if not args.force:
        # THE ONLY raw_exists CALL SITE ON THIS LEG, and the capture path below leads straight to
        # the PUT with no second fence in front of it. An existence probe that cannot answer must
        # be read neither as "absent" (which is how the old swallow-all raw_exists destroyed
        # captures) nor as "already landed" (a silent skip, on a leg where a skipped day is an
        # unrecoverable day). It fails the run instead: one line, exit 1, NOTHING fetched.
        try:
            already_landed = raw_exists(bucket, key, aws_region)
        except Exception as exc:  # noqa: BLE001 -- raw_exists fails CLOSED and may raise here
            logger.error(
                "FAILED JSE capture for %s: the raw existence probe could not answer (%s: %s) -- "
                "nothing fetched, NOTHING WRITTEN. Refusing to capture: an unanswerable probe must "
                "never be read as 'absent' and PUT over a landed capture on a leg whose source "
                "object is overwritten daily and has ONE archive capture in its whole history",
                as_of, type(exc).__name__, exc,
            )
            return 1
        if already_landed:
            logger.info("JSE capture for %s already landed -- skipping (use --force to re-fetch)",
                        as_of)
            return 0
    try:
        payload = fetch_workbook()
        bad = looks_like_the_agri_workbook(payload)
        if bad:
            raise ValueError(f"{JSE_URL}: {bad}")
        land_bytes(bucket, key, payload, source_url=JSE_URL, region=aws_region)
    except Exception:  # noqa: BLE001
        logger.exception("FAILED JSE capture for %s -- THIS DAY IS UNRECOVERABLE (the source "
                         "object is overwritten and has no archive)", as_of)
        return 1
    logger.info("JSE capture %s landed", as_of)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
