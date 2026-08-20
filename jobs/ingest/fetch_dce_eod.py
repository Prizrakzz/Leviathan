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

THE EXISTENCE PROBE FAILS CLOSED, AND THIS PRODUCER HAS TWO DIFFERENT VERDICTS (2026-08-20)
--------------------------------------------------------------------------------------------
``raw_exists`` gates every PUT on this leg's raw data plane and it is called from BOTH mode
loops. The estate house idiom (``except Exception: return False``) answers "absent" to a throttle,
a 5xx, an expired token or a denied head, so a transient ``HeadObject`` failure makes the producer
believe a landed capture is missing and PUT over it. The recoverability answer differs by mode, and
both are recorded here rather than averaged into one:

  * ``--mode daily`` IS THE EEX ARGUMENT AT FULL STRENGTH. ``/quote/delay/futureData?variety={v}``
    takes NO date parameter -- it serves the CURRENT state of the board, which is exactly why the
    raw key is the CAPTURE date and the session date has to be read out of the payload's own
    ``tradeDate`` by the transform. There is no way to ask this endpoint for yesterday. A capture
    overwritten by a later render of the board is gone, and (worse, given the NOT_READY guard
    above) the later render may be the night session's T+1-dated all-zero board.
  * ``--mode history`` IS THE WEAKER CASE, and it is said honestly: the vendor workbooks are
    deterministic per ``(variety, year)`` and re-downloadable, so those bytes ARE re-derivable.
    What the swallow costs there is the resume contract in the paragraph above -- ~105 HEADs whose
    throttling silently turns "costs only what has not landed" into a full re-download walk behind
    a WAF that has to be re-cleared with Chromium each time.

So only a genuine 404 means absent; any other ``HeadObject`` error takes that UNIT out of the run
as a recorded failure and the run exits 1 -- never a silent skip, and never the "nothing to fetch"
exit 0 below (a run whose probes all threw proved nothing was landed, so reporting it as complete
would be the worst of the three outcomes). Exit 1 is Class D EXIT in
``infra/terraform/modules/batch/main.tf`` ``local.producer_retry_rules``, terminal after ONE
attempt -- no retry storm against a WAF-fronted venue.

**PINNED, because it changes who this fix protects:** ``--force`` sets ``skip_existing=False`` and
the call sites read ``if args.skip_existing and raw_exists(...)``, so under ``--force`` the probe is
NEVER CALLED -- Python short-circuits before it. The always-on lane
(``cursor/always_on/docker-compose.yml``, ``cursor/always_on/run_once_windows.py``) fires
``--mode daily --force`` and therefore never touches this path at all. The fix binds the
NON-force runs: the Batch/browser-runner submissions in ``cursor/DCE_BURSA_DAILY_ARM_PLAN.md`` and
every ``--mode history`` walk, all of which rely on the probe.

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

# The only S3 error codes that mean "this key is genuinely not there". Everything else raises --
# see raw_exists(). Mirrors fetch_eex_freight._ABSENT_ERROR_CODES.
_ABSENT_ERROR_CODES = frozenset({"404", "NotFound", "NoSuchKey"})

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
    """True when the object is already landed. **Only a genuine 404 means "absent".**

    THIS DIVERGES FROM THE ESTATE HOUSE IDIOM ON PURPOSE -- see the module docstring's two verdicts.
    ``except Exception: return False`` turns a throttle, a 5xx or an expired credential into
    "nothing is landed", which on ``--mode daily`` is a licence to PUT over a capture the venue
    cannot serve twice (the endpoint has no date parameter; it answers with the CURRENT board), and
    on ``--mode history`` silently voids the walk's resume contract.

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


def probe_landed(bucket: str, key: str, region: str, *, unit: str,
                 failures: list[str]) -> Optional[bool]:
    """``True`` already landed, ``False`` owed, **``None`` the probe could not answer**.

    The three-state answer is the whole point, and it is what both call sites below need:
    ``raw_exists`` now FAILS CLOSED, and an unanswerable probe must be read neither as "absent"
    (which is how the old swallow-all idiom destroyed captures -- the pending list leads straight
    to a fetch and a PUT with no second fence in front of it) nor as "already landed" (a silent
    skip). ``None`` means the unit is taken OUT of the run entirely: it is not fetched, nothing is
    written for it, its reason is recorded in *failures*, and ``main`` exits 1.
    """
    try:
        return raw_exists(bucket, key, region)
    except Exception as exc:  # noqa: BLE001 -- raw_exists fails CLOSED and may raise here
        logger.error(
            "dce %s: the raw existence probe could not answer (%s: %s) -- unit SKIPPED and the run "
            "marked failed. Refusing to capture: an unanswerable probe must never be read as "
            "'absent' and PUT over a landed capture", unit, type(exc).__name__, exc,
        )
        failures.append(f"{unit}: existence probe {type(exc).__name__}")
        return None


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
    # Units whose existence probe could not answer. NOT fetched, NOT written, and NOT allowed to
    # reach the "nothing to fetch" exit 0 below -- see probe_landed() and the module docstring.
    probe_failures: list[str] = []
    # NOTE --force sets skip_existing=False, so `and` short-circuits and raw_exists is never
    # called on a forced run at all. Pinned in the module docstring: this fix binds the non-force
    # invocations (the Batch submissions and every history walk), not the always-on --force lane.
    if args.mode == "daily":
        pending_daily: list[tuple[str, str]] = []
        for variety in varieties:
            key = raw_dce_daily_key(variety, as_of)
            landed_already = (probe_landed(bucket, key, aws_region, unit=variety,
                                           failures=probe_failures)
                              if args.skip_existing else False)
            if landed_already is None:
                continue                       # unanswerable -- taken out, never queued for a PUT
            if landed_already:
                skipped += 1
                continue
            pending_daily.append((variety, key))
        selected, pending = len(varieties), len(pending_daily)
    else:
        pending_history: list[tuple[str, int, str]] = []
        for variety in varieties:
            for year in range(args.year_start, year_end + 1):
                key = raw_dce_history_key(variety, year)
                landed_already = (probe_landed(bucket, key, aws_region, unit=f"{variety}/{year}",
                                               failures=probe_failures)
                                  if args.skip_existing else False)
                if landed_already is None:
                    continue                   # unanswerable -- taken out, never queued for a PUT
                if landed_already:
                    skipped += 1
                    continue
                pending_history.append((variety, year, key))
        selected = len(varieties) * (year_end - args.year_start + 1)
        pending = len(pending_history)

    logger.info("DCE %s: %d unit(s) selected, %d already landed, %d to fetch, %d unprobeable",
                args.mode, selected, skipped, pending, len(probe_failures))
    if not pending:
        if probe_failures:
            # NOT the "nothing to fetch" path. Nothing was PROVEN landed for these units, so exit 0
            # here would report a run that wrote nothing and could not even say why as a clean one
            # -- the exact fall-through the euronext fix found tonight.
            logger.error("DCE %s: nothing could be captured -- %d unit(s) failed their existence "
                         "probe: %s", args.mode, len(probe_failures),
                         ", ".join(probe_failures[:20]))
            return 1
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

    # The unprobeable units are failures of THIS run and are folded in BEFORE the exit decision, so
    # they take precedence over the NOT_READY branch: a run that could not read S3 must exit 1, not
    # the retryable 5, whatever the boards were doing.
    failed = list(failed) + probe_failures

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
