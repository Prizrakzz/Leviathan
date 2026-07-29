#!/usr/bin/env python
"""PRICE_AND_PLAYBOOKS W1c / D1 -- the DCE (Dalian) producer, browser-driven (raw landing only).

SOURCE
------
    http://www.dce.com.cn/dcereport/quote/delay/futureData?variety={v}        (--mode daily)
    http://www.dce.com.cn/dcereport/quote/history/download?type=1&year={Y}&variety={v}
                                                                             (--mode history)

Five varieties, all five of the ``source == "dce"`` contracts:
``p`` palm olein, ``a`` soybeans no.1, ``b`` soybeans no.2, ``m`` soybean meal, ``y`` soybean oil.

WHY THIS PRODUCER DRIVES A BROWSER AND THE CZCE ONE DOES NOT
------------------------------------------------------------
CZCE's static-file tree answers plain ``python-requests`` with HTTP 200 and that is deliberately not
"fixed". DCE is the opposite case, probed live 2026-07-29: **every** plain request answers 412 --
the Ruishu WAF's JS cookie challenge -- from a residential IP AND from Fargate. There is no header
recipe that clears it, because clearing it means EXECUTING the challenge script. Headless Chromium
does that in ~5-10 seconds and then the ordinary JSON endpoints answer 200.

So this leg carries a browser, and the browser carries a question: does the challenge also settle
from a DATACENTER IP? That is residual probe S2, and it cannot be answered from a laptop. **The
first Fargate run of this producer IS the probe** -- ``ChallengeFailed`` exits
:data:`EXIT_CHALLENGE_FAILED` (7) and nothing else does, so one exit code answers it.

THE NOT_READY GUARD IS THE MOST IMPORTANT LINE OF CODE HERE
-----------------------------------------------------------
The daily endpoint serves the CURRENT state of the board, and ``settlePrice``/``closePrice`` are
``0.0`` until the exchange publishes the settlement after the 15:00 Beijing close. Worse, when the
night session opens at 21:00 Beijing the endpoint rolls its own ``tradeDate`` FORWARD to T+1 while
the settles are still zero -- which is exactly the state fixture ``dce_futureData_p.json`` was
captured in. An unguarded producer running at the wrong hour would therefore land a full-size,
well-formed, entirely FICTIONAL board dated one day into the future.

Hence: a variety whose every contract reads ``settlePrice == 0.0`` is NOT SETTLED YET. It is logged
and SKIPPED, and no object is written -- never a zero-price raw file, because zero is not a price
and a landed object is what every downstream step trusts. If EVERY selected variety is skipped, the
process exits :data:`EXIT_NOT_READY` (5): the run was too early (or too late), which a scheduler can
retry, and which is a different fact from a failure.

Fire between the 15:30 and the 21:00 Beijing boundaries (07:30-13:00 UTC).

HISTORY IS A ONE-SHOT, AND IT IS CHEAP TO RESUME
------------------------------------------------
``--mode history`` walks ``(variety, year)`` and downloads the vendor's own
``{v}_ftr.xlsx`` -- one workbook per variety-year (2016 palm olein: 188,440 B, 2,928 rows). The key
is deterministic, so a landed pair is skipped with a HEAD and no download at all: re-running the
whole 2006-2026 walk costs only the pairs that have not landed.

S3 LAYOUT
---------
    raw/production/source=dce/variety={v}/as_of_date={YYYY-MM-DD}/futureData.json
    raw/production/source=dce/variety={v}/history/year={YYYY}/{v}_ftr.xlsx
    raw_meta/<that key>_meta.json      (the write_raw_s3_metadata companion: sha256, size, url)

EXIT CODES
----------
    0  everything selected either landed or was already landed
    1  at least one variety/year failed for an ordinary reason -- INCLUDING a NavigationFailed,
       i.e. the venue was never reached (DNS/egress/TLS). That is deliberately NOT a 7: a broken
       route says nothing about whether the WAF clears from this IP class
    5  NOT_READY -- every selected variety is still unsettled (nothing was written)
    7  CHALLENGE_FAILED -- the venue's JS challenge never SETTLED (the residual S2 answer)

Usage
-----
    python jobs/ingest/fetch_dce_eod.py --mode daily
    python jobs/ingest/fetch_dce_eod.py --mode daily --as-of-date 2026-07-29 --variety p
    python jobs/ingest/fetch_dce_eod.py --mode history --year-start 2006 --year-end 2026
    python jobs/ingest/fetch_dce_eod.py --mode daily --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _REPO_ROOT)
# ...and src/, unlike the W1a producers: this leg imports leviathan.ingest.browser_fetch, which is
# NEW in W1c, so a stale editable install that predates it would otherwise fail at import.
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.ingest.browser_fetch import (  # noqa: E402
    EXIT_CHALLENGE_FAILED,
    BrowserSession,
    ChallengeFailed,
    NavigationFailed,
    ascii_safe,
    challenge_failed_exit,
    navigation_failed_exit,
)
from leviathan.storage.paths import raw_dce_daily_key, raw_dce_history_key  # noqa: E402
from leviathan.transforms.raw_to_bronze.dce_eod import (  # noqa: E402
    DCE_FIRST_HISTORY_YEAR,
    DCE_VARIETY_MAP,
    daily_not_ready,
    daily_records,
)

logger = get_logger("fetch_dce_eod")

DCE_BASE_URL = "http://www.dce.com.cn"
DAILY_PATH = "/dcereport/quote/delay/futureData?variety={variety}"
HISTORY_PATH = "/dcereport/quote/history/download?type=1&year={year}&variety={variety}"
# The homepage is what mints the WAF cookie; the JSON endpoints are only reachable behind it.
SETTLE_PATH = "/"
# The variety the readiness probe uses. Any of the five would do -- p is the flagship and the one
# every capture note is written against.
_READY_VARIETY = "p"

_DAILY_SOURCE_LABEL = "dce_daily"
_HISTORY_SOURCE_LABEL = "dce_history"
_DAILY_CONTENT_TYPE = "application/json"
_HISTORY_CONTENT_TYPE = ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# NOT_READY. Distinct from 1 (a real failure) and from 7 (the venue refused the session): the run
# fired outside the settlement window, which is a scheduling fact and is retryable as-is.
EXIT_NOT_READY = 5

# xlsx is a zip. A challenge/error document served as an "attachment" fails here rather than landing
# as a "workbook" the transform then cannot open (the JSE OLE-magic precedent).
_ZIP_MAGIC = b"PK\x03\x04"

# Politeness between downloads. The history walk is (5 varieties x ~21 years) = ~105 downloads of
# ~200 KB against a venue that already answers 412 to anything that does not look like a browser.
_DEFAULT_SLEEP_SECONDS = 1.5
_SETTLE_MAX_WAIT_S = 90


def _today_utc() -> str:
    return datetime.now(tz=timezone.utc).date().isoformat()


def quote_api_ready(session: BrowserSession):
    """A ``ready_check(page)`` that asks the REAL endpoint whether the WAF has stood down.

    Deliberately the same in-page call the producer is about to make, not a DOM heuristic: "the
    homepage rendered" and "the JSON API answers 200 to an in-page fetch" are different facts, and
    only the second one means the capture can proceed. While the challenge is up the fetch raises,
    and ``goto_and_settle`` reads a raising probe as "not ready yet"."""

    def _check(_page) -> bool:
        body = session.fetch_text(DAILY_PATH.format(variety=_READY_VARIETY),
                                  accept="application/json")
        obj = json.loads(body)
        return bool(obj.get("data"))

    return _check


def land_bytes(bucket: str, key: str, data: bytes, *, source_url: str, region: str,
               source_label: str, content_type: str) -> None:
    """Upload one raw artifact + its ``write_raw_s3_metadata`` companion, after the size floor.

    The house raw-landing convention, copied from ``fetch_czce_eod.land_bytes``. NOTE that
    ``check_min_file_size`` returns SILENTLY when the source key is absent from
    ``MIN_RAW_FILE_SIZES`` -- a missing entry is a DISABLED floor, not an error -- so
    ``constants.MIN_RAW_FILE_SIZES['dce_daily'|'dce_history']`` is part of this producer, not
    decoration."""
    from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
    from leviathan.storage.s3 import upload_bytes_to_s3

    check_min_file_size(data, source_label, context=key)
    upload_bytes_to_s3(data, bucket, key, region)
    write_raw_s3_metadata(bucket, key, data, source_url, content_type, region)
    logger.info("raw written -> s3://%s/%s (%d bytes)", bucket, key, len(data))


def raw_exists(bucket: str, key: str, region: str) -> bool:
    from leviathan.storage.s3 import get_thread_local_s3_client
    try:
        get_thread_local_s3_client(region).head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001 -- any head failure means "treat as absent"
        return False


def resolve_varieties(selected: Optional[list[str]]) -> list[str]:
    """The varieties to walk, validated against the curated map. Fail-closed on an unknown letter."""
    if not selected:
        return sorted(DCE_VARIETY_MAP)
    unknown = sorted({v for v in selected if v not in DCE_VARIETY_MAP})
    if unknown:
        raise SystemExit(f"--variety {unknown} is not one of the five DCE varieties this leg keeps "
                         f"{sorted(DCE_VARIETY_MAP)}")
    return sorted(set(selected))


# ---------------------------------------------------------------------------
# --mode daily
# ---------------------------------------------------------------------------
def run_daily(session: BrowserSession, pending: list[tuple[str, str]], *, bucket: str,
              region: str, sleep_s: float) -> tuple[int, list[str], list[str]]:
    """Fetch + land each pending ``(variety, key)``. Returns ``(landed, not_ready, failed)``."""
    landed = 0
    not_ready: list[str] = []
    failed: list[str] = []
    for variety, key in pending:
        path = DAILY_PATH.format(variety=variety)
        url = session.url_for(path)
        try:
            body = session.fetch_text(path, accept="application/json")
            payload = body.encode("utf-8")
            records, _envelope = daily_records(payload)
            if daily_not_ready(records):
                # THE GUARD. Never write a board whose every settle is the 0.0 sentinel: the night
                # session serves exactly that shape with tradeDate ALREADY rolled to T+1.
                not_ready.append(variety)
                logger.warning("dce variety=%s: %d contract(s), every settlePrice is 0.0 -- the "
                               "board has NOT settled yet; skipping WITHOUT writing", variety,
                               len(records))
                continue
            land_bytes(bucket, key, payload, source_url=url, region=region,
                       source_label=_DAILY_SOURCE_LABEL, content_type=_DAILY_CONTENT_TYPE)
            landed += 1
        except ChallengeFailed:
            raise                              # the S2 answer travels all the way out
        except Exception as exc:  # noqa: BLE001 -- one variety's failure must not abort the rest
            logger.exception("FAILED dce daily variety=%s", variety)
            failed.append(f"{variety}: {type(exc).__name__}")
        finally:
            time.sleep(max(0.0, sleep_s))
    return landed, not_ready, failed


# ---------------------------------------------------------------------------
# --mode history
# ---------------------------------------------------------------------------
def looks_like_a_workbook(payload: bytes) -> Optional[str]:
    """None if the bytes are a plausible xlsx, else the reason they are not."""
    if not payload.startswith(_ZIP_MAGIC):
        return (f"the download is not a zip/xlsx container (first bytes "
                f"{ascii_safe(payload[:16])!r}) -- the venue served an error document")
    return None


def run_history(session: BrowserSession, pending: list[tuple[str, int, str]], *, bucket: str,
                region: str, sleep_s: float) -> tuple[int, list[str]]:
    """Download + land each pending ``(variety, year, key)``. Returns ``(landed, failed)``."""
    landed = 0
    failed: list[str] = []
    for variety, year, key in pending:
        path = HISTORY_PATH.format(year=year, variety=variety)
        url = session.url_for(path)
        try:
            payload = session.download(path)
            bad = looks_like_a_workbook(payload)
            if bad:
                raise ValueError(f"{url}: {bad}")
            land_bytes(bucket, key, payload, source_url=url, region=region,
                       source_label=_HISTORY_SOURCE_LABEL, content_type=_HISTORY_CONTENT_TYPE)
            landed += 1
        except ChallengeFailed:
            raise
        except Exception as exc:  # noqa: BLE001 -- one unit's failure must not abort the walk
            logger.exception("FAILED dce history variety=%s year=%s", variety, year)
            failed.append(f"{variety}/{year}: {type(exc).__name__}")
        finally:
            time.sleep(max(0.0, sleep_s))
    return landed, failed


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        stream=sys.stderr)
    load_env()
    ap = argparse.ArgumentParser(description="DCE quotes -> raw S3, via headless Chromium (W1c)")
    ap.add_argument("--mode", choices=["daily", "history"], default="daily")
    ap.add_argument("--as-of-date", default=None, dest="as_of_date",
                    help="daily: the CAPTURE date used in the raw key (default: today, UTC). The "
                         "SESSION date is read from the payload's own tradeDate by the transform")
    ap.add_argument("--variety", action="append", dest="varieties", default=None,
                    help=f"restrict to one variety (repeatable). Default: all of "
                         f"{sorted(DCE_VARIETY_MAP)}")
    ap.add_argument("--year-start", type=int, default=DCE_FIRST_HISTORY_YEAR, dest="year_start",
                    help="history: inclusive first year")
    ap.add_argument("--year-end", type=int, default=None, dest="year_end",
                    help="history: inclusive last year (default: the current UTC year)")
    ap.add_argument("--skip-existing", dest="skip_existing", action="store_true", default=True,
                    help="skip a unit whose raw object already exists -- the DEFAULT, and what "
                         "makes a resumed history walk cost only what it has not landed")
    ap.add_argument("--force", dest="skip_existing", action="store_false",
                    help="re-fetch and overwrite a unit whose raw object already exists")
    ap.add_argument("--sleep", type=float, default=_DEFAULT_SLEEP_SECONDS,
                    help="seconds between requests (politeness)")
    # Both spellings on both switches: an operator or a scheduler copying an invocation between the
    # three W1c jobs must not get an argparse error over a flag name.
    ap.add_argument("--headless", dest="headless", action="store_true", default=True,
                    help="(the default) run Chromium headless -- the mode probe S1 validated")
    ap.add_argument("--headful", "--headed", dest="headless", action="store_false",
                    help="debugging only: run Chromium with a visible window")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--aws-region", default=None, dest="aws_region")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and the keys; no browser, no HTTP, no writes")
    args = ap.parse_args(argv)

    varieties = resolve_varieties(args.varieties)
    as_of = args.as_of_date or _today_utc()
    year_end = args.year_end or datetime.now(tz=timezone.utc).year
    if args.mode == "history" and year_end < args.year_start:
        raise SystemExit(f"--year-end {year_end} is before --year-start {args.year_start}")

    if args.dry_run:
        print(f"mode      : {args.mode}")
        print(f"varieties : {','.join(varieties)}")
        if args.mode == "daily":
            print(f"as_of     : {as_of}")
            print(f"first url : {DCE_BASE_URL}{DAILY_PATH.format(variety=varieties[0])}")
            print(f"first key : {raw_dce_daily_key(varieties[0], as_of)}")
        else:
            print(f"years     : {args.year_start}..{year_end}")
            print(f"first url : {DCE_BASE_URL}"
                  f"{HISTORY_PATH.format(year=args.year_start, variety=varieties[0])}")
            print(f"first key : {raw_dce_history_key(varieties[0], args.year_start)}")
            print(f"units     : {len(varieties) * (year_end - args.year_start + 1)}")
        print("(dry-run -- no browser, no HTTP, no writes)")
        return 0

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    # The skip-existing pass runs BEFORE the browser is launched: a fully-landed window must not
    # pay for a Chromium start, and a resumed history walk should only open a session if it has
    # something to download.
    skipped = 0
    if args.mode == "daily":
        pending_daily: list[tuple[str, str]] = []
        for variety in varieties:
            key = raw_dce_daily_key(variety, as_of)
            if args.skip_existing and raw_exists(bucket, key, aws_region):
                skipped += 1
                continue
            pending_daily.append((variety, key))
        selected, pending = len(varieties), len(pending_daily)
    else:
        pending_history: list[tuple[str, int, str]] = []
        for variety in varieties:
            for year in range(args.year_start, year_end + 1):
                key = raw_dce_history_key(variety, year)
                if args.skip_existing and raw_exists(bucket, key, aws_region):
                    skipped += 1
                    continue
                pending_history.append((variety, year, key))
        selected = len(varieties) * (year_end - args.year_start + 1)
        pending = len(pending_history)

    logger.info("DCE %s: %d unit(s) selected, %d already landed, %d to fetch",
                args.mode, selected, skipped, pending)
    if not pending:
        logger.info("nothing to fetch -- every selected unit is already landed")
        return 0

    try:
        with BrowserSession(DCE_BASE_URL, headless=args.headless) as session:
            # The challenge dance. Everything below this line depends on it having settled, so it
            # is a hard gate rather than a best effort.
            session.goto_and_settle(SETTLE_PATH, ready_check=quote_api_ready(session),
                                    max_wait_s=_SETTLE_MAX_WAIT_S)
            if args.mode == "daily":
                landed, not_ready, failed = run_daily(
                    session, pending_daily, bucket=bucket, region=aws_region, sleep_s=args.sleep)
            else:
                landed, failed = run_history(
                    session, pending_history, bucket=bucket, region=aws_region, sleep_s=args.sleep)
                not_ready = []
    except ChallengeFailed as exc:
        return challenge_failed_exit("dce", exc)
    except NavigationFailed as exc:
        # NOT rc 7. The venue was never reached, so this run answered nothing about the challenge.
        return navigation_failed_exit("dce", exc)

    logger.info("DCE %s done: landed=%d skipped_existing=%d not_ready=%d failed=%d",
                args.mode, landed, skipped, len(not_ready), len(failed))
    if failed:
        logger.error("failed unit(s): %s", ", ".join(failed[:20]))
        return 1
    if not_ready and landed == 0:
        # Every variety this run was asked to capture is still unsettled. NOT a failure and NOT a
        # success: the run fired outside the settlement window and can be retried unchanged.
        logger.error("NOT_READY: all %d selected variety(ies) %s are unsettled -- nothing written. "
                     "Fire between 15:30 and 21:00 Beijing (07:30-13:00 UTC)",
                     len(not_ready), ",".join(not_ready))
        return EXIT_NOT_READY
    if not_ready:
        logger.warning("PARTIAL: %d variety(ies) %s were unsettled while %d landed -- re-run to "
                       "pick up the stragglers", len(not_ready), ",".join(not_ready), landed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
