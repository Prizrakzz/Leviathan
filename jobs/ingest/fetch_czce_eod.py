#!/usr/bin/env python
"""PRICE_AND_PLAYBOOKS W1a / D1 -- the CZCE daily quotation producer (raw landing only).

SOURCE
------
    https://www.czce.com.cn/cn/DFSStaticFiles/Future/{YYYY}/{YYYYMMDD}/FutureDataDaily.txt

One pipe-delimited text file per trading session, carrying every listed delivery month of all ~26
CZCE roots. This leg keeps two of them (``RM`` rapeseed meal, ``OI`` rapeseed OIL) -- but the RAW
object is the upstream bytes VERBATIM, whole file, no filtering: raw is a faithful capture and the
root selection is the transform's job.

THE REQUEST RECIPE, AND WHY IT LOOKS UNDER-ENGINEERED
-----------------------------------------------------
Plain ``requests``. **No custom User-Agent, no cookies, no session, no Referer.** That is not an
oversight and it must not be "fixed": re-verified live on 2026-07-27 and 2026-07-29, the default
``python-requests`` UA returns HTTP 200 with the full 37,747-byte payload. The CZCE WAF is
ASYMMETRIC -- the HTML pages under ``/cn/index.htm`` return **412** with a JS cookie challenge to
every UA tried, while the ``DFSStaticFiles`` tree is open. Adding a browser UA buys nothing and
changes a working request into an untested one.

Corollaries, all probed:
  * **There is no bulk archive.** ``/cn/exchange/...``, ``.htm`` and ``.zip`` all return 412 (WAF).
    The backfill is a day-by-day loop over ~2,600 files. Budget it as such; run it on Batch
    (``leviathan-dev-queue-ondemand``), not the laptop.
  * ``FutureDataDailyOption.txt`` does not exist (404). There is no options fallback to code.
  * **2015-10-08 is the first session that exists.** 2015-09-07 and every probed date before it
    return 404. Anything earlier is a PERMANENT absence, not a gap, and this job refuses to walk
    into it rather than spending 2,000 requests discovering that.
  * A non-session day (weekend, Golden Week, any exchange holiday) is simply a 404. That is an
    ABSENCE, not an error: the loop records it and moves on. The holiday calendar is derived
    EMPIRICALLY from the backfill (probe P10) and is never curated here.

IDEMPOTENCE, AND THE PROBE THAT FAILS CLOSED
--------------------------------------------
The raw key is deterministic per session (``.../year={YYYY}/trade_date={YYYYMMDD}/...``), and a day
whose object already exists is skipped without an HTTP request unless ``--force``. Re-running the
whole backfill is therefore cheap and safe, and a resumed run costs only the days it has not landed.

**VERDICT 2026-08-20 -- narrowed, and NOT on the EEX argument. The weaker case, said honestly.**
Unlike JSE or Bursa, this leg's bytes ARE re-derivable: ``DFSStaticFiles`` publishes one immutable
text file per closed session and the tree reaches back to 2015-10-08, so a destroyed capture costs
one GET to recover. ``raw_exists`` is therefore not narrowed for unrecoverability. It is narrowed
because the house idiom (``except Exception: return False``) is wrong in two ways that bite HERE:

  * IT VOIDS THE RESUME CONTRACT EXACTLY WHEN S3 IS UNHAPPY, and this is the leg where that costs
    most. A full backfill is ~2,600 sequential HEADs -- precisely the shape that provokes
    ``SlowDown`` -- and every throttled head then reads as "absent" and re-issues the venue GET and
    the PUT for a day already landed. The paragraph above promises a resumed run costs only what it
    has not landed; the swallow silently converts an S3 throttle into a full ~2,600-request re-walk
    against an origin that already answers 412 to anything it does not like. That is how a leg gets
    itself blocked.
  * IT IS BLIND TO A RESTATEMENT. If CZCE ever republishes a corrected session file at the same
    path, a silent overwrite destroys the first capture AND the only evidence of the restatement.
    There is no ``_divergence/`` machinery on this leg (``fetch_eex_freight.py`` has it); the
    landed object is the sole witness.

So only a genuine 404 means absent; any other ``HeadObject`` error takes that SESSION out of the
walk as a RECORDED FAILURE (the run exits 1), never as a silent skip and never as a licence to
write. Note the asymmetry that makes this safe: a 404 from the VENUE is still an absence and still
writes nothing, so failing closed on the S3 side cannot manufacture a missing trading day. Exit 1
is Class D EXIT in ``infra/terraform/modules/batch/main.tf`` ``local.producer_retry_rules``,
terminal after ONE attempt -- no retry storm.

S3 LAYOUT
---------
    raw/production/source=czce/year={YYYY}/trade_date={YYYYMMDD}/FutureDataDaily.txt
    raw_meta/<that key>_meta.json      (the write_raw_s3_metadata companion: sha256, size, url)

Usage
-----
    python jobs/ingest/fetch_czce_eod.py --mode incremental
    python jobs/ingest/fetch_czce_eod.py --mode backfill --start 2015-10-08
    python jobs/ingest/fetch_czce_eod.py --mode backfill --start 2016-01-01 --end 2016-12-31
    python jobs/ingest/fetch_czce_eod.py --mode incremental --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests  # noqa: E402
from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.storage.paths import CZCE_DAILY_FILENAME, raw_czce_key  # noqa: E402
from leviathan.transforms.raw_to_bronze.czce_eod import (  # noqa: E402
    CZCE_FIRST_TRADE_DATE,
    decode_bytes,
    header_trade_date,
)

logger = get_logger("fetch_czce_eod")

_URL_FMT = ("https://www.czce.com.cn/cn/DFSStaticFiles/Future/{year}/{compact}/"
            + CZCE_DAILY_FILENAME)
_SOURCE_LABEL = "czce"
_CONTENT_TYPE = "text/plain"
_TIMEOUT = 30

# Politeness. The venue publishes a static file and the backfill is ~2,600 sequential GETs, so the
# spacing is the whole rate-limit story -- there is no key, no quota and no documented limit.
_DEFAULT_SLEEP_SECONDS = 1.0

_MAX_ATTEMPTS = 4
_BACKOFF_SECONDS = 5
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
# 412 is the CZCE WAF's JS cookie challenge. It is NOT retryable and NOT an absence: retrying it
# hammers the venue, and treating it as "no session" would silently erase a trading day.
_WAF_STATUS = 412

# A real session file carries >= 100 contract rows (the thinnest observed is 2015-10-08 with 134
# across 17 roots). This is a SHAPE sniff on the response, not a data floor -- the silver row floor
# (gate 5) lives in jobs/batch/futures_eod_task.py and counts SILVER rows for the two kept slugs.
_MIN_DATA_LINES = 50

# The only S3 error codes that mean "this key is genuinely not there". Everything else raises --
# see raw_exists(). Mirrors fetch_eex_freight._ABSENT_ERROR_CODES.
_ABSENT_ERROR_CODES = frozenset({"404", "NotFound", "NoSuchKey"})


def czce_url(day: date) -> str:
    compact = day.strftime("%Y%m%d")
    return _URL_FMT.format(year=compact[:4], compact=compact)


def daterange(start: date, end: date):
    """Every calendar day in ``[start, end]``. Sessions are decided by the venue (a 404), never by
    a curated calendar -- see probe P10."""
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def looks_like_a_session_file(payload: bytes, day: date) -> Optional[str]:
    """None if the bytes are a plausible CZCE daily file, else the reason they are not.

    Guards the case a size floor cannot see: a 200 response carrying a challenge/error page that is
    merely large enough. The check is structural (pipe-delimited rows + the file's own header date),
    never a parse -- all parsing authority stays in the transform so raw and bronze cannot
    disagree about what the file said."""
    text, _enc = decode_bytes(payload)
    lines = [ln for ln in text.splitlines() if ln.count("|") >= 12]
    if len(lines) < _MIN_DATA_LINES:
        return (f"only {len(lines)} pipe-delimited row(s), expected >= {_MIN_DATA_LINES} -- this is "
                f"not a session file")
    stamped = header_trade_date(text)
    want = day.isoformat()
    if stamped is not None and stamped != want:
        return f"the file's own header date is {stamped}, not {want} -- the venue served another day"
    return None


def fetch_day(day: date, *, timeout: int = _TIMEOUT) -> Optional[bytes]:
    """The session file for ``day``; ``None`` when the venue has no such session (HTTP 404).

    Bounded exponential-backoff retry on a connection failure or a 429/5xx. A 404 returns None
    immediately -- weekends, Golden Week and every other closure are absences, not failures. A 412
    raises: it is the WAF, and pretending it is a closed session would erase a trading day."""
    url = czce_url(day)
    backoff = _BACKOFF_SECONDS
    last_error: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            # NO custom headers. See the module docstring -- the default UA is the working recipe.
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 404:
                return None
            if resp.status_code == _WAF_STATUS:
                raise RuntimeError(
                    f"{url} returned HTTP 412 -- the CZCE WAF challenged the request. This is NOT a "
                    f"closed session. Do not add a browser User-Agent to 'fix' it: the "
                    f"DFSStaticFiles tree is open to the default UA and the HTML tree is not"
                )
            if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS:
                logger.warning("CZCE %s returned HTTP %d (attempt %d/%d) -- retrying in %ds",
                               day, resp.status_code, attempt, _MAX_ATTEMPTS, backoff)
            else:
                resp.raise_for_status()
                return resp.content
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= _MAX_ATTEMPTS:
                break
            logger.warning("CZCE %s fetch failed (attempt %d/%d): %s -- retrying in %ds",
                           day, attempt, _MAX_ATTEMPTS, exc, backoff)
        time.sleep(backoff)
        backoff *= 2
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"failed to fetch {url} after {_MAX_ATTEMPTS} attempts")


def land_bytes(bucket: str, key: str, data: bytes, *, source_url: str, region: str) -> None:
    """Upload one raw artifact + its ``write_raw_s3_metadata`` companion, after the size floor.

    The house raw-landing convention, copied from ``fetch_databento_eod.land_bytes``. NOTE that
    ``check_min_file_size`` returns SILENTLY when the source key is absent from
    ``MIN_RAW_FILE_SIZES`` -- a missing entry is a DISABLED floor, not an error -- so
    ``constants.MIN_RAW_FILE_SIZES['czce']`` is part of this producer, not decoration."""
    from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
    from leviathan.storage.s3 import upload_bytes_to_s3

    check_min_file_size(data, _SOURCE_LABEL, context=key)
    upload_bytes_to_s3(data, bucket, key, region)
    write_raw_s3_metadata(bucket, key, data, source_url, _CONTENT_TYPE, region)
    logger.info("raw written -> s3://%s/%s (%d bytes)", bucket, key, len(data))


def raw_exists(bucket: str, key: str, region: str) -> bool:
    """True when the object is already landed. **Only a genuine 404 means "absent".**

    THIS DIVERGES FROM THE ESTATE HOUSE IDIOM ON PURPOSE -- see the module docstring's verdict, and
    note that the verdict here is the WEAKER one: these bytes are re-fetchable. What the swallow-all
    idiom actually costs on this leg is the resume contract (a throttled ~2,600-day HEAD walk re-GETs
    and re-PUTs everything it already has, at an origin that answers 412 to anything it dislikes)
    and restatement-blindness (a silent overwrite destroys the only witness that the venue
    republished a corrected session file).

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


def resolve_window(args) -> tuple[date, date]:
    """``(start, end)`` inclusive, per mode. Refuses a start before the venue's first session."""
    first = datetime.strptime(CZCE_FIRST_TRADE_DATE, "%Y-%m-%d").date()
    today = datetime.now(tz=timezone.utc).date()
    if args.mode == "incremental":
        end = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else today
        start = (datetime.strptime(args.start, "%Y-%m-%d").date() if args.start
                 else end - timedelta(days=max(1, args.lookback_days)))
    else:
        start = datetime.strptime(args.start, "%Y-%m-%d").date() if args.start else first
        end = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else today
    if start < first:
        raise SystemExit(
            f"--start {start} is before CZCE's first published session {CZCE_FIRST_TRADE_DATE}. "
            f"Everything earlier is a PERMANENT absence (probed: 2015-09-07 and earlier all 404), "
            f"not a gap to walk -- refusing to spend the requests"
        )
    if end < start:
        raise SystemExit(f"--end {end} is before --start {start}")
    return start, end


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        stream=sys.stderr)
    load_env()
    ap = argparse.ArgumentParser(description="CZCE FutureDataDaily.txt -> raw S3 (W1a)")
    ap.add_argument("--mode", choices=["backfill", "incremental"], default="incremental")
    ap.add_argument("--start", default=None, help="inclusive first session (YYYY-MM-DD)")
    ap.add_argument("--end", default=None, help="inclusive last session (YYYY-MM-DD)")
    ap.add_argument("--lookback-days", type=int, default=5,
                    help="incremental, used when --start is absent: walk the last N calendar days. "
                         "The scheduler substitutes only <aws.scheduler.*> attributes, so the "
                         "scheduled chain passes this rather than a templated date")
    ap.add_argument("--force", action="store_true",
                    help="re-fetch and overwrite a session whose raw object already exists")
    ap.add_argument("--sleep", type=float, default=_DEFAULT_SLEEP_SECONDS,
                    help="seconds between GETs (politeness; the backfill is ~2,600 sequential)")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--aws-region", default=None, dest="aws_region")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the window and the keys; no HTTP, no writes")
    args = ap.parse_args(argv)

    start, end = resolve_window(args)
    days = list(daterange(start, end))
    logger.info("CZCE %s: %s .. %s (%d calendar day(s))", args.mode, start, end, len(days))

    if args.dry_run:
        print(f"mode      : {args.mode}")
        print(f"window    : {start} .. {end}  ({len(days)} calendar days)")
        print(f"first url : {czce_url(days[0])}")
        print(f"first key : {raw_czce_key(days[0].isoformat())}")
        print(f"last  key : {raw_czce_key(days[-1].isoformat())}")
        print("(dry-run -- no HTTP, no writes)")
        return 0

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    landed = skipped_existing = absent = 0
    failures: list[str] = []
    for day in days:
        key = raw_czce_key(day.isoformat())
        if not args.force:
            # THE ONLY raw_exists CALL SITE ON THIS LEG, and it sits ABOVE the try below, so the
            # per-day guard cannot catch it -- hence its own. An existence probe that cannot answer
            # is read neither as "absent" (which is how the old swallow-all raw_exists destroyed
            # captures: the capture path leads straight to the PUT with no second fence) nor as
            # "already landed" (a silent skip). The SESSION is taken out of the walk as a RECORDED
            # FAILURE: nothing fetched for it, nothing written, the other days still run, and the
            # run exits 1 below so the fire is not read as clean. No sleep is owed -- like the
            # skip-existing `continue`, this branch issues no CZCE request at all.
            try:
                already_landed = raw_exists(bucket, key, aws_region)
            except Exception as exc:  # noqa: BLE001 -- raw_exists fails CLOSED and may raise here
                logger.error(
                    "CZCE %s: the raw existence probe could not answer (%s: %s) -- session SKIPPED "
                    "and the run marked failed. Refusing to capture: an unanswerable probe must "
                    "never be read as 'absent' and PUT over a landed capture",
                    day, type(exc).__name__, exc,
                )
                failures.append(f"{day}: existence probe {type(exc).__name__}")
                continue
            if already_landed:
                skipped_existing += 1
                continue                          # HEAD on S3 only -- no CZCE GET, nothing to space
        try:
            payload = fetch_day(day)
            if payload is None:
                absent += 1                       # weekend / holiday / not a session. Not an error.
                continue
            bad = looks_like_a_session_file(payload, day)
            if bad:
                raise ValueError(f"{czce_url(day)}: {bad}")
            land_bytes(bucket, key, payload, source_url=czce_url(day), region=aws_region)
            landed += 1
        except Exception as exc:  # noqa: BLE001 -- one day's failure must not abort the walk
            logger.exception("FAILED CZCE session %s", day)
            failures.append(f"{day}: {type(exc).__name__}")
        finally:
            # POLITENESS SPACING LIVES IN `finally` SO EVERY BRANCH THAT ISSUED A GET IS SPACED.
            # The 404/absence branch above `continue`s, and a bare trailing sleep would be jumped
            # clean over: the ~2,600-day backfill from 2015-10-08 is roughly 1,150 non-sessions, and
            # Golden Week alone is 7-10 consecutive 404s that would otherwise be fired back-to-back
            # at an origin that already answers 412 (WAF) on /cn/exchange/, .htm and .zip. `finally`
            # runs on `continue` and on the handled exception alike; the only unspaced path is the
            # skip-existing `continue` ABOVE the try, which issues no CZCE request at all.
            time.sleep(max(0.0, args.sleep))

    logger.info("CZCE %s done: landed=%d skipped_existing=%d absent(404)=%d failed=%d",
                args.mode, landed, skipped_existing, absent, len(failures))
    if failures:
        logger.error("failed session(s): %s", ", ".join(failures[:20]))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
