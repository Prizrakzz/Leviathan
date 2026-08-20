#!/usr/bin/env python
"""PRICE_AND_PLAYBOOKS W1b / D1 -- the MIAX Futures (ex-MGEX) settlement producer (raw landing).

SOURCE
------
    https://www.miaxglobal.com/sites/default/files/mgex/daily-settlement/
        Public_Daily_Settlement_File_{YYYY-MM-DD}.csv

Deterministic, date-templated, ``text/csv``, ~6.7 KB. **Probe P1a passed on the DEFAULT
``python-requests`` User-Agent** -- no UA, no cookies, no session, no Referer. Cleaner than CEPEA
and as clean as CZCE, which is why this leg ships with the ``requests``-first free-first wave rather
than behind a browser.

The index page (``/markets/futures/miax-futures/daily-reports``, 1.1 MB) is needed only for backfill
ENUMERATION and this job does not scrape it: the daily path is a pure date substitution, and the
backfill walks the calendar and reads a 404 as "no session".

Entry redirects worth recording so nobody re-discovers them: ``www.mgex.com/settlement.html`` 301s
to ``www.miaxglobal.com/settlement.html`` which 301s to the canonical daily-reports page. Pin the
canonical URL; do not depend on the 301 pair.

THE HISTORY WALL -- READ THIS BEFORE WIDENING --start
------------------------------------------------------
  * **CSV: 2025-09-09 -> today. ~222 sessions, about ten and a half months.** Four pre-boundary
    dates were probed (2025-09-08, 2025-06-02, 2024-07-29, 2023-09-18) and ALL return a
    63,668-byte Drupal 404 page. The wall is real, not a paginated listing.
  * 2023-06-01 -> 2025-09-08 exists as **PDF ONLY**, with a naming break at 2023-09-15/18. That
    tier is **OUT OF SCOPE for this wave**: it is a table-extraction job, and it must be an
    explicit decision rather than something a backfill loop half-does.
  * Before 2023-06-01 there is nothing on the site, and MIAX's historical-market-data product page
    sells options and equities feeds only -- futures/HRSW are not offered there either.

So :data:`MIAX_CSV_FIRST_TRADE_DATE` is a boundary this job REFUSES to walk past, rather than
spending several hundred requests discovering the same 404 wall again.

WHAT THE FILE DOES AND DOES NOT CARRY
-------------------------------------
75 rows on 2026-07-28: **7 outright futures and 68 options**, sharing one file (the option rows
carry a space, ``OMWH7 C6.50``). And **no volume and no open interest at all** -- those live in a
separate PDF that is not part of this leg. Both facts are the transform's business; this job lands
the whole file verbatim.

IDEMPOTENCE, AND THE PROBE THAT FAILS CLOSED
--------------------------------------------
The raw key is deterministic per session and an existing object is skipped without an HTTP request
unless ``--force``.

**VERDICT 2026-08-20 -- narrowed, and NOT on the EEX argument. Say the weaker case honestly.**
Unlike JSE, Bursa or EEX freight, this leg's bytes ARE re-derivable: the URL is a pure date
substitution over a static published file, a settled session file does not change, and the whole
CSV horizon above is still served. A capture destroyed here can be fetched again for the price of
one GET. So ``raw_exists`` is NOT narrowed because the data is unrecoverable. It is narrowed
because the house idiom (``except Exception: return False``) is WRONG IN TWO WAYS THAT COST
SOMETHING REAL ON A WALK THIS SHAPE:

  * IT VOIDS THE RESUME CONTRACT EXACTLY WHEN S3 IS UNHAPPY. A backfill is ~222 sequential HEADs,
    which is precisely the shape that provokes ``SlowDown``; every throttled head then reads as
    "absent" and re-issues the venue GET and the PUT for a day already landed. The idiom converts
    an S3 throttle into a venue-hammering re-walk of the entire window -- the opposite of what the
    skip-existing pass exists to do.
  * IT IS BLIND TO A RESTATEMENT. If MIAX ever republishes a corrected settlement file under the
    same URL, a silent overwrite destroys the first capture AND the only evidence the venue
    restated. This leg has no ``_divergence/`` machinery to catch that (``fetch_eex_freight.py``
    does), so the landed object is the sole witness.

So only a genuine 404 means absent; any other ``HeadObject`` error takes that SESSION out of the
walk as a RECORDED FAILURE (the run exits 1), never as a silent skip and never as a licence to
write. The cost of being wrong in that direction is one re-fire -- the incremental default already
re-walks the last 5 calendar days -- and exit 1 is Class D EXIT in
``infra/terraform/modules/batch/main.tf`` ``local.producer_retry_rules``, terminal after ONE
attempt, so it cannot become a retry storm.

S3 LAYOUT
---------
    raw/production/source=miax/year={YYYY}/trade_date={YYYYMMDD}/
        Public_Daily_Settlement_File_{YYYY-MM-DD}.csv
    raw_meta/<that key>_meta.json

Usage
-----
    python jobs/ingest/fetch_miax_eod.py --mode incremental
    python jobs/ingest/fetch_miax_eod.py --mode backfill --start 2025-09-09
    python jobs/ingest/fetch_miax_eod.py --mode incremental --dry-run
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
from leviathan.storage.paths import miax_daily_filename, raw_miax_key  # noqa: E402
from leviathan.transforms.raw_to_bronze.miax_eod import (  # noqa: E402
    MIAX_CSV_FIRST_TRADE_DATE,
    MIAX_PDF_FIRST_TRADE_DATE,
)

logger = get_logger("fetch_miax_eod")

_URL_FMT = ("https://www.miaxglobal.com/sites/default/files/mgex/daily-settlement/{filename}")
_SOURCE_LABEL = "miax"
_CONTENT_TYPE = "text/csv"
_TIMEOUT = 30
_DEFAULT_SLEEP_SECONDS = 1.5
_MAX_ATTEMPTS = 4
_BACKOFF_SECONDS = 5
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

# The header the file must open with, verbatim. A Drupal error page served with HTTP 200 fails
# here; a genuine missing session is a 404 and never reaches this check.
_EXPECTED_HEADER_TOKENS = ("Trade_Date", "Instrument", "Settle")
# The thinnest plausible session: 7 outrights + a header. A holiday is a 404, not a short file.
_MIN_DATA_LINES = 5

# The only S3 error codes that mean "this key is genuinely not there". Everything else raises --
# see raw_exists(). Mirrors fetch_eex_freight._ABSENT_ERROR_CODES.
_ABSENT_ERROR_CODES = frozenset({"404", "NotFound", "NoSuchKey"})


def miax_url(day: date) -> str:
    return _URL_FMT.format(filename=miax_daily_filename(day.isoformat()))


def daterange(start: date, end: date):
    """Every calendar day in ``[start, end]``. Sessions are decided by the venue (a 404)."""
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def looks_like_a_settlement_file(payload: bytes, day: date) -> Optional[str]:
    """None if the bytes are a plausible MIAX settlement CSV, else the reason they are not."""
    text = payload.decode("utf-8-sig", errors="replace")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "the response is empty"
    header = lines[0]
    missing = [t for t in _EXPECTED_HEADER_TOKENS if t not in header]
    if missing:
        return (f"the first line is missing {missing} (got {header[:120]!r}) -- this is not a "
                f"settlement CSV")
    if len(lines) < _MIN_DATA_LINES:
        return f"only {len(lines) - 1} data row(s) -- expected at least the 7 listed outrights"
    stamped = day.strftime("%-m/%-d/%y") if os.name != "nt" else day.strftime("%#m/%#d/%y")
    if stamped not in text:
        return (f"the file carries no row dated {stamped} -- the venue served another session")
    return None


def fetch_day(day: date, *, timeout: int = _TIMEOUT) -> Optional[bytes]:
    """The settlement CSV for ``day``; ``None`` when there is no such session (HTTP 404).

    NO custom headers: probe P1a passed clean on the default UA and adding one would turn a working
    request into an untested one."""
    url = miax_url(day)
    backoff = _BACKOFF_SECONDS
    last_error: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 404:
                return None
            if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS:
                logger.warning("MIAX %s returned HTTP %d (attempt %d/%d) -- retrying in %ds",
                               day, resp.status_code, attempt, _MAX_ATTEMPTS, backoff)
            else:
                resp.raise_for_status()
                return resp.content
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= _MAX_ATTEMPTS:
                break
            logger.warning("MIAX %s fetch failed (attempt %d/%d): %s -- retrying in %ds",
                           day, attempt, _MAX_ATTEMPTS, exc, backoff)
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
    note that the verdict here is the WEAKER one: these bytes are re-fetchable. What the swallow-all
    idiom actually costs on this leg is the resume contract (a throttled 222-day HEAD walk re-GETs
    and re-PUTs everything it already has) and restatement-blindness (a silent overwrite destroys
    the only witness that the venue republished a corrected file).

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
    """``(start, end)`` inclusive, per mode. Refuses a start before the CSV horizon."""
    first = datetime.strptime(MIAX_CSV_FIRST_TRADE_DATE, "%Y-%m-%d").date()
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
            f"--start {start} is before the MIAX CSV horizon {MIAX_CSV_FIRST_TRADE_DATE}. Every "
            f"probed earlier date returns a Drupal 404 page. {MIAX_PDF_FIRST_TRADE_DATE} .. "
            f"{MIAX_CSV_FIRST_TRADE_DATE} exists as PDF ONLY and is OUT OF SCOPE for this wave "
            f"(a table extraction with its own naming break); before {MIAX_PDF_FIRST_TRADE_DATE} "
            f"there is nothing at all. Refusing to spend the requests"
        )
    if end < start:
        raise SystemExit(f"--end {end} is before --start {start}")
    return start, end


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        stream=sys.stderr)
    load_env()
    ap = argparse.ArgumentParser(description="MIAX daily settlement CSV -> raw S3 (W1b)")
    ap.add_argument("--mode", choices=["backfill", "incremental"], default="incremental")
    ap.add_argument("--start", default=None, help="inclusive first session (YYYY-MM-DD)")
    ap.add_argument("--end", default=None, help="inclusive last session (YYYY-MM-DD)")
    ap.add_argument("--lookback-days", type=int, default=5,
                    help="incremental, used when --start is absent: walk the last N calendar days")
    ap.add_argument("--force", action="store_true", help="re-fetch and overwrite an existing object")
    ap.add_argument("--sleep", type=float, default=_DEFAULT_SLEEP_SECONDS,
                    help="seconds between GETs (politeness)")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--aws-region", default=None, dest="aws_region")
    ap.add_argument("--dry-run", action="store_true", help="print the window and keys; no HTTP")
    args = ap.parse_args(argv)

    start, end = resolve_window(args)
    days = list(daterange(start, end))
    logger.info("MIAX %s: %s .. %s (%d calendar day(s))", args.mode, start, end, len(days))

    if args.dry_run:
        print(f"mode      : {args.mode}")
        print(f"window    : {start} .. {end}  ({len(days)} calendar days)")
        print(f"first url : {miax_url(days[0])}")
        print(f"first key : {raw_miax_key(days[0].isoformat())}")
        print(f"last  key : {raw_miax_key(days[-1].isoformat())}")
        print(f"csv horizon starts {MIAX_CSV_FIRST_TRADE_DATE} (earlier is PDF-only, out of scope)")
        print("(dry-run -- no HTTP, no writes)")
        return 0

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    landed = skipped_existing = absent = 0
    failures: list[str] = []
    for day in days:
        key = raw_miax_key(day.isoformat())
        if not args.force:
            # THE ONLY raw_exists CALL SITE ON THIS LEG, and it sits ABOVE the try below, so the
            # per-day guard cannot catch it -- hence its own. An existence probe that cannot answer
            # is read neither as "absent" (which is how the old swallow-all raw_exists destroyed
            # captures: the capture path leads straight to the PUT with no second fence) nor as
            # "already landed" (a silent skip). The SESSION is taken out of the walk as a RECORDED
            # FAILURE: nothing fetched for it, nothing written, the other days still run, and the
            # run exits 1 below so the fire is not read as clean. No sleep is owed -- like the
            # skip-existing `continue`, this branch issues no MIAX request at all.
            try:
                already_landed = raw_exists(bucket, key, aws_region)
            except Exception as exc:  # noqa: BLE001 -- raw_exists fails CLOSED and may raise here
                logger.error(
                    "MIAX %s: the raw existence probe could not answer (%s: %s) -- session SKIPPED "
                    "and the run marked failed. Refusing to capture: an unanswerable probe must "
                    "never be read as 'absent' and PUT over a landed capture",
                    day, type(exc).__name__, exc,
                )
                failures.append(f"{day}: existence probe {type(exc).__name__}")
                continue
            if already_landed:
                skipped_existing += 1
                continue                      # HEAD on S3 only -- no MIAX GET, nothing to space
        try:
            payload = fetch_day(day)
            if payload is None:
                absent += 1                   # weekend / exchange holiday. Not an error.
                continue
            bad = looks_like_a_settlement_file(payload, day)
            if bad:
                raise ValueError(f"{miax_url(day)}: {bad}")
            land_bytes(bucket, key, payload, source_url=miax_url(day), region=aws_region)
            landed += 1
        except Exception as exc:  # noqa: BLE001 -- one day's failure must not abort the walk
            logger.exception("FAILED MIAX session %s", day)
            failures.append(f"{day}: {type(exc).__name__}")
        finally:
            # POLITENESS SPACING LIVES IN `finally` SO EVERY BRANCH THAT ISSUED A GET IS SPACED --
            # the absence branch above `continue`s and would otherwise jump a trailing sleep. Same
            # shape as fetch_czce_eod.py; see the longer note there. The only unspaced path is the
            # skip-existing `continue` ABOVE the try, which issues no MIAX request at all.
            time.sleep(max(0.0, args.sleep))

    logger.info("MIAX %s done: landed=%d skipped_existing=%d absent(404)=%d failed=%d",
                args.mode, landed, skipped_existing, absent, len(failures))
    if failures:
        logger.error("failed session(s): %s", ", ".join(failures[:20]))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
