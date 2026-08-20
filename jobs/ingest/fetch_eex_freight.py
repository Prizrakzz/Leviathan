#!/usr/bin/env python
"""The EEX dry-bulk freight FORWARD-ONLY settlement accumulator (raw landing only).

SOURCE
------
    GET  https://api.eex-group.com/pub/market-data/chart/eod
    POST https://api.eex-group.com/pub/customise-widget/filter-data-with-scope

Unauthenticated, free, JSON. No API key, no .env secret, no browser -- the only credentials this
job needs are the AWS ones for the raw landing (``LEVIATHAN_BUCKET`` / ``AWS_REGION``, or
``--bucket`` / ``--aws-region``).

THE URGENCY IS THE DESIGN
-------------------------
The endpoint serves a **rolling ~5-trading-day window of settlement prices and nothing earlier.**
Measured live 2026-08-20: widening the request to ``startDate=2025-01-01&endDate=2026-08-21`` still
returns exactly five ``settlPx`` points (2026-08-13..2026-08-19), while the ``volume`` series of the
SAME response reaches ~33 sessions back. There is no history endpoint, no date-seek, no archive and
no vendor backfill under any licence the estate holds.

**Every day not fetched is gone forever.** So this producer's whole job is: run daily, capture the
window, land it immutably, and NEVER overwrite an existing ``(symbol, trade_date)`` observation.

  * ONE OBJECT PER (SYMBOL, SETTLEMENT DATE), holding that symbol's whole listed curve for that
    date -- not per capture date, which would re-key the same published settlement under five
    different names across five runs.
  * FIRST CAPTURE WINS. A settlement is published once. A re-served window is byte-compared against
    what is already landed; a difference is written to a ``_divergence/`` sibling and LOGGED, the
    first capture is kept untouched, and **the RUN then exits 2** so a scheduled fire surfaces the
    restatement instead of burying it in a warning nobody reads. **There is deliberately no
    ``--force``**: an overwrite flag on this leg is a PIT violation with no undo, because the bytes
    it destroys cannot be re-fetched.
  * The "is it already landed?" probe FAILS CLOSED. Only a genuine 404 counts as absent; any other
    ``HeadObject`` error aborts the run rather than risk PUTting over an unrecoverable first
    capture (see ``raw_exists`` -- this is a deliberate divergence from the estate house idiom).

EXIT CODES
----------
``0`` clean; ``1`` at least one symbol/date failed; ``2`` clean apart from a detected RESTATEMENT
(first capture kept, ``_divergence/`` record written). See the constants below.
  * The five-day window is also the resilience budget: up to FOUR consecutive missed runs are
    recoverable, the fifth is not.

WHAT IS FETCHED, AND THE TWO WRITTEN REFUSALS
----------------------------------------------
The instrument universe is ENUMERATED LIVE every run (``/filter-data-with-scope``), never read from
a hard-coded list -- a contract the venue lists tomorrow must be captured tomorrow, because a day
not fetched is unrecoverable. ``transforms.raw_to_bronze.eex_freight.MEASURED_FUTURES_SYMBOLS`` is
the 2026-08-20 census kept as a DRIFT DETECTOR, so an appearance or a unit re-base is said out loud.

Measured 2026-08-20 for ``commodity=FREIGHT``: 1,123 instruments across 23 products -- 16 futures
(``pricing=F``) and 7 options (``pricing=O``).

  * OPTIONS are refused HERE, at the fetch boundary (``REFUSED_PRICINGS``): a different endpoint
    (``/table-data-option``, strike-keyed) and a premium rather than a freight rate.
  * LNG ROUTE futures are FETCHED and refused in SILVER, in writing. Source fidelity wins at the raw
    layer precisely because there is no history endpoint: a scope decision enforced at the fetch
    would destroy the option of revisiting it, permanently.

Today that is 16 symbols and, filtering out expired maturities, ~790 ``/chart/eod`` calls per run
(~682 of them dry bulk) at a 1.1 s sleep -- roughly 15 minutes, single-threaded.

BE POLITE, AND NEVER THREADED
-----------------------------
One shared ``requests.Session``, one request at a time, ``--sleep`` >= 1.0 s between every call.
This is a venue's public widget API, not a CDN; concurrency buys nothing and risks the 403 that
would cost a day. The three headers below are MANDATORY -- probed 2026-08-20, a call without
``Referer`` returns 403.

EXPIRED MATURITIES
------------------
The scope endpoint keeps listing maturities after they expire, and ``/chart/eod`` answers 200 with an
all-null envelope and empty series for them (verified: P5TC ``maturity=202607`` on 2026-08-20). They
are filtered out by ``--lookback-months`` (default 1) rather than probed. The honest limitation this
leaves, recorded rather than hidden: because the venue drops a contract's WHOLE series at expiry, an
expiring contract's final settlements must be captured on the day -- a look-back cannot recover them.

Usage
-----
    python jobs/ingest/fetch_eex_freight.py --dry-run
    python jobs/ingest/fetch_eex_freight.py
    python jobs/ingest/fetch_eex_freight.py --symbol P5TC --symbol S11F
    python jobs/ingest/fetch_eex_freight.py --skip-existing
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.storage.paths import (  # noqa: E402
    raw_eex_freight_divergence_key,
    raw_eex_freight_key,
)
from leviathan.transforms.raw_to_bronze.eex_freight import (  # noqa: E402
    COMMODITY_FREIGHT,
    EEX_FREIGHT_SOURCE,
    MEASURED_FUTURES_SYMBOLS,
    PRICING_FUTURE,
    REFUSED_PRICINGS,
    SETTLEMENT_WINDOW_TRADING_DAYS,
    build_observation,
    canonical_observation_bytes,
    is_dry_bulk,
    settlement_dates,
)

logger = get_logger("fetch_eex_freight")

# ---------------------------------------------------------------------------
# The request recipe
# ---------------------------------------------------------------------------
API_BASE = "https://api.eex-group.com/pub/market-data"
SCOPE_URL = "https://api.eex-group.com/pub/customise-widget/filter-data-with-scope"
EOD_PATH = "/chart/eod"

# MANDATORY, all three. Probed live 2026-08-20: the widget's own calls carry Origin + Referer and a
# call WITHOUT Referer returns 403. The UA is a browser UA for the same reason ams.usda.gov needs one
# -- the crawler UA is what gets refused, not the client.
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Origin": "https://www.eex.com",
    "Referer": "https://www.eex.com/",
    "Accept": "application/json, text/plain, */*",
}

# A venue widget API, not a CDN. Sequential, never threaded; see the module docstring.
_DEFAULT_SLEEP_S = 1.1
_MIN_SLEEP_S = 1.0
_TIMEOUT_S = 60

# The request window. The endpoint only ever answers with its rolling ~5-trading-day settlement
# window, so a generous calendar span costs nothing and absorbs holiday runs.
_DEFAULT_WINDOW_DAYS = 21

_CONTENT_TYPE = "application/json"

# The only S3 error codes that mean "this key is genuinely not there". Everything else raises --
# see raw_exists().
_ABSENT_ERROR_CODES = frozenset({"404", "NotFound", "NoSuchKey"})

# EXIT CODES (documented here because a schedule reads them, not a human).
#   0  clean run
#   1  at least one symbol/date FAILED (fetch, build or landing) -- Class D, terminal
#   2  the run is otherwise clean but the venue RESTATED an already-landed settlement.
#      The first capture was kept and a _divergence/ sibling was written; this code exists so a
#      scheduled fire surfaces the restatement instead of burying it in a WARNING. It is terminal
#      after ONE attempt under the estate's producer retry matrix -- exit 2 with an absent container
#      reason falls to the mandatory terminal `on_reason = "*"` EXIT rule, live-probed on job
#      cb151695 (infra/terraform/modules/batch/main.tf, DSG-TAIL F1) -- so it never re-runs and
#      never lands a second divergence record for the same restatement.
EXIT_OK = 0
EXIT_FAILURES = 1
EXIT_DIVERGENCE = 2


def scope_blob(commodity: str = COMMODITY_FREIGHT) -> str:
    """The base64 ``data`` parameter ``/filter-data-with-scope`` expects.

    The widget builds it as ``btoa(JSON.stringify(contracts))`` where ``contracts`` is a list of
    ``{commodity, pricing, area, product, productSpecific, maturityType}`` selectors and ``"All"``
    is the wildcard. Key order is the widget's own, kept so the request is byte-comparable with the
    one that was probed."""
    contracts = [{"commodity": commodity, "pricing": "All", "area": "All",
                  "product": "All", "productSpecific": "All", "maturityType": "All"}]
    return base64.b64encode(json.dumps(contracts).encode("utf-8")).decode("ascii")


class _Client:
    """One session, one request at a time, a sleep before every call but the first."""

    def __init__(self, sleep_s: float = _DEFAULT_SLEEP_S) -> None:
        if sleep_s < _MIN_SLEEP_S:
            raise ValueError(
                f"--sleep {sleep_s} is below the {_MIN_SLEEP_S}s floor. This is a venue's public "
                f"widget API; a faster loop buys nothing and risks the 403 that costs a day"
            )
        self.sleep_s = float(sleep_s)
        self.session = requests.Session()
        self.calls = 0

    def _pace(self) -> None:
        if self.calls:
            time.sleep(self.sleep_s)
        self.calls += 1

    def get_json(self, path: str, params: dict) -> dict:
        self._pace()
        resp = self.session.get(API_BASE + path, params=params, headers=_HEADERS,
                                timeout=_TIMEOUT_S)
        resp.raise_for_status()
        return resp.json()

    def post_scope(self, encoded: str) -> dict:
        self._pace()
        resp = self.session.post(SCOPE_URL, params={"data": encoded}, data={"data": encoded},
                                 headers=_HEADERS, timeout=_TIMEOUT_S)
        # The scope endpoint answers 201 Created for this POST-as-query idiom, not 200.
        if resp.status_code not in (200, 201):
            resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Universe enumeration
# ---------------------------------------------------------------------------
def parse_scope(payload: dict) -> list[dict]:
    """The scope endpoint's ``{header, data}`` table -> a list of instrument records.

    PURE, so the shape is testable without the network. The response is column-oriented (a header
    list plus positional rows), and the header is read BY NAME rather than by position -- a venue
    that inserts a column must not shift ``shortCode`` into ``maturity``.
    """
    header = list(payload.get("header") or [])
    rows = list(payload.get("data") or [])
    required = ("shortCode", "maturity", "maturityType", "commodity", "pricing", "area",
                "product", "productSpecific")
    missing = [name for name in required if name not in header]
    if missing:
        raise ValueError(
            f"eex freight: the scope response header is missing {missing}. Header seen: {header}. "
            f"Refusing to read the rows positionally -- an off-by-one here silently re-labels every "
            f"instrument"
        )
    idx = {name: header.index(name) for name in required}
    out: list[dict] = []
    for row in rows:
        if len(row) != len(header):
            raise ValueError(
                f"eex freight: a scope row has {len(row)} cell(s), expected {len(header)}"
            )
        out.append({
            "symbol": str(row[idx["shortCode"]] or "").strip().upper(),
            "maturity": str(row[idx["maturity"]] or "").strip(),
            "maturity_type": str(row[idx["maturityType"]] or "").strip(),
            "commodity": str(row[idx["commodity"]] or "").strip(),
            "pricing": str(row[idx["pricing"]] or "").strip(),
            "area": str(row[idx["area"]] or "").strip(),
            "product": str(row[idx["product"]] or "").strip(),
            "route": str(row[idx["productSpecific"]] or "").strip(),
        })
    return out


def min_maturity(reference: date, lookback_months: int) -> str:
    """The oldest ``YYYYMM`` worth requesting: ``reference``'s month minus ``lookback_months``.

    The look-back exists for the window that straddles a month end, not as a recovery mechanism --
    see the module docstring's note on expired maturities.
    """
    months = reference.year * 12 + (reference.month - 1) - int(lookback_months)
    return f"{months // 12:04d}{months % 12 + 1:02d}"


def probe_maturity(maturities: list[str], *, current_month: str) -> str:
    """The maturity ``--skip-existing`` should probe: the front month that has NOT expired.

    PURE. Why this is not simply ``maturities[0]``: the scope endpoint keeps listing maturities
    after they expire, ``--lookback-months`` defaults to 1 so the floor sits one month BELOW the
    run's month, and ``/chart/eod`` answers an expired maturity with an all-null envelope and an
    empty series. Probing that maturity therefore yields no settlement dates at all, the caller's
    "are they all landed?" test is vacuously false, and the flag falls through to the full fetch --
    plus one wasted call per symbol. Measured on the checked-in 2026-08-20 scope capture: under the
    DEFAULT arguments ``maturities[0]`` is the expired 202607 on 16 of 16 symbols, so the flag was
    inert exactly as shipped and only did what it advertises with ``--lookback-months 0``.

    The front LIVE month is the right probe rather than the last: it is the most heavily quoted
    contract on the board and the one certain to carry the window's settlements. If every listed
    maturity is below ``current_month`` -- the whole symbol has rolled off -- the newest listed one
    is probed instead, so the question asked is at least a real one.
    """
    live = [m for m in maturities if m >= current_month]
    return live[0] if live else maturities[-1]


def select_instruments(records: list[dict], *, floor: str,
                       symbols: Optional[list[str]] = None) -> dict[str, dict]:
    """Group the enumerated universe into ``{symbol: {spec, maturities}}``, futures only.

    PURE. Applies, in order: the ``commodity=FREIGHT`` scope, the ``pricing`` refusals (options), the
    expired-maturity floor, and an optional explicit ``--symbol`` filter. Anything dropped is dropped
    for a reason this function can name.
    """
    wanted = {s.strip().upper() for s in symbols} if symbols else None
    grouped: dict[str, dict] = {}
    refused_pricing: dict[str, int] = {}
    for rec in records:
        if rec["commodity"] != COMMODITY_FREIGHT:
            continue
        if rec["pricing"] in REFUSED_PRICINGS:
            refused_pricing[rec["pricing"]] = refused_pricing.get(rec["pricing"], 0) + 1
            continue
        if rec["pricing"] != PRICING_FUTURE:
            logger.warning(
                "eex freight UNIVERSE DRIFT: pricing %r is neither the futures book %r nor a "
                "written refusal %s (symbol %s). Skipped -- classify it",
                rec["pricing"], PRICING_FUTURE, sorted(REFUSED_PRICINGS), rec["symbol"],
            )
            continue
        if wanted is not None and rec["symbol"] not in wanted:
            continue
        if rec["maturity"] < floor:
            continue
        slot = grouped.setdefault(rec["symbol"], {
            "spec": {k: rec[k] for k in ("commodity", "pricing", "area", "product", "route")},
            "maturities": [],
        })
        slot["maturities"].append(rec["maturity"])
    for symbol, slot in grouped.items():
        slot["maturities"] = sorted(set(slot["maturities"]))
    for pricing, count in sorted(refused_pricing.items()):
        logger.info("eex freight: REFUSED %d instrument(s) at pricing=%s -- %s",
                    count, pricing, REFUSED_PRICINGS[pricing])
    if wanted is not None:
        for symbol in sorted(wanted - set(grouped)):
            logger.warning("eex freight: --symbol %s matched no live futures instrument", symbol)
    return grouped


# ---------------------------------------------------------------------------
# S3 landing
# ---------------------------------------------------------------------------
def raw_exists(bucket: str, key: str, region: str) -> bool:
    """True when the object is already landed. **Only a genuine 404 means "absent".**

    THIS DIVERGES FROM THE ESTATE HOUSE IDIOM ON PURPOSE. The shared shape
    (``fetch_euronext_eod.py``, ``fetch_bursa_fcpo.py``, ``fetch_moex_agro_indices.py``,
    ``fetch_cepea_daily.py``) swallows EVERY exception and answers ``False``, so a transient
    ``HeadObject`` failure -- a throttle, a 5xx, an expired credential -- makes the caller believe a
    landed first capture is absent and PUT over it. On every one of those legs the destroyed bytes
    can be re-fetched. On THIS leg they cannot: the venue serves a rolling ~5-trading-day settlement
    window and no history, which is the same argument that gives this producer no ``--force``.

    So a head failure that is not a 404 RAISES. Aborting the run is strictly cheaper than
    overwriting an unrecoverable first capture: the window still holds four more days of recovery
    budget, while the destroyed bytes are gone at any price. Fail closed.
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
    for this source. ``build_observation`` has already proven the document carries at least one real
    settlement, which is a STRICTLY STRONGER integrity check than any byte count -- and a byte floor
    here would refuse a legitimately thin curve (a newly listed contract with three maturities lands
    at a few hundred bytes). That is the ESR 1499/MY2001 lesson: the mis-inferred-floor class.
    """
    from leviathan.storage.raw_metadata import write_raw_s3_metadata
    from leviathan.storage.s3 import upload_bytes_to_s3

    upload_bytes_to_s3(data, bucket, key, region)
    write_raw_s3_metadata(bucket, key, data, source_url, _CONTENT_TYPE, region, extra=extra)
    logger.info("raw written -> s3://%s/%s (%d bytes)", bucket, key, len(data))


def divergence_record(symbol: str, trade_date: str, landed: bytes, served: bytes,
                      capture_stamp: str, source_url: str) -> bytes:
    """The document written when a re-served window disagrees with the landed first capture.

    It holds BOTH readings in full plus a maturity-level diff, so the disagreement can be
    adjudicated later from the record alone. The first capture is never touched.
    """
    def _parse(blob: bytes) -> dict:
        try:
            return json.loads(blob.decode("utf-8"))
        except Exception:  # noqa: BLE001 -- an unparseable landed object is itself the finding
            return {}

    first, second = _parse(landed), _parse(served)
    by_first = {str(s.get("maturity")): s for s in (first.get("settlements") or [])}
    by_second = {str(s.get("maturity")): s for s in (second.get("settlements") or [])}
    changed = [
        {"maturity": m, "first_capture": by_first.get(m), "re_served": by_second.get(m)}
        for m in sorted(set(by_first) | set(by_second))
        if by_first.get(m) != by_second.get(m)
    ]
    return json.dumps({
        "schema": "eex_freight_divergence/v1",
        "source": EEX_FREIGHT_SOURCE,
        "symbol": symbol,
        "trade_date": trade_date,
        "observed_at_utc": capture_stamp,
        "source_url": source_url,
        "resolution": "kept-as-first",
        "first_capture_bytes": len(landed),
        "re_served_bytes": len(served),
        "changed_maturities": changed,
        "first_capture": first,
        "re_served": second,
    }, indent=2, sort_keys=True).encode("utf-8")


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------
def eod_params(spec: dict, symbol: str, maturity: str, start: str, end: str) -> dict:
    """The ``/chart/eod`` query for one (symbol, maturity). Every field is the venue's own scope
    vocabulary, taken from the enumeration rather than assumed."""
    return {
        "commodity": spec["commodity"],
        "pricing": spec["pricing"],
        "area": spec["area"],
        "product": spec["product"],
        "maturity": maturity,
        "startDate": start,
        "endDate": end,
        "shortCode": symbol,
    }


def eod_url(spec: dict, symbol: str, maturity: str, start: str, end: str) -> str:
    """The absolute, fully-parameterised request URL -- recorded in ``raw_meta`` for provenance."""
    from urllib.parse import urlencode
    return f"{API_BASE}{EOD_PATH}?{urlencode(eod_params(spec, symbol, maturity, start, end))}"


def fetch_symbol(client: _Client, symbol: str, slot: dict, start: str,
                 end: str) -> dict[str, dict]:
    """Every live maturity of ONE symbol -> ``{maturity: chart/eod payload}``.

    An individual maturity that errors is logged and skipped rather than aborting the symbol: on a
    source where a missed day is unrecoverable, losing one back month must never cost the front."""
    spec = slot["spec"]
    out: dict[str, dict] = {}
    for maturity in slot["maturities"]:
        try:
            payload = client.get_json(EOD_PATH, eod_params(spec, symbol, maturity, start, end))
        except Exception as exc:  # noqa: BLE001 -- one maturity must not abort the symbol
            logger.error("eex freight %s %s: fetch failed -- %s: %s",
                         symbol, maturity, type(exc).__name__, exc)
            continue
        if settlement_dates(payload):
            out[maturity] = payload
        else:
            logger.debug("eex freight %s %s: no settlements served (expired or not yet listed)",
                         symbol, maturity)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        stream=sys.stderr)
    load_env()
    today = datetime.now(tz=timezone.utc).date()

    ap = argparse.ArgumentParser(
        description=("EEX dry-bulk freight settlements -> raw S3. FORWARD-ONLY: the source serves a "
                     "rolling ~5-trading-day settlement window and no history, so a day not fetched "
                     "is gone forever. First capture always wins."))
    ap.add_argument("--symbol", action="append", dest="symbols", default=None, metavar="CODE",
                    help=("repeatable; restrict to these EEX short codes (default: every freight "
                          f"FUTURE the scope endpoint enumerates -- {len(MEASURED_FUTURES_SYMBOLS)} "
                          "on 2026-08-20)"))
    ap.add_argument("--end-date", default=None, metavar="YYYY-MM-DD",
                    help=f"last date of the request window (default: today UTC = {today})")
    ap.add_argument("--window-days", type=int, default=_DEFAULT_WINDOW_DAYS, metavar="N",
                    help=(f"calendar days of request window (default {_DEFAULT_WINDOW_DAYS}). The "
                          f"venue answers with its rolling ~{SETTLEMENT_WINDOW_TRADING_DAYS}-"
                          "trading-day settlement window regardless, so a wide span is free and "
                          "absorbs holidays"))
    ap.add_argument("--lookback-months", type=int, default=1, metavar="N",
                    help=("skip maturities older than N months before the end date (default 1). "
                          "Expired contracts are still LISTED by the scope endpoint but answer with "
                          "an empty series"))
    ap.add_argument("--skip-existing", action="store_true",
                    help=("cheap re-run: probe the FRONT LIVE maturity of each symbol (never an "
                          "expired one -- see probe_maturity) and skip the symbol entirely when "
                          "every settlement date in the window is already landed. Works under the "
                          "default arguments. NOTE this also skips the first-capture-wins byte "
                          "comparison for that symbol -- the default (full fetch) is what enforces "
                          "it, so a restatement can only be DETECTED by a full run"))
    ap.add_argument("--sleep", type=float, default=_DEFAULT_SLEEP_S, metavar="SECONDS",
                    help=f"pause between every request (default {_DEFAULT_SLEEP_S}; floor "
                         f"{_MIN_SLEEP_S}). Never threaded")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--aws-region", default=None, dest="aws_region")
    ap.add_argument("--dry-run", action="store_true",
                    help=("enumerate the live universe (ONE read-only POST) and print the exact "
                          "request plan and raw keys. No /chart/eod calls, no S3 writes"))
    args = ap.parse_args(argv)

    end = args.end_date or today.isoformat()
    try:
        end_date = date.fromisoformat(end)
    except ValueError:
        raise SystemExit(f"--end-date {end!r} is not YYYY-MM-DD")
    start = (end_date - timedelta(days=max(1, int(args.window_days)))).isoformat()
    floor = min_maturity(end_date, args.lookback_months)
    # The run's own month. The maturity FLOOR may sit below it (--lookback-months exists for a
    # window that straddles a month end), but a --skip-existing probe must never be aimed there.
    current_month = min_maturity(end_date, 0)

    try:
        client = _Client(sleep_s=args.sleep)
    except ValueError as exc:
        raise SystemExit(str(exc))

    logger.info("eex freight: enumerating the live %s universe (scope endpoint)", COMMODITY_FREIGHT)
    records = parse_scope(client.post_scope(scope_blob()))
    grouped = select_instruments(records, floor=floor, symbols=args.symbols)
    if not grouped:
        logger.error("eex freight: the scope endpoint enumerated no live freight future at all "
                     "(records=%d, maturity floor=%s)", len(records), floor)
        return 1

    planned = sum(len(slot["maturities"]) for slot in grouped.values())
    logger.info("eex freight: %d symbol(s), %d live maturity(ies), window %s..%s (floor %s)",
                len(grouped), planned, start, end, floor)
    for symbol in sorted(grouped):
        slot = grouped[symbol]
        if symbol not in MEASURED_FUTURES_SYMBOLS:
            logger.warning("eex freight UNIVERSE DRIFT: %s (%s / %s) is a NEW short code -- "
                           "capturing it and re-pin MEASURED_FUTURES_SYMBOLS", symbol,
                           slot["spec"]["product"], slot["spec"]["route"])

    if args.dry_run:
        print(f"window     : {start} .. {end}   (maturity floor {floor})")
        print(f"symbols    : {len(grouped)}   maturities: {planned}   "
              f"est. /chart/eod calls: {planned}   est. wall time: "
              f"{planned * args.sleep / 60.0:.1f} min at --sleep {args.sleep}")
        for symbol in sorted(grouped):
            slot = grouped[symbol]
            spec = slot["spec"]
            mats = slot["maturities"]
            tag = "dry-bulk" if is_dry_bulk(spec["product"]) else "NOT dry bulk (silver refuses it)"
            print(f"  {symbol}  {spec['product']} {spec['route']}  "
                  f"{len(mats)} maturities {mats[0]}..{mats[-1]}  [{tag}]")
            print(f"    GET {eod_url(spec, symbol, mats[0], start, end)}")
            template = raw_eex_freight_key(symbol, end).replace(f"trade_date={end}",
                                                               "trade_date={SETTLEMENT_DATE}")
            print(f"    -> {template}")
            print("       (one such key per settlement date the window actually serves -- the "
                  "dates come from the payload, never from the clock)")
            print(f"    --skip-existing would probe maturity "
                  f"{probe_maturity(mats, current_month=current_month)} "
                  f"(the front LIVE month; mats[0]={mats[0]} may be expired and answer empty)")
        print("(dry-run -- no /chart/eod calls, no S3 writes)")
        return 0

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    capture_stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    landed = skipped_identical = skipped_symbol = diverged = 0
    failures: list[str] = []

    for symbol in sorted(grouped):
        slot = grouped[symbol]
        spec = slot["spec"]
        mats = slot["maturities"]

        # The cheap re-run path: one probe tells us which settlement dates the window holds.
        # The probe maturity is the front LIVE month, never mats[0] -- under the default
        # --lookback-months the first listed maturity is an EXPIRED contract that answers empty,
        # which made this flag inert. See probe_maturity().
        if args.skip_existing:
            pm = probe_maturity(mats, current_month=current_month)
            probe = client.get_json(EOD_PATH, eod_params(spec, symbol, pm, start, end))
            dates = settlement_dates(probe)
            if not dates:
                logger.warning(
                    "eex freight %s: the --skip-existing probe on maturity %s served no "
                    "settlement at all -- falling through to the full fetch rather than "
                    "guessing the symbol is complete", symbol, pm,
                )
            try:
                complete = bool(dates) and all(
                    raw_exists(bucket, raw_eex_freight_key(symbol, d), aws_region) for d in dates
                )
            except Exception as exc:  # noqa: BLE001 -- raw_exists fails CLOSED and may raise here
                # An existence probe that cannot answer must never be read as "already landed"
                # (which would skip the symbol) nor as "absent" (which is how the old swallow-all
                # raw_exists destroyed first captures). Fall through to the full fetch, where the
                # per-date guard makes the same failure a recorded, non-overwriting failure.
                logger.error(
                    "eex freight %s: --skip-existing could not probe S3 (%s: %s) -- taking the "
                    "full fetch path, which fails closed per date", symbol,
                    type(exc).__name__, exc,
                )
                complete = False
            if complete:
                logger.info("eex freight %s: all %d window date(s) %s..%s already landed -- symbol "
                            "skipped (the byte comparison is skipped with it)",
                            symbol, len(dates), dates[0], dates[-1])
                skipped_symbol += 1
                continue

        per_maturity = fetch_symbol(client, symbol, slot, start, end)
        if not per_maturity:
            logger.error("eex freight %s: not one live maturity served a settlement in %s..%s",
                         symbol, start, end)
            failures.append(f"{symbol}: empty window")
            continue

        dates = sorted({d for payload in per_maturity.values() for d in settlement_dates(payload)})
        for trade_date in dates:
            try:
                document = build_observation(symbol=symbol, trade_date=trade_date, spec=spec,
                                             per_maturity=per_maturity)
                served = canonical_observation_bytes(document)
                key = raw_eex_freight_key(symbol, trade_date)
                url = eod_url(spec, symbol, mats[0], start, end)

                if raw_exists(bucket, key, aws_region):
                    stored = raw_read(bucket, key, aws_region)
                    if stored == served:
                        skipped_identical += 1
                        logger.debug("eex freight %s %s: re-served window byte-identical to the "
                                     "first capture", symbol, trade_date)
                        continue
                    # FIRST CAPTURE WINS. Never overwrite; record the disagreement beside it.
                    dkey = raw_eex_freight_divergence_key(symbol, trade_date, capture_stamp)
                    land_bytes(bucket, dkey,
                               divergence_record(symbol, trade_date, stored, served,
                                                 capture_stamp, url),
                               source_url=url, region=aws_region,
                               extra={"note": "eex freight re-served window differed from the "
                                              "first capture; first capture KEPT"})
                    logger.warning(
                        "eex freight DIVERGENCE %s %s: the re-served window differs from the landed "
                        "first capture (%d vs %d bytes). First capture KEPT; the disagreement is "
                        "recorded at s3://%s/%s",
                        symbol, trade_date, len(stored), len(served), bucket, dkey,
                    )
                    diverged += 1
                    continue

                land_bytes(bucket, key, served, source_url=url, region=aws_region,
                           extra={
                               "eex_endpoint": f"{API_BASE}{EOD_PATH}",
                               "eex_symbol": symbol,
                               "eex_product": spec["product"],
                               "eex_route": spec["route"],
                               "eex_maturities_requested": len(mats),
                               "eex_maturities_settled": len(document["settlements"]),
                               "eex_request_window": f"{start}..{end}",
                               "eex_currency": document["currency"],
                               "eex_uom": document["uom"],
                               "capture_stamp_utc": capture_stamp,
                               "licence_note": ("EEX Group DataSource General Conditions govern "
                                                "redistribution; this is the venue's own public "
                                                "widget API. Internal signal use only until the GC "
                                                "clauses are read (recon 1d-iv, PARKED-FOR-HOME)"),
                           })
                landed += 1
            except Exception as exc:  # noqa: BLE001 -- one date must not abort the symbol
                logger.exception("FAILED eex freight %s %s", symbol, trade_date)
                failures.append(f"{symbol} {trade_date}: {type(exc).__name__}")

    logger.info(
        "eex freight done: landed=%d identical=%d diverged=%d symbols_skipped=%d failed=%d "
        "(%d HTTP call(s))",
        landed, skipped_identical, diverged, skipped_symbol, len(failures), client.calls,
    )
    if failures:
        logger.error("failed: %s", "; ".join(failures))
        return EXIT_FAILURES
    if diverged:
        # A divergence is the most interesting event this job can observe: the venue RESTATED a
        # settlement that is already landed. The first capture is kept and the disagreement is on
        # disk, but a WARNING in a Batch log is not a control -- it needs a human to go looking.
        # Exiting nonzero makes the scheduled fire itself carry the news.
        logger.error(
            "eex freight: %d RESTATED settlement(s) detected. The first capture was kept in every "
            "case and the disagreement is recorded under the _divergence/ prefix; exiting %d so "
            "this run is not read as clean. Adjudicate the record, then re-run if warranted",
            diverged, EXIT_DIVERGENCE,
        )
        return EXIT_DIVERGENCE
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
