#!/usr/bin/env python
"""MOEX AGRO INDICES -- the Russian grain indicative-price producer (raw landing only).

SOURCE
------
    GET https://iss.moex.com/iss/history/engines/stock/markets/index/securities/{SECID}.json
        ?from=YYYY-MM-DD&till=YYYY-MM-DD[&start=N]

Unauthenticated, free, JSON. No API key, no .env secret, no browser -- the only credentials this job
needs are the AWS ones for the raw landing (``LEVIATHAN_BUCKET`` / ``AWS_REGION``, or ``--bucket`` /
``--aws-region``).

*** THIS FETCHER RUNS IN THE CLOUD. IT CANNOT RUN ON THE LAPTOP. ***
---------------------------------------------------------------------
``iss.moex.com`` IS REACHABLE ONLY FROM AWS. Probed 2026-08-20 from both ends of the estate: the
laptop gets ``http=000`` (the connection never completes), an AWS-side probe job gets ``200``. This
is the same selective-blocking class as ``mcx.gov.ru`` and ``www.moex.com`` in the Black Sea recon
(section 2) -- not a general Russia-wide failure, since ``nfa.ru`` answers from the same laptop.

Consequences, and they are not negotiable:

  * EVERY real run of this producer is CLOUD-SIDE (Batch / Fargate). There is no laptop fallback and
    there is no proxy work-around -- the standing rule is "network-blocked source = park for home,
    never work around", and here the cloud IS the reachable end, so the leg is scheduled rather than
    parked.
  * On the laptop this job supports ``--dry-run`` and NOTHING else. A real local invocation will
    fail at the first request with a connection error, which is honest but wastes a run; the
    ``--dry-run`` path makes no request at all and prints the exact plan.
  * The worker image must be REBUILT to include this file before any cloud invocation. A jobdef
    pointing at an image built before this commit will exit with "No such file or directory" --
    that is the smoke-exact-command law's whole point, and the prepared commands below say so.

THE DUTY ROUTE -- WHY THIS FAMILY EXISTS
-----------------------------------------
Russia's floating wheat export duty is computed from an indicative price derived from export
contracts registered on the Moscow Exchange, and the Ministry publishes the weekly rate on a page
this estate cannot reach at all (``mcx.gov.ru``, PARKED-FOR-HOME). Every reachable mirror of the
rate is licensing-fouled. MOEX publishes the INPUT openly, so this family takes the input series and
DOCUMENTS the derivation without computing it -- see the duty note in
``transforms/bronze_to_silver/moex_agro_indices.py`` and FOLLOW-UP MOEX-DUTY-1.

S3 LAYOUT -- ONE IMMUTABLE OBJECT PER (SECID, TRADEDATE)
---------------------------------------------------------
    raw/production/source=moex_agro_indices/secid={SECID}/trade_date={YYYY-MM-DD}/row.json
    raw_meta/<that key>_meta.json    (sha256, size, request URL, capture UTC)

``trade_date`` is the row's OWN ``TRADEDATE``, published inside the payload -- never the fetch date.
That is what makes re-running free: the same window re-derives the same keys, and

FIRST CAPTURE WINS. A settled index level is published once. ISS *does* serve history (unlike the
EEX freight leg), so a missed day is recoverable -- but a re-served row still never overwrites the
landed one. A byte difference between the landed capture and a re-served row is LOGGED as a
divergence finding, and the first capture is kept. There is deliberately NO ``--force``: an
overwrite flag on an immutable raw layer is a PIT violation with no undo, and the correct repair for
a genuinely bad object is a deliberate delete-and-refetch by an operator, not a flag.

**AND THE EXISTENCE PROBE OBEYS THAT SAME LAW (verdict 2026-08-20).** The EEX unrecoverability
argument does NOT apply to this family -- ISS serves history and a lost row is re-fetchable -- so
the case here is the paragraph above, not that one. ``raw_exists`` gates both the ``--skip-existing-s3``
short-circuit AND the first-capture-wins byte comparison, i.e. the only PUT on this leg's data
plane. The estate house idiom (``except Exception: return False``) answers "absent" to a throttle,
a 5xx, an expired token or a denied head, which is precisely the overwrite this family refuses to
give an operator a FLAG for -- granted silently, at random, by S3 weather. It is worse than a
``--force``: it also fires when the landed and re-served bytes DIFFER, so it converts a divergence
finding into a quiet overwrite of the evidence. A leg that writes "no --force because an overwrite
on immutable raw is a PIT violation" and then swallows head failures contradicts its own law. So
only a genuine 404 means absent; any other ``HeadObject`` error raises and fails that
``(secid, trade_date)`` loudly through the per-date guard in :func:`run` (exit 1).

This producer is AWS-only-reachable, so the narrowing was NOT live-tested: it is the
``fetch_eex_freight.raw_exists`` shape verbatim, covered by unit tests only.

THE DORMANT INDEX IS NOT AN ERROR
----------------------------------
``WH4CPTNOV`` served ZERO history rows for August 2026. An empty ISS history is a NORMAL answer on
this family -- a dormant security, a window with no sessions, a request before a security's
inception -- and it is handled as DATA: zero rows landed, one written log line naming the secid and
the window, exit 0. It stays in the default universe because an index that starts printing must be
captured on the day it does.

BE POLITE, AND NEVER THREADED
------------------------------
One shared ``requests.Session``, one request at a time, ``--sleep`` >= 1.0 s between every call.
This is an exchange's public data API, not a CDN. A full 2015-2026 backfill of five securities is
roughly 5 x 27 pages ~= 135 requests at the assumed 100-row page -- under three minutes, and there
is no reason to go faster.

PAGING
------
Standard ISS paging: the response carries a ``history.cursor`` block, and a page that does not reach
``TOTAL`` is followed by ``&start=INDEX+PAGESIZE``. The walk in
``transforms.raw_to_bronze.moex_agro_indices.iter_pages`` uses the cursor when ISS serves a usable
one and falls back to advancing by the ROW COUNT it actually received otherwise, stopping on the
first empty page -- so a cursor that is absent, renamed or re-shaped costs one extra request and
never a row.

Usage
-----
    python jobs/ingest/fetch_moex_agro_indices.py --mode backfill --from 2015-01-01 --dry-run
    python jobs/ingest/fetch_moex_agro_indices.py --mode backfill --from 2015-01-01 --secids WHFOB
    python jobs/ingest/fetch_moex_agro_indices.py --mode daily
    python jobs/ingest/fetch_moex_agro_indices.py --mode daily --skip-existing-s3

PREPARED COMMANDS (cloud-side; NOT armed in this wave)
-------------------------------------------------------
No jobdef and no schedule is created here. The submit shapes, the smoke-exact-command law and the
image precondition are recorded in the wave report rather than fired, under the four-checkmark law:
no numbers card exists for this family and none may be minted before proof-of-rows.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.storage.paths import raw_moex_agro_indices_key  # noqa: E402
from leviathan.transforms.raw_to_bronze.moex_agro_indices import (  # noqa: E402
    ASSUMED_PAGE_SIZE,
    DORMANT_SECIDS,
    ISS_BASE,
    ISS_HISTORY_PATH,
    MEASURED_SECURITIES,
    MOEX_AGRO_INDICES_SOURCE,
    canonical_observation_bytes,
    iter_pages,
    observations_from_rows,
)

logger = get_logger("fetch_moex_agro_indices")

# ---------------------------------------------------------------------------
# The request recipe
# ---------------------------------------------------------------------------
# ISS answers a plain client; no Origin/Referer dance is needed (unlike EEX). A named UA is sent as
# ordinary courtesy so the venue can identify the traffic.
_HEADERS = {
    "User-Agent": "leviathan-ingest/1.0 (commodity research; contact via repository)",
    "Accept": "application/json",
}

# An exchange's public data API, not a CDN. Sequential, never threaded.
_DEFAULT_SLEEP_S = 1.1
_MIN_SLEEP_S = 1.0
_TIMEOUT_S = 60

_CONTENT_TYPE = "application/json"

# The only S3 error codes that mean "this key is genuinely not there". Everything else raises --
# see raw_exists(). Mirrors fetch_eex_freight._ABSENT_ERROR_CODES.
_ABSENT_ERROR_CODES = frozenset({"404", "NotFound", "NoSuchKey"})

# The whole measured universe, in a stable order.
DEFAULT_SECIDS: list[str] = sorted(MEASURED_SECURITIES)

# The daily arm's default look-back. Wide enough to absorb a long weekend, a Russian public holiday
# run and one missed fire; first-capture-wins makes re-offering old days free, so the only cost of a
# generous window is a few requests.
_DEFAULT_DAILY_LOOKBACK_DAYS = 10

# The backfill's default floor. INCEPTION DATES ARE UNKNOWN for every one of these securities -- the
# recon never established when MOEX first published them -- so the backfill asks for a window that
# certainly precedes them and relies on EMPTY-WINDOW HONESTY: ISS answers a pre-inception window
# with zero rows, which this producer reports as zero rows rather than as a failure. A guessed
# inception date would silently truncate the series; an over-wide window costs a few requests.
DEFAULT_BACKFILL_FROM = "2015-01-01"


class MoexClient:
    """One session, one request at a time, a sleep before every call but the first.

    Constructed with an explicit ``sleep_s`` floor so a future operator cannot quietly turn this
    into a hammer. The tests substitute their own object with the same ``get_json`` signature, which
    is why the walk in ``iter_pages`` takes a callable rather than this class.
    """

    def __init__(self, sleep_s: float = _DEFAULT_SLEEP_S) -> None:
        if sleep_s < _MIN_SLEEP_S:
            raise ValueError(
                f"--sleep {sleep_s} is below the {_MIN_SLEEP_S}s floor. This is an exchange's "
                f"public data API; a faster loop buys nothing and risks a block on the ONE route "
                f"this estate has to the Russian indicative price"
            )
        self.sleep_s = float(sleep_s)
        self.session = requests.Session()
        self.calls = 0

    def _pace(self) -> None:
        if self.calls:
            time.sleep(self.sleep_s)
        self.calls += 1

    def get_json(self, url: str, params: dict) -> dict:
        self._pace()
        resp = self.session.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT_S)
        resp.raise_for_status()
        return resp.json()


def history_url(secid: str) -> str:
    """The absolute ISS history URL for one security."""
    return ISS_BASE + ISS_HISTORY_PATH.format(secid=str(secid).strip().upper())


def history_params(date_from: str, date_till: str, start: Optional[int] = None) -> dict:
    """The ISS query for one page. ``start`` is omitted on the first page, as the venue expects."""
    params: dict = {"from": date_from, "till": date_till}
    if start:
        params["start"] = int(start)
    return params


def request_url(secid: str, date_from: str, date_till: str, start: Optional[int] = None) -> str:
    """The fully-parameterised request URL -- recorded in ``raw_meta`` for provenance."""
    return f"{history_url(secid)}?{urlencode(history_params(date_from, date_till, start))}"


# ---------------------------------------------------------------------------
# S3 landing
# ---------------------------------------------------------------------------
def raw_exists(bucket: str, key: str, region: str) -> bool:
    """True when the object is already landed. **Only a genuine 404 means "absent".**

    THIS DIVERGES FROM THE ESTATE HOUSE IDIOM ON PURPOSE -- see the module docstring's verdict.
    ``except Exception: return False`` turns a throttle, a 5xx or an expired credential into
    "nothing is landed", which hands the caller exactly the overwrite this family refuses to give
    an operator a ``--force`` for -- and does it silently, and does it even when the landed bytes
    and the re-served bytes DIFFER, which is the case the divergence log exists to surface.

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


def raw_read(bucket: str, key: str, region: str) -> bytes:
    from leviathan.storage.s3 import get_thread_local_s3_client, s3_download_with_retry
    return s3_download_with_retry(bucket, key, get_thread_local_s3_client(region))


def land_bytes(bucket: str, key: str, data: bytes, *, source_url: str, region: str,
               extra: Optional[dict] = None) -> None:
    """Upload one raw artifact + its ``write_raw_s3_metadata`` companion.

    NOTE there is deliberately NO ``check_min_file_size`` call and no ``MIN_RAW_FILE_SIZES`` entry
    for this source. ``build_observation`` has already proven the document carries a real published
    level, which is a STRICTLY STRONGER integrity check than any byte count -- and a byte floor here
    would refuse a legitimately small object (one index row is a few hundred bytes). That is the ESR
    1499/MY2001 lesson: the mis-inferred-floor class.
    """
    from leviathan.storage.raw_metadata import write_raw_s3_metadata
    from leviathan.storage.s3 import upload_bytes_to_s3

    upload_bytes_to_s3(data, bucket, key, region)
    write_raw_s3_metadata(bucket, key, data, source_url, _CONTENT_TYPE, region, extra=extra)
    logger.info("raw written -> s3://%s/%s (%d bytes)", bucket, key, len(data))


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------
def fetch_secid_rows(client, secid: str, date_from: str, date_till: str) -> list[dict]:
    """Every ``history`` row ISS serves for one security in one window, across all pages.

    Returns ``[]`` for a dormant security or an empty window -- see the module docstring; that is
    data, not a failure.
    """
    url = history_url(secid)

    def fetch_page(start: int):
        return client.get_json(url, history_params(date_from, date_till, start))

    return iter_pages(fetch_page, secid=secid)


def run(
    *,
    client,
    secids: list[str],
    date_from: str,
    date_till: str,
    bucket: str,
    region: str,
    skip_existing: bool,
    mode: str,
) -> int:
    """Fetch, land and report. Returns the process exit code.

    One secid failing does not abort the others: this leg's whole value is a long continuous series
    per index, and losing WHCPT because CRFOB 500'd would be a self-inflicted gap.
    """
    landed = skipped_existing = identical = diverged = 0
    empty_secids: list[str] = []
    failures: list[str] = []

    for secid in secids:
        try:
            rows = fetch_secid_rows(client, secid, date_from, date_till)
        except Exception as exc:  # noqa: BLE001 -- one secid must not abort the run
            logger.exception("FAILED moex %s: history walk", secid)
            failures.append(f"{secid}: {type(exc).__name__}: {exc}")
            continue

        if not rows:
            # A WRITTEN LOG LINE, and exit 0. A dormant security, a pre-inception window and a
            # holiday week all land here and all three are data. Silence would be indistinguishable
            # from a leg that never ran.
            dormant = " (known DORMANT as of 2026-08-20)" if secid in DORMANT_SECIDS else ""
            logger.info(
                "moex %s: ISS served ZERO history rows for %s..%s%s -- nothing landed, and this is "
                "DATA rather than a failure. An empty window is the venue's honest answer for a "
                "dormant security, a pre-inception window or a period with no sessions",
                secid, date_from, date_till, dormant,
            )
            empty_secids.append(secid)
            continue

        try:
            observations = observations_from_rows(rows, secid=secid)
        except ValueError as exc:
            logger.error("FAILED moex %s: %s", secid, exc)
            failures.append(f"{secid}: {exc}")
            continue

        logger.info("moex %s: %d row(s) served for %s..%s (%d landable)",
                    secid, len(rows), date_from, date_till, len(observations))

        for document in observations:
            trade_date = document["trade_date"]
            key = raw_moex_agro_indices_key(secid, trade_date)
            # BOTH raw_exists CALL SITES ON THIS LEG SIT INSIDE THIS GUARD, and that is load-bearing
            # rather than incidental: raw_exists fails CLOSED and RAISES on any head failure that is
            # not a 404, so the guard is what turns an unanswerable probe into a recorded, non-
            # overwriting per-date FAILURE (exit 1) instead of an aborted secid. Do not narrow the
            # `except Exception` below to the transform's ValueError -- that would let a throttled
            # head take the whole run down, and worse, moving either call OUT of the guard would put
            # an unfenced probe in front of the PUT.
            try:
                if skip_existing and raw_exists(bucket, key, region):
                    skipped_existing += 1
                    continue

                served = canonical_observation_bytes(document)
                if raw_exists(bucket, key, region):
                    stored = raw_read(bucket, key, region)
                    if stored == served:
                        identical += 1
                        continue
                    # FIRST CAPTURE WINS. Never overwrite. MOEX does not restate a settled level, so
                    # a difference is a FINDING -- recorded loudly, adjudicated by a human, never
                    # resolved by whichever run happened to be last.
                    diverged += 1
                    logger.warning(
                        "moex DIVERGENCE %s %s: the re-served row differs from the landed first "
                        "capture (%d vs %d bytes). FIRST CAPTURE KEPT. MOEX does not restate a "
                        "settled index level, so this is a finding: landed=%s served=%s",
                        secid, trade_date, len(stored), len(served),
                        _summary(stored), _summary(served),
                    )
                    continue

                land_bytes(
                    bucket, key, served,
                    source_url=request_url(secid, date_from, date_till),
                    region=region,
                    extra={
                        "source": MOEX_AGRO_INDICES_SOURCE,
                        "moex_secid": secid,
                        "moex_board": document["board"],
                        "moex_currency": document["currency"],
                        "moex_trade_date": trade_date,
                        "moex_request_window": f"{date_from}..{date_till}",
                        "moex_mode": mode,
                        "capture_timestamp_utc": datetime.now(tz=timezone.utc).isoformat(
                            timespec="seconds"),
                        "reachability_note": (
                            "iss.moex.com answers from AWS only (laptop http=000, AWS 200, probed "
                            "2026-08-20). This object was landed cloud-side"),
                        "licence_note": (
                            "MOEX ISS is the exchange's own public API. Redistribution terms were "
                            "NOT established in this wave -- treat as fetchable for internal signal "
                            "and read the ISS terms before any external publication"),
                    },
                )
                landed += 1
            except Exception as exc:  # noqa: BLE001 -- one date must not abort the secid
                logger.exception("FAILED moex %s %s", secid, trade_date)
                failures.append(f"{secid} {trade_date}: {type(exc).__name__}")

    logger.info(
        "moex done: landed=%d skipped_existing=%d identical=%d diverged=%d empty_secids=%s "
        "failed=%d (%d HTTP call(s))",
        landed, skipped_existing, identical, diverged, empty_secids or "none", len(failures),
        getattr(client, "calls", -1),
    )
    if failures:
        logger.error("failed: %s", "; ".join(failures))
        return 1
    return 0


def _summary(blob: bytes) -> str:
    """A one-line ASCII digest of a landed/served object, for the divergence log line."""
    try:
        doc = json.loads(blob.decode("utf-8"))
    except Exception:  # noqa: BLE001 -- an unparseable object is itself the finding
        return f"<unparseable {len(blob)} bytes>"
    return (f"close={doc.get('close')} currency={doc.get('currency')!r} "
            f"board={doc.get('board')!r}")


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        stream=sys.stderr)
    today = datetime.now(tz=timezone.utc).date()

    ap = argparse.ArgumentParser(
        description=("MOEX agro indices (WHFOB/BRFOB/CRFOB/WHCPT/WH4CPTNOV) -> raw S3. The Russian "
                     "grain indicative-price route. iss.moex.com is reachable ONLY from AWS: every "
                     "real run is cloud-side and the laptop gets --dry-run."))
    ap.add_argument("--mode", choices=["backfill", "daily"], required=True,
                    help=("backfill: one wide window per secid, from --from to --till. "
                          "daily: a rolling look-back window ending today UTC."))
    ap.add_argument("--secids", nargs="+", default=DEFAULT_SECIDS, metavar="SECID",
                    help=(f"MOEX security ids to fetch (default: the whole measured universe, "
                          f"{' '.join(DEFAULT_SECIDS)})."))
    ap.add_argument("--from", dest="date_from", default=None, metavar="YYYY-MM-DD",
                    help=(f"first trade date of the request window. backfill default "
                          f"{DEFAULT_BACKFILL_FROM} -- INCEPTION DATES ARE UNKNOWN, so the backfill "
                          f"asks for a window that certainly precedes them and relies on ISS "
                          f"answering a pre-inception window with zero rows (empty-window honesty). "
                          f"daily default: {_DEFAULT_DAILY_LOOKBACK_DAYS} days before --till"))
    ap.add_argument("--till", dest="date_till", default=None, metavar="YYYY-MM-DD",
                    help=f"last trade date of the request window (default: today UTC = {today})")
    ap.add_argument("--lookback-days", type=int, default=_DEFAULT_DAILY_LOOKBACK_DAYS, metavar="N",
                    help=(f"daily mode only: days of look-back before --till (default "
                          f"{_DEFAULT_DAILY_LOOKBACK_DAYS}). First capture wins, so re-offering "
                          "already-landed days is free and the window absorbs missed fires"))
    ap.add_argument("--skip-existing-s3", action="store_true", dest="skip_existing",
                    help=("skip the fetch-side comparison for a (secid, trade_date) already in S3. "
                          "NOTE this also skips the first-capture-wins byte comparison for that "
                          "key -- the default (compare) is what enforces it"))
    ap.add_argument("--sleep", type=float, default=_DEFAULT_SLEEP_S, metavar="SECONDS",
                    help=f"pause between every request (default {_DEFAULT_SLEEP_S}; floor "
                         f"{_MIN_SLEEP_S}). Never threaded")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--aws-region", default=None, dest="aws_region")
    ap.add_argument("--dry-run", action="store_true",
                    help=("print the exact request plan and key shapes. NO HTTP call and NO S3 "
                          "write -- this is the ONLY mode that works on the laptop, because "
                          "iss.moex.com does not answer from here"))
    args = ap.parse_args(argv)

    date_till = args.date_till or today.isoformat()
    try:
        till = date.fromisoformat(date_till)
    except ValueError:
        raise SystemExit(f"--till {date_till!r} is not YYYY-MM-DD")

    if args.date_from:
        date_from = args.date_from
    elif args.mode == "backfill":
        date_from = DEFAULT_BACKFILL_FROM
    else:
        date_from = (till - timedelta(days=max(1, int(args.lookback_days)))).isoformat()
    try:
        start_day = date.fromisoformat(date_from)
    except ValueError:
        raise SystemExit(f"--from {date_from!r} is not YYYY-MM-DD")
    if start_day > till:
        raise SystemExit(f"--from {date_from} is after --till {date_till}")

    secids = [s.strip().upper() for s in args.secids if str(s).strip()]
    if not secids:
        raise SystemExit("--secids resolved to an empty list")
    for secid in secids:
        if secid not in MEASURED_SECURITIES:
            logger.warning(
                "moex UNIVERSE DRIFT: %s is not one of the five securities measured 2026-08-20 "
                "(%s). Fetching it anyway -- a new listing must be captured, not refused",
                secid, " ".join(DEFAULT_SECIDS),
            )

    span_days = (till - start_day).days + 1
    est_pages = max(1, -(-span_days * 5 // 7 // ASSUMED_PAGE_SIZE))  # ~5 sessions per 7 days

    if args.dry_run:
        print(f"mode       : {args.mode}")
        print(f"window     : {date_from} .. {date_till}   ({span_days} calendar days)")
        print(f"secids     : {len(secids)}   {' '.join(secids)}")
        print(f"est. pages : ~{est_pages} per secid at the assumed {ASSUMED_PAGE_SIZE}-row ISS page "
              f"(~{est_pages * len(secids)} requests, "
              f"~{est_pages * len(secids) * args.sleep / 60.0:.1f} min at --sleep {args.sleep})")
        for secid in secids:
            spec = MEASURED_SECURITIES.get(secid, {})
            tag = "DORMANT 2026-08-20" if secid in DORMANT_SECIDS else (
                f"{spec.get('board') or '?'} / {spec.get('currency') or '?'}")
            print(f"  {secid}  [{tag}]")
            print(f"    GET {request_url(secid, date_from, date_till)}")
            template = raw_moex_agro_indices_key(secid, date_till).replace(
                f"trade_date={date_till}", "trade_date={TRADEDATE}")
            print(f"    -> {template}")
        print("       (one such key per TRADEDATE the window actually serves -- the dates come from")
        print("        the payload, never from the clock; first capture wins and there is no --force)")
        print("(dry-run -- no HTTP calls, no S3 writes. NOTE iss.moex.com answers from AWS ONLY;")
        print(" a real run of this producer must happen cloud-side.)")
        return 0

    load_env()
    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    logger.info(
        "moex %s: %d secid(s) %s, window %s..%s. iss.moex.com is AWS-REACHABLE ONLY -- if this run "
        "is on a laptop it will fail at the first request, by design",
        args.mode, len(secids), " ".join(secids), date_from, date_till,
    )

    try:
        client = MoexClient(sleep_s=args.sleep)
    except ValueError as exc:
        raise SystemExit(str(exc))

    return run(
        client=client,
        secids=secids,
        date_from=date_from,
        date_till=date_till,
        bucket=bucket,
        region=aws_region,
        skip_existing=args.skip_existing,
        mode=args.mode,
    )


if __name__ == "__main__":
    raise SystemExit(main())
