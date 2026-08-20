#!/usr/bin/env python
"""PRICE_AND_PLAYBOOKS W1a / D1 -- the CEPEA daily cash-reference producer (raw landing only).

SOURCE
------
    https://www.cepea.org.br/br/widgetproduto.js.php?...&id_indicador%5B%5D={ID}

with **arabica id 23** and **Campinas corn id 77** (the ESALQ/BM&FBovespa maize indicator IS the
Campinas reference). The widget returns the LAST published value only -- one dated row, no series,
no US$ column.

THREE REQUEST FACTS, ALL PROBED, NONE OPTIONAL
----------------------------------------------
1. **A browser ``User-Agent`` is MANDATORY.** Re-probed 2026-07-28 and again 2026-07-29: the
   default ``python-requests/2.x`` UA gets **Cloudflare HTTP 403** (a ``cdn-cgi/content`` challenge
   body) on BOTH ids; a Chrome UA returns 200. ``Referer`` and ``Accept-Language`` make no
   difference -- **the UA alone is the gate**, and this is a static UA filter, not a JS challenge
   (which is exactly what separates CEPEA from Bursa, whose ``Cf-Mitigated: challenge`` Turnstile
   interstitial no header permutation clears). :data:`CEPEA_USER_AGENT` is pinned here for that
   reason and must not be "cleaned up".
2. **A 403 is a HARD FAILURE, never an empty result.** This table has no freshness alarm armed yet,
   so a producer that swallowed a challenge body and wrote nothing would be silent for as long as
   nobody looked.
3. **The host is load-bearing: ``www.cepea.org.br``.** The ``cepea.esalq.usp.br`` host 301s to it
   and the redirect DOUBLE-ENCODES the ``[]`` in the query (``%255B%255D``), which silently yields
   "Sem resultados" -- a 200 with no data. The host is hard-coded; never follow the other one.

Also probed: the ``.aspx`` series pages are Cloudflare-403 to plain requests, to a FULL Chrome
header set, and via WebFetch. **Only ``.php`` is open.** History therefore comes from the archive
one-shot (``fetch_cepea_wayback_history.py``), not from here.

RATE LIMIT
----------
The origin resets the connection after ~4 rapid requests. Spacing is **>= 2.5 s** (the
``fetch_sagis_cec.py`` 1.0 s discipline, widened to what was measured). Two ids per run makes this
one sleep, so it costs nothing.

CADENCE AND THE HOLIDAY CASE
----------------------------
Daily, ~18:00 America/Sao_Paulo. On a Brazilian holiday (Carnival is the named risk) the widget
keeps serving the PREVIOUS session's value -- so the capture date and the value's own date are
different facts. This job lands the capture under ``as_of_date=``; the transform reads the value's
date out of the payload and the silver leg dedupes identical values, so a holiday re-serve becomes
a no-op rather than a stale duplicate row.

THE SERVED-DATE VERDICT (D-PR-19)
---------------------------------
**Measured, 2026-07-29:** a MANUAL 17:00Z run -- 14:00 BRT, ~4 h before publication -- landed a
payload whose own date was ``28/07/2026``. The transform did not lie (silver holds 07-28), but
session 2026-07-29 was never captured by anything, and both CEPEA slugs are missing it to this day
while every other business day in that week is present. Nothing detected it: the per-day floor is
an equality on rows PRESENT, a stale re-serve collapses in the silver dedupe, and the day still
showed exactly 2 rows.

So every capture now asserts the session it is serving BEFORE anything is written:

  * the served date is read out of the payload (``served_date_from_widget``), the same cell the
    transform turns into ``trade_date``;
  * it is classified against the EXPECTED session (``fresh`` / ``stale_reserve`` /
    ``ahead_of_session``);
  * ``served_date``, ``served_lag_business_days`` and ``served_verdict`` ride into ``raw_meta``
    alongside the licence, so a landed object states what it is.

**The decision is taken over ALL indicators at once, and it is BOTH OR NEITHER.** The per-day
silver floor for this leg is an EQUALITY (``== 2``, one row per cash reference), so withholding one
indicator while landing the other would turn a clean day into a floor violation -- the withhold
must never be able to manufacture a 1-row day.

**Why withholding a stale re-serve is safe and is the point.** A stale payload carries a session
that is already landed; the silver dedupe collapses it to nothing, so refusing it loses exactly
zero data. What it BUYS is the thing the 07-29 hole turned on: :func:`raw_exists` short-circuits on
the CAPTURE-date key, so once a pre-publication payload is landed, the 22:30Z scheduled fire finds
the key present and does nothing at all. Withholding leaves no key -- and the scheduled fire lands
the real session. On the 07-29 sequence this job would have written nothing at 17:00Z and captured
2026-07-29 at 22:30Z.

A holiday takes the same withhold path (no new session exists, so nothing is owed) and exits 0 with
a declaration in the log, NOT a failure: a hard-fail on ``served != capture`` would red roughly ten
Brazilian holidays a year, which is the trade this wave exists to refuse. ``--on-stale land``
restores the pure land-and-declare behaviour if the declaration alone is ever wanted.

THE EXISTENCE PROBE FAILS CLOSED (verdict 2026-08-20)
-----------------------------------------------------
``raw_exists`` gates the only PUT on this leg's raw data plane, and the estate house idiom
(``except Exception: return False``) answers "absent" to a throttle, a 5xx, an expired token or a
denied head -- so a transient S3 failure would make the producer believe a landed capture is
missing and PUT over it.

**Is what the capture holds re-derivable? NO -- and this is the EEX argument, not a weakened one.**
The value's own series is published on CEPEA's ``.aspx`` pages, which serve an interactive
Turnstile challenge to plain ``requests``, to a full Chrome header set and via WebFetch; that route
is closed BY POLICY and not by capability, permanently (see ``fetch_cepea_wayback_history.py``).
The ``.php`` widget this producer reads serves the LAST published value only -- no series, no date
parameter. The only history that exists in the estate is a pair of 2017 Wayback snapshots landed by
a one-shot, with an accepted ~9-year hole to the daily leg's first run on 2026-07-28 that no
republisher can fill (IPEADATA swept: 3,585 series, zero CEPEA/ESALQ). So a destroyed daily capture
cannot be re-fetched from anywhere at any price.

And even where a VALUE happened to be re-derivable, an overwrite is still a PIT event: the raw
object's ``raw_meta`` vintage -- sha256, size, capture instant, and the D-PR-19 ``served_date`` /
``served_verdict`` / ``served_lag_business_days`` declaration -- describes THE CAPTURE, not the
number, and cannot be re-created by a later fetch.

So only a genuine 404 means absent. Any other ``HeadObject`` error takes the WHOLE RUN out (exit 1,
nothing written) rather than one indicator: the landing decision here is a group decision and the
per-day silver floor is an EQUALITY, so an unanswerable probe on one indicator must never leave the
other free to manufacture a 1-row day.

S3 LAYOUT
---------
    raw/production/source=cepea/indicator={23|77}/as_of_date={YYYY-MM-DD}/widget.js
    raw_meta/<that key>_meta.json   (licence + attribution + the served-date declaration)

Usage
-----
    python jobs/ingest/fetch_cepea_daily.py
    python jobs/ingest/fetch_cepea_daily.py --indicator 23 --dry-run
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests  # noqa: E402
from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.storage.paths import raw_cepea_widget_key  # noqa: E402
from leviathan.transforms.raw_to_bronze.cepea import (  # noqa: E402
    CEPEA_ATTRIBUTION,
    CEPEA_INDICATORS,
    CEPEA_LICENSE,
    SERVED_AHEAD,
    SERVED_FRESH,
    SERVED_STALE,
    classify_served_date,
    previous_business_day,
    served_date_from_widget,
    session_for_capture,
)

logger = get_logger("fetch_cepea_daily")

# THE HOST IS PART OF THE CONTRACT. See the module docstring -- the esalq.usp.br host's 301
# double-encodes the [] and silently returns "Sem resultados".
CEPEA_HOST = "www.cepea.org.br"
_URL_FMT = ("https://" + CEPEA_HOST + "/br/widgetproduto.js.php?fonte=arial&tamanho=10"
            "&largura=400px&corfundo=dbd6b2&cortexto=333333&corlinha=ede7bf"
            "&id_indicador%5B%5D={indicator}")

# THE PINNED UA. Probed 2026-07-28 and 2026-07-29: default python-requests UA -> Cloudflare 403
# (cdn-cgi/content challenge body) on both ids; this string -> HTTP 200, application/javascript,
# ~1,988 B. Referer and Accept-Language change nothing. This is a STATIC UA FILTER, not a JS
# challenge, which is why a plain requests GET with a UA is sufficient and legitimate here.
CEPEA_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

_SOURCE_LABEL = "cepea_widget"
_CONTENT_TYPE = "application/javascript"

# D-PR-20. The apex one-shot has recorded these in raw_meta since 2026-07-29; this route did not,
# so the SAME CEPEA/ESALQ data under the SAME CC BY-NC licence was documented on one route only.
# Defined once in the transform module and imported by both producers -- a unit test pins the two
# strings equal so they cannot drift.
_LICENSE = CEPEA_LICENSE
_ATTRIBUTION = CEPEA_ATTRIBUTION

_TIMEOUT = 30
# Measured: the origin resets the connection after ~4 rapid requests.
_DEFAULT_SLEEP_SECONDS = 2.5
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = 5
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
# Cloudflare's static UA filter. NOT retryable (retrying a UA block just hammers the origin) and
# NOT an absence (writing nothing would be silent on a table with no freshness alarm).
_CHALLENGE_STATUS = 403

# The only S3 error codes that mean "this key is genuinely not there". Everything else raises --
# see raw_exists(). Mirrors fetch_eex_freight._ABSENT_ERROR_CODES.
_ABSENT_ERROR_CODES = frozenset({"404", "NotFound", "NoSuchKey"})


def cepea_url(indicator_id: int) -> str:
    return _URL_FMT.format(indicator=int(indicator_id))


def looks_like_a_widget(payload: bytes) -> Optional[str]:
    """None if the bytes are a plausible widget response, else the reason they are not."""
    text = payload.decode("utf-8", errors="replace")
    if "document.write" not in text:
        return "the response carries no document.write() -- this is not a widget payload"
    if "<tbody>" not in text.lower():
        return "the widget markup carries no <tbody> -- there is no value row in it"
    return None


def fetch_indicator(indicator_id: int, *, timeout: int = _TIMEOUT) -> bytes:
    """The widget payload for one indicator id. A 403 raises -- see the module docstring."""
    url = cepea_url(indicator_id)
    headers = {"User-Agent": CEPEA_USER_AGENT}
    backoff = _BACKOFF_SECONDS
    last_error: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code == _CHALLENGE_STATUS:
                raise RuntimeError(
                    f"{url} returned HTTP 403 -- Cloudflare rejected the request. This is NOT an "
                    f"empty result and must never be treated as one. Check that the pinned "
                    f"CEPEA_USER_AGENT is still being sent and still accepted; the UA alone is the "
                    f"gate (Referer and Accept-Language change nothing)"
                )
            if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS:
                logger.warning("CEPEA id=%s returned HTTP %d (attempt %d/%d) -- retrying in %ds",
                               indicator_id, resp.status_code, attempt, _MAX_ATTEMPTS, backoff)
            else:
                resp.raise_for_status()
                return resp.content
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= _MAX_ATTEMPTS:
                break
            logger.warning("CEPEA id=%s fetch failed (attempt %d/%d): %s -- retrying in %ds",
                           indicator_id, attempt, _MAX_ATTEMPTS, exc, backoff)
        time.sleep(backoff)
        backoff *= 2
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"failed to fetch {url} after {_MAX_ATTEMPTS} attempts")


def raw_meta_extra(*, served_date: str, verdict: str, lag: int, expected_session: str) -> dict:
    """The ``extra=`` record every landed daily capture carries.

    Two D-decisions in one dict. **D-PR-20**: the CC BY-NC grant and its attribution travel with
    the bytes on THIS route too, closing the asymmetry with the apex one-shot -- ``raw_metadata.py``
    documents ``extra`` as existing for precisely this. **D-PR-19**: the object states the session
    it serves, so "which session is this?" is answerable from ``raw_meta`` alone rather than by
    re-parsing the payload. ``posture`` is the counterpart of the one-shot's ``NEVER schedule``:
    this route IS the scheduled one and says so."""
    return {
        "license": _LICENSE,
        "attribution": _ATTRIBUTION,
        "posture": "scheduled daily widget capture (cron 30 22 ? * MON-FRI); "
                   "the apex-host series export is a separate ONE-SHOT and stays one-shot",
        "served_date": served_date,
        "expected_session": expected_session,
        "served_lag_business_days": int(lag),
        "served_verdict": verdict,
    }


def land_bytes(bucket: str, key: str, data: bytes, *, source_url: str, region: str,
               extra: Optional[dict] = None) -> None:
    """Upload one raw artifact + its ``write_raw_s3_metadata`` companion, after the size floor.

    The floor is a BACKSTOP only on this leg: the Cloudflare challenge body is ~5,600 B and the
    legitimate widget is ~1,988 B, so the challenge is BIGGER and size cannot separate them. The
    403 status check in :func:`fetch_indicator` is the real gate."""
    from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
    from leviathan.storage.s3 import upload_bytes_to_s3

    check_min_file_size(data, _SOURCE_LABEL, context=key)
    upload_bytes_to_s3(data, bucket, key, region)
    write_raw_s3_metadata(bucket, key, data, source_url, _CONTENT_TYPE, region, extra=extra)
    logger.info("raw written -> s3://%s/%s (%d bytes)", bucket, key, len(data))


def raw_exists(bucket: str, key: str, region: str) -> bool:
    """True when the object is already landed. **Only a genuine 404 means "absent".**

    THIS DIVERGES FROM THE ESTATE HOUSE IDIOM ON PURPOSE -- see the module docstring's verdict.
    ``except Exception: return False`` turns a throttle, a 5xx or an expired credential into
    "nothing is landed", which is a licence to PUT over a capture that no route can re-fetch: the
    ``.aspx`` series pages are Turnstile-closed by policy, the ``.php`` widget serves the last
    value only, and the archive one-shot stops in 2017.

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


def group_verdict(captures: dict[int, dict], *, expected_session: str,
                  on_stale: str = "withhold") -> tuple[bool, str, str]:
    """``(land, disposition, why)`` for the WHOLE run. Both indicators or neither -- D-PR-19.

    The per-day silver floor for this leg is an EQUALITY (``== 2``), so any rule that could land
    one cash reference and withhold the other converts a clean day into a floor violation. That
    makes this a GROUP decision by construction, not by preference. Four dispositions:

      ``land``                 every fetched capture is fresh;
      ``refuse_ahead``         some capture serves a session LATER than the expected one -- the
                               session model is wrong and landing would mislabel real numbers;
      ``refuse_split``         the indicators disagree on the served date. They are one publication
                               on one host at one instant, so a split means the run is not
                               observing a single session and neither half can be trusted;
      ``withhold_stale``       every non-fresh capture is a re-serve of an older session. Nothing
                               new is on offer; landing it can only duplicate a landed row.

    Only ``land`` writes. ``withhold_stale`` is exit 0 by design -- a holiday must not red the leg
    -- while both refusals are hard failures.
    """
    if not captures:
        return False, "nothing_fetched", "no capture was taken"
    served = {c["served_date"] for c in captures.values()}
    if len(served) > 1:
        detail = ", ".join(f"id {i} -> {c['served_date']}" for i, c in sorted(captures.items()))
        return False, "refuse_split", (
            f"the indicators disagree on the served session ({detail}) -- one host, one "
            f"publication, one instant, so a split capture cannot be reconciled here")
    ahead = sorted(i for i, c in captures.items() if c["verdict"] == SERVED_AHEAD)
    if ahead:
        return False, "refuse_ahead", (
            f"indicator(s) {ahead} serve {sorted(served)[0]}, which is LATER than the expected "
            f"session {expected_session} -- the venue cannot publish a session that has not "
            f"happened, so the expected session (--as-of / --expected-session / the clock) is "
            f"wrong and nothing may be landed against it")
    unknown = sorted(i for i, c in captures.items()
                     if c["verdict"] not in (SERVED_FRESH, SERVED_STALE, SERVED_AHEAD))
    if unknown:
        # FAIL CLOSED. A verdict this function does not recognise must never fall through to the
        # land branch by default -- that is how a new classification silently becomes "land".
        return False, "refuse_unknown_verdict", (
            f"indicator(s) {unknown} carry an unrecognised served-date verdict "
            f"{sorted({captures[i]['verdict'] for i in unknown})}")
    stale = sorted(i for i, c in captures.items() if c["verdict"] == SERVED_STALE)
    if stale and on_stale == "withhold":
        return False, "withhold_stale", (
            f"the widget is re-serving {sorted(served)[0]}, not the expected session "
            f"{expected_session} -- either a Brazilian holiday (no session exists) or a capture "
            f"taken before publication, which one capture cannot distinguish. Nothing new is on "
            f"offer, so nothing is landed and the key stays free for a later fire")
    if stale:
        return True, "land_declared_stale", (
            f"--on-stale land: landing a re-serve of {sorted(served)[0]} against expected session "
            f"{expected_session}, declared in raw_meta")
    return True, "land", f"every capture serves the expected session {expected_session}"


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        stream=sys.stderr)
    load_env()
    ap = argparse.ArgumentParser(description="CEPEA daily cash-reference widget -> raw S3 (W1a)")
    ap.add_argument("--indicator", action="append", type=int, dest="indicators", default=None,
                    choices=sorted(CEPEA_INDICATORS),
                    help="repeatable; default is every curated indicator (23 arabica, 77 corn)")
    ap.add_argument("--as-of", default=None, dest="as_of",
                    help="the FETCH date used in the raw key (default: today, UTC). The VALUE's "
                         "own date is read from the payload by the transform")
    ap.add_argument("--force", action="store_true", help="re-fetch and overwrite today's capture")
    ap.add_argument("--expected-session", default=None, dest="expected_session",
                    help="the session the capture must be serving (YYYY-MM-DD). Default: the "
                         "Brazilian calendar day of the capture instant, rolled back over "
                         "weekends. A capture serving anything else is not landed -- see D-PR-19")
    ap.add_argument("--on-stale", choices=("withhold", "land"), default="withhold",
                    dest="on_stale",
                    help="what to do when the widget re-serves an OLDER session (a holiday, or a "
                         "capture taken before publication). 'withhold' (default) writes nothing "
                         "and leaves the key free for a later fire; 'land' is the pure "
                         "land-and-declare fallback -- it writes the row with the verdict in "
                         "raw_meta, which is what the 2026-07-29 run did silently")
    ap.add_argument("--sleep", type=float, default=_DEFAULT_SLEEP_SECONDS,
                    help="seconds between GETs; the origin resets after ~4 rapid requests")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--aws-region", default=None, dest="aws_region")
    ap.add_argument("--dry-run", action="store_true", help="print the URLs and keys; no HTTP")
    args = ap.parse_args(argv)

    indicators = args.indicators or sorted(CEPEA_INDICATORS)
    as_of = args.as_of or datetime.now(tz=timezone.utc).date().isoformat()
    # The session the capture is judged against. --expected-session wins; otherwise an explicit
    # --as-of names the day being recovered (weekend-rolled, because Saturday is not a session
    # anywhere); otherwise the clock, read in Brazil.
    if args.expected_session:
        expected_session = args.expected_session
    elif args.as_of:
        expected_session = previous_business_day(as_of)
    else:
        expected_session = session_for_capture()

    if args.dry_run:
        print(f"as_of            : {as_of}")
        print(f"expected session : {expected_session}")
        print(f"on stale         : {args.on_stale}")
        for ind in indicators:
            print(f"id {ind} ({CEPEA_INDICATORS[ind]})")
            print(f"  url : {cepea_url(ind)}")
            print(f"  key : {raw_cepea_widget_key(ind, as_of)}")
        print("(dry-run -- no HTTP, no writes)")
        print(f"license recorded per object: {_LICENSE}")
        return 0

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    # PHASE 1 -- fetch and JUDGE every indicator. Nothing is written in this loop: the land/withhold
    # call is a GROUP decision (the silver floor is an equality, so a half-landed day is a
    # violation), and a group decision cannot be taken one indicator at a time.
    captures: dict[int, dict] = {}
    skipped = 0
    failures: list[str] = []
    fetched = 0
    for ind in indicators:
        key = raw_cepea_widget_key(ind, as_of)
        if not args.force:
            # THE ONLY raw_exists CALL SITE ON THIS LEG, and it sits OUTSIDE the per-indicator try
            # below. An existence probe that cannot answer must be read neither as "absent" (which
            # is how the old swallow-all raw_exists destroyed captures -- phase 2 PUTs with no
            # second fence in front of it) nor as "already landed" (a silent skip).
            #
            # It takes the WHOLE RUN out, not this indicator: landing is a GROUP decision because
            # the per-day silver floor is an EQUALITY (== 2). Recording one indicator as failed and
            # carrying on would leave group_verdict a single fresh capture, which it would quite
            # correctly rule `land` -- manufacturing exactly the 1-row day that rule exists to
            # prevent. Phase 1 has written nothing at this point, so returning here lands NOTHING.
            try:
                already_landed = raw_exists(bucket, key, aws_region)
            except Exception as exc:  # noqa: BLE001 -- raw_exists fails CLOSED and may raise here
                logger.error(
                    "CEPEA %s REFUSED: the raw existence probe for indicator %s could not answer "
                    "(%s: %s) -- NOTHING FETCHED, NOTHING LANDED. An unanswerable probe must never "
                    "be read as 'absent' and PUT over a landed capture on a leg whose series pages "
                    "are Turnstile-closed and whose widget serves the last value only",
                    as_of, ind, type(exc).__name__, exc,
                )
                return 1
            if already_landed:
                skipped += 1
                continue
        if fetched:
            time.sleep(max(0.0, args.sleep))
        try:
            payload = fetch_indicator(ind)
            fetched += 1
            bad = looks_like_a_widget(payload)
            if bad:
                raise ValueError(f"{cepea_url(ind)}: {bad}")
            served = served_date_from_widget(payload)
            verdict, lag = classify_served_date(served, expected_session)
            captures[ind] = {"key": key, "payload": payload, "served_date": served,
                             "verdict": verdict, "lag": lag}
        except Exception as exc:  # noqa: BLE001 -- one id's failure must not abort the other
            logger.exception("FAILED CEPEA indicator %s", ind)
            failures.append(f"{ind}: {type(exc).__name__}")

    land, disposition, why = group_verdict(captures, expected_session=expected_session,
                                           on_stale=args.on_stale)

    # THE DECLARATION. One greppable line, whichever way the verdict went -- a withhold that left
    # no raw_meta behind must still be visible in the job log.
    declaration = {
        "as_of": as_of,
        "expected_session": expected_session,
        "disposition": disposition,
        "on_stale": args.on_stale,
        "fetched": sorted(captures),
        "skipped_existing": skipped,
        "failed": len(failures),
        "served": {str(i): c["served_date"] for i, c in sorted(captures.items())},
        "verdict": {str(i): c["verdict"] for i, c in sorted(captures.items())},
        "served_lag_business_days": {str(i): int(c["lag"]) for i, c in sorted(captures.items())},
    }
    logger.info("cepea served-date declaration: %s", json.dumps(declaration, sort_keys=True))

    landed = 0
    if land:
        # PHASE 2 -- write. Reached only when the whole group may land.
        for ind, cap in sorted(captures.items()):
            try:
                land_bytes(bucket, cap["key"], cap["payload"], source_url=cepea_url(ind),
                           region=aws_region,
                           extra=raw_meta_extra(served_date=cap["served_date"],
                                                verdict=cap["verdict"], lag=cap["lag"],
                                                expected_session=expected_session))
                landed += 1
            except Exception as exc:  # noqa: BLE001
                logger.exception("FAILED to land CEPEA indicator %s", ind)
                failures.append(f"{ind}: {type(exc).__name__}")
    elif captures:
        logger.warning("CEPEA %s: NOTHING LANDED (%s) -- %s", as_of, disposition, why)

    logger.info("CEPEA %s done: landed=%d skipped_existing=%d withheld=%d failed=%d",
                as_of, landed, skipped, 0 if land else len(captures), len(failures))
    if failures:
        logger.error("failed indicator(s): %s", ", ".join(failures))
        return 1
    if disposition in ("refuse_ahead", "refuse_split", "refuse_unknown_verdict"):
        # A hard refusal: the session model and the payload disagree, and landing would mislabel
        # real numbers. Never the holiday path -- that is `withhold_stale`, which exits 0.
        logger.error("CEPEA %s REFUSED: %s", as_of, why)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
