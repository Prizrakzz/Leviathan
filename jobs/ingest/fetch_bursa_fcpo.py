#!/usr/bin/env python
"""PRICE_AND_PLAYBOOKS W1c / D2 -- the Bursa Malaysia FCPO producer (raw landing only).

SOURCE
------
    page: https://www.bursamalaysia.com/market_information/derivatives_prices
    api : /api/v1/derivatives_prices/derivatives_prices?code=FCPO&ses=day&per_page=50&page=1

THE REQUEST RECIPE
------------------
Cloudflare answers a plain request with **403 + ``Cf-Mitigated: challenge``** from BOTH a
residential and a Fargate IP (probed 2026-07-29) -- there is no UA or header trick that gets past
it, and the recon-era ``/market/derivatives/derivatives_prices`` path is a 404 besides. The
challenge CLEARS in headless Chromium with no Turnstile presented, so the recipe is: load the real
prices page, wait for the challenge to settle, then call the JSON API **in-page** so it carries the
session cookie.

WHAT LANDS, AND WHY IT IS A WRAPPER
-----------------------------------
The API body is 13 POSITIONAL elements per row with **no field names anywhere**. The only
self-description the venue publishes is the rendered table's ``thead``, so this producer scrapes it
and lands::

    {"thead": ["NO", "NAME", "MONTH", ...], "api": {"recordsTotal": 24, "data": [[...], ...]}}

That side channel is what lets the transform fail CLOSED on a column reordering per day (the JSE
header-pin precedent). Without it, a venue that inserts a column silently swaps HIGH for LOW and
publishes plausible wrong numbers that no row count can catch.

RAW FIDELITY, STATED PLAINLY: the body arrives through ``BrowserSession.fetch_json`` as a parsed
object, so the landed bytes are a canonical re-serialization of it rather than the wire bytes.
Values are preserved exactly (JSON round-trip); key order and whitespace are not.

``ses=day`` IS PINNED AND IS NOT A FLAG
---------------------------------------
The same URL shape serves ``day`` (T), ``night`` (T+1 after-hours) and ``all``. The night payload is
a COMPLETE, PLAUSIBLE 24-month table with different prices (Aug 2026 settles 4,557 against the day's
4,540) and the only discriminator in it is the NAME cell reading ``FCPO (T+1)``. An operator who
could pass ``--ses night`` could land after-hours prices under a day key, and nothing downstream
would know. So the session is a constant, the sniff below refuses a payload carrying the T+1 label,
and the transform refuses it a second time on the landed bytes.

THERE IS NO HISTORY. THE SERIES STARTS AT THE FIRST RUN
-------------------------------------------------------
The API serves current prices only -- no date parameter exists and the body carries no date field.
So this is a FORWARD-ACCUMULATION leg like the CEPEA daily widget: ``as_of_date`` is the trade date,
every missed session is permanently unrecoverable, and there is no backfill to run.
``as_of_date`` must be the MALAYSIAN calendar day of the T session; firing post-close
(>= 18:00 MYT == 10:00 UTC) makes the UTC default correct.

``--mode {incremental,backfill}`` exists for exactly one reason -- the JSE precedent, verbatim: so
that an operator or a scheduler copying the CZCE/MIAX/DCE invocation gets the plan's gate-8 error
instead of a silent no-op. There is still no backfill to run.

THE EXIT-CODE CONTRACT (this run IS the residual S2 probe)
----------------------------------------------------------
``ChallengeFailed`` exits ``EXIT_CHALLENGE_FAILED`` (7) with one ASCII log line. On this leg a 7 is
the real thing -- Cloudflare did not clear -- and the first Fargate run of this job is what answers
whether the challenge solves from a datacenter IP.

S3 LAYOUT
---------
    raw/production/source=bursa/code=FCPO/as_of_date={YYYY-MM-DD}/derivatives_day.json
    raw_meta/<that key>_meta.json      (sha256, size, the API URL)

Usage
-----
    python jobs/ingest/fetch_bursa_fcpo.py
    python jobs/ingest/fetch_bursa_fcpo.py --as-of-date 2026-07-29 --force
    python jobs/ingest/fetch_bursa_fcpo.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.storage.paths import BURSA_DAY_FILENAME, raw_bursa_key  # noqa: E402
from leviathan.transforms.raw_to_bronze.bursa_fcpo import (  # noqa: E402
    BURSA_CODE_MAP,
    BURSA_DAY_SESSION,
)

logger = get_logger("fetch_bursa_fcpo")

BURSA_BASE_URL = "https://www.bursamalaysia.com"
# The LIVE route. The recon-era /market/derivatives/derivatives_prices is a 404 and must not come
# back: a 404 behind a challenge reads exactly like a challenge failure.
BURSA_PRICES_PATH = "/market_information/derivatives_prices"
_API_PATH_FMT = ("/api/v1/derivatives_prices/derivatives_prices"
                 "?code={code}&ses={ses}&per_page={per_page}&page={page}")
_SOURCE_LABEL = "bursa"
_CONTENT_TYPE = "application/json"

# Mirrored from leviathan.ingest.browser_fetch; :func:`_browser` binds the two and fails on drift.
EXIT_CHALLENGE_FAILED = 7

# The challenge dance takes ~5-10 s of redirects. 90 s is the shared default: long enough that a
# timeout means "blocked", not "slow".
_DEFAULT_MAX_WAIT_S = 90
# 24 delivery months are listed; 50 covers the curve with room for the venue to extend it.
_PER_PAGE = 50
_PAGE = 1

# A real day payload carries the whole listed curve. This is a SHAPE sniff on the response, not a
# data floor -- the per-day silver row floor (plan gate 5) is counted in
# jobs/batch/futures_eod_task.py over SILVER rows.
_MIN_MONTHS = 8

# The Cloudflare interstitial's title, and the "we are through" test. Lowercased before matching.
_CHALLENGE_TITLES = ("just a moment", "attention required", "please wait", "checking your browser")

# The night session's label, verbatim from the NAME cell.
_NIGHT_LABEL = "(T+1)"

# PLAN GATE 8, the JSE precedent (jobs/ingest/fetch_jse_safex_daily.py). This leg is the identical
# case: a no-history source where an empty result would be indistinguishable from a public holiday.
_BACKFILL_MESSAGE = (
    "Bursa has no history; the series starts at the first run. The derivatives_prices API serves "
    "CURRENT prices only -- no date parameter exists on it and the body carries no date field -- so "
    "there is nothing to walk back to. Refusing to pretend otherwise: a backfill that quietly "
    "landed today's board under a past date would publish today's prices as that session's "
    "settlement"
)


def refuse_backfill() -> None:
    """PLAN GATE 8. Raised by any code path that asks this leg for history."""
    raise NotImplementedError(_BACKFILL_MESSAGE)


def api_path(code: str = "FCPO", *, ses: str = BURSA_DAY_SESSION,
             per_page: int = _PER_PAGE, page: int = _PAGE) -> str:
    """The in-page API path. ``ses`` defaults to the pinned day session and is never widened."""
    return _API_PATH_FMT.format(code=str(code).strip().upper(), ses=ses,
                                per_page=int(per_page), page=int(page))


def api_url(code: str = "FCPO") -> str:
    """The absolute API URL (recorded in raw_meta; the session fetches by path, in-page)."""
    return BURSA_BASE_URL + api_path(code)


def _api_probe_js(code: str) -> str:
    """An in-page ``fetch`` of the API that resolves to its HTTP status (0 on a network error).

    This is the SECOND half of the ready check and the load-bearing one: the Cloudflare
    interstitial swaps the title long before the cookie is usable, so "the title changed" alone
    lets the producer fire the API into a 403 and land a challenge body as prices."""
    return (
        "async () => { try { const r = await fetch('%s', {credentials: 'same-origin'});"
        " return r.status; } catch (e) { return 0; } }" % api_path(code)
    )


# The rendered header row, scraped for the transform's column pin. Prefers the thead that actually
# carries a settlement column, so a nav/footer table elsewhere on the page cannot be mistaken for it.
_THEAD_JS = """() => {
  const rows = Array.from(document.querySelectorAll('table thead tr')).map(
    tr => Array.from(tr.querySelectorAll('th,td')).map(
      c => (c.innerText || c.textContent || '').replace(/\\s+/g, ' ').trim()));
  const priced = rows.filter(
    r => r.length >= 10 && r.join(' ').toUpperCase().indexOf('SETT') >= 0);
  return priced[0] || rows[0] || [];
}"""


def _browser():
    """The shared browser module, imported LAZILY (playwright is not a laptop dependency; the
    parser tests import this module without it). The exit-code bind is asserted here."""
    from leviathan.ingest import browser_fetch

    if browser_fetch.EXIT_CHALLENGE_FAILED != EXIT_CHALLENGE_FAILED:
        raise RuntimeError(
            f"exit-code drift: browser_fetch.EXIT_CHALLENGE_FAILED is "
            f"{browser_fetch.EXIT_CHALLENGE_FAILED}, this producer mirrors {EXIT_CHALLENGE_FAILED}"
        )
    return browser_fetch


def is_challenge_title(title: Optional[str]) -> bool:
    """True while the page is still showing the Cloudflare interstitial (or has no title yet)."""
    token = " ".join(str(title or "").split()).strip().lower()
    if not token:
        return True
    return any(t in token for t in _CHALLENGE_TITLES)


def challenge_cleared(code: str = "FCPO"):
    """Build ``goto_and_settle``'s ready check for one product code.

    BOTH halves are required: the title must no longer be the interstitial AND an in-page fetch of
    the API must answer 200. The title flips first, so the API probe is what actually proves the
    session cookie is usable."""
    probe = _api_probe_js(code)

    def _ready(page) -> bool:
        try:
            if is_challenge_title(page.title()):
                return False
            return int(page.evaluate(probe) or 0) == 200
        except Exception:  # noqa: BLE001 -- a mid-navigation evaluate throws; that is "not yet"
            return False

    return _ready


def scrape_thead(session) -> list:
    """The rendered price table's header row, via the session's page escape hatch.

    A failure here is NOT fatal: the header is a column PIN, and losing it degrades the transform to
    "positional map assumed" (logged, and recorded in its stats) rather than losing the session's
    prices -- which, on a leg with no history, would be unrecoverable."""
    try:
        head = session.page.evaluate(_THEAD_JS)
    except Exception:  # noqa: BLE001
        logger.warning("bursa: could not scrape the rendered thead -- landing the body without the "
                       "column pin (the transform will log that the pin is unavailable)")
        return []
    return [str(c) for c in (head or [])]


def looks_like_a_day_payload(body, *, code: str) -> Optional[str]:
    """None if the API body is a plausible ``ses=day`` payload, else the reason it is not.

    Structural, never a parse -- all parsing authority stays in the transform. The T+1 test is here
    ANYWAY, and deliberately duplicated in the transform: landing a night body under a day key
    creates an object whose own name lies about it, on a leg that has no history to re-fetch from."""
    if not isinstance(body, dict):
        return f"the API returned {type(body).__name__}, not a JSON object"
    data = body.get("data")
    if not isinstance(data, list):
        return "the API body carries no 'data' array -- this is not a derivatives_prices response"
    if len(data) < _MIN_MONTHS:
        return (f"the API body carries {len(data)} row(s), expected >= {_MIN_MONTHS} -- the "
                f"delivery curve is truncated")
    declared = body.get("recordsTotal")
    if isinstance(declared, int) and declared != len(data):
        return (f"the body declares recordsTotal={declared} but carries {len(data)} row(s) -- the "
                f"response is paginated and delivery months are missing")
    blob = json.dumps(data)
    if _NIGHT_LABEL in blob:
        return (f"the payload's NAME cells carry {_NIGHT_LABEL!r} -- this is the AFTER-HOURS "
                f"session, not ses={BURSA_DAY_SESSION}. Refusing to land after-hours prices under "
                f"a day key")
    if str(code).strip().upper() not in blob.upper():
        return f"the payload carries no {code!r} instrument name -- the venue served another product"
    return None


def land_bytes(bucket: str, key: str, data: bytes, *, source_url: str, region: str) -> None:
    """Upload one raw artifact + its ``write_raw_s3_metadata`` companion, after the size floor.

    NOTE that ``check_min_file_size`` returns SILENTLY when the source key is absent from
    ``MIN_RAW_FILE_SIZES`` -- a missing entry is a DISABLED floor, not an error -- so
    ``constants.MIN_RAW_FILE_SIZES['bursa']`` is part of this producer, not decoration."""
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
    except Exception:  # noqa: BLE001 -- any head failure means "treat as absent"
        return False


def build_raw_object(thead: list, body: dict) -> bytes:
    """The landed wrapper: the rendered header side channel + the API body, UTF-8 JSON bytes."""
    return json.dumps({"thead": list(thead or []), "api": body},
                      ensure_ascii=False).encode("utf-8")


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        stream=sys.stderr)
    load_env()
    ap = argparse.ArgumentParser(
        description="Bursa Malaysia FCPO derivatives prices -> raw S3 (W1c browser leg)")
    # --mode exists ONLY so that an operator or a scheduler copying the CZCE/MIAX/DCE invocation
    # gets the plan's gate-8 error instead of a silent no-op. There is no backfill to run.
    ap.add_argument("--mode", choices=["incremental", "backfill"], default="incremental")
    ap.add_argument("--code", default="FCPO", choices=sorted(BURSA_CODE_MAP),
                    help="the venue's product selector value. Only FCPO is a CONTRACT_MAP slug "
                         "today; FPKO/FSOY/FEPO/FPOL are later legs")
    ap.add_argument("--as-of-date", "--as-of", default=None, dest="as_of",
                    help="the capture date used in the raw key AND as the trade date (default: "
                         "today, UTC). It must be the MALAYSIAN calendar day of the T session; the "
                         "API publishes no date of its own")
    # The flag SPELLINGS are the same across the three W1c producers on purpose -- see
    # fetch_dce_eod.py and fetch_euronext_eod.py. --force CLEARS skip-existing; it is not a second,
    # independent switch that has to be ANDed with it.
    ap.add_argument("--skip-existing", action="store_true", default=True, dest="skip_existing",
                    help="(the default) skip a capture that already exists; --force overrides")
    ap.add_argument("--force", dest="skip_existing", action="store_false",
                    help="re-fetch and overwrite an already-landed capture")
    ap.add_argument("--headless", action="store_true", default=True, dest="headless",
                    help="(the default) run Chromium headless -- the mode probe S1 validated")
    ap.add_argument("--headful", "--headed", action="store_false", dest="headless",
                    help="local debugging only; NEVER on Fargate")
    ap.add_argument("--max-wait-s", type=int, default=_DEFAULT_MAX_WAIT_S, dest="max_wait_s",
                    help="seconds to wait for the Cloudflare challenge to clear")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--aws-region", default=None, dest="aws_region")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the URLs and the key; no browser, no writes")
    # NOTE there is deliberately no --ses. See the module docstring.
    args = ap.parse_args(argv)

    if args.mode == "backfill":
        logger.error("%s", _BACKFILL_MESSAGE)
        refuse_backfill()

    code = str(args.code).strip().upper()
    as_of = args.as_of or datetime.now(tz=timezone.utc).date().isoformat()
    key = raw_bursa_key(code, as_of, BURSA_DAY_FILENAME)

    if args.dry_run:
        print(f"code   : {code}")
        print(f"as_of  : {as_of}")
        print(f"page   : {BURSA_BASE_URL + BURSA_PRICES_PATH}")
        print(f"api    : {api_url(code)}")
        print(f"key    : {key}")
        print("(dry-run -- no browser, no writes)")
        return 0

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    if args.skip_existing and raw_exists(bucket, key, aws_region):
        logger.info("bursa %s capture for %s already landed -- skipping (use --force to re-fetch)",
                    code, as_of)
        return 0

    bf = _browser()
    try:
        with bf.BrowserSession(BURSA_BASE_URL, headless=args.headless) as session:
            session.goto_and_settle(BURSA_PRICES_PATH,
                                    ready_check=challenge_cleared(code),
                                    max_wait_s=args.max_wait_s)
            body = session.fetch_json(api_path(code))
            # The header is scraped from the SAME settled page as the body, so the pin describes
            # the payload it shipped with rather than yesterday's layout.
            thead = scrape_thead(session)
    except bf.ChallengeFailed as exc:
        # THE RESIDUAL S2 PROBE. One ASCII line, one dedicated exit code.
        logger.error("CHALLENGE_FAILED bursa: Cloudflare did not clear within %ds (%s)",
                     args.max_wait_s, type(exc).__name__)
        return EXIT_CHALLENGE_FAILED
    except Exception:  # noqa: BLE001
        logger.exception("FAILED bursa %s capture for %s -- THIS SESSION IS UNRECOVERABLE (the API "
                         "serves current prices only and has no date parameter)", code, as_of)
        return 1

    try:
        bad = looks_like_a_day_payload(body, code=code)
        if bad:
            raise ValueError(f"{api_url(code)}: {bad}")
        land_bytes(bucket, key, build_raw_object(thead, body),
                   source_url=api_url(code), region=aws_region)
    except Exception:  # noqa: BLE001
        logger.exception("FAILED bursa %s capture for %s -- THIS SESSION IS UNRECOVERABLE (the API "
                         "serves current prices only and has no date parameter)", code, as_of)
        return 1
    logger.info("bursa %s capture %s landed (%d month(s), thead_cells=%d)",
                code, as_of, len(body.get("data") or []), len(thead))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
