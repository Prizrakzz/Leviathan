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

S3 LAYOUT
---------
    raw/production/source=cepea/indicator={23|77}/as_of_date={YYYY-MM-DD}/widget.js
    raw_meta/<that key>_meta.json

Usage
-----
    python jobs/ingest/fetch_cepea_daily.py
    python jobs/ingest/fetch_cepea_daily.py --indicator 23 --dry-run
"""
from __future__ import annotations

import argparse
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
from leviathan.transforms.raw_to_bronze.cepea import CEPEA_INDICATORS  # noqa: E402

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
_TIMEOUT = 30
# Measured: the origin resets the connection after ~4 rapid requests.
_DEFAULT_SLEEP_SECONDS = 2.5
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = 5
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
# Cloudflare's static UA filter. NOT retryable (retrying a UA block just hammers the origin) and
# NOT an absence (writing nothing would be silent on a table with no freshness alarm).
_CHALLENGE_STATUS = 403


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


def land_bytes(bucket: str, key: str, data: bytes, *, source_url: str, region: str) -> None:
    """Upload one raw artifact + its ``write_raw_s3_metadata`` companion, after the size floor.

    The floor is a BACKSTOP only on this leg: the Cloudflare challenge body is ~5,600 B and the
    legitimate widget is ~1,988 B, so the challenge is BIGGER and size cannot separate them. The
    403 status check in :func:`fetch_indicator` is the real gate."""
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
    except Exception:  # noqa: BLE001
        return False


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
    ap.add_argument("--sleep", type=float, default=_DEFAULT_SLEEP_SECONDS,
                    help="seconds between GETs; the origin resets after ~4 rapid requests")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--aws-region", default=None, dest="aws_region")
    ap.add_argument("--dry-run", action="store_true", help="print the URLs and keys; no HTTP")
    args = ap.parse_args(argv)

    indicators = args.indicators or sorted(CEPEA_INDICATORS)
    as_of = args.as_of or datetime.now(tz=timezone.utc).date().isoformat()

    if args.dry_run:
        print(f"as_of : {as_of}")
        for ind in indicators:
            print(f"id {ind} ({CEPEA_INDICATORS[ind]})")
            print(f"  url : {cepea_url(ind)}")
            print(f"  key : {raw_cepea_widget_key(ind, as_of)}")
        print("(dry-run -- no HTTP, no writes)")
        return 0

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    landed = skipped = 0
    failures: list[str] = []
    for i, ind in enumerate(indicators):
        key = raw_cepea_widget_key(ind, as_of)
        if not args.force and raw_exists(bucket, key, aws_region):
            skipped += 1
            continue
        if i:
            time.sleep(max(0.0, args.sleep))
        try:
            payload = fetch_indicator(ind)
            bad = looks_like_a_widget(payload)
            if bad:
                raise ValueError(f"{cepea_url(ind)}: {bad}")
            land_bytes(bucket, key, payload, source_url=cepea_url(ind), region=aws_region)
            landed += 1
        except Exception as exc:  # noqa: BLE001 -- one id's failure must not abort the other
            logger.exception("FAILED CEPEA indicator %s", ind)
            failures.append(f"{ind}: {type(exc).__name__}")

    logger.info("CEPEA %s done: landed=%d skipped_existing=%d failed=%d",
                as_of, landed, skipped, len(failures))
    if failures:
        logger.error("failed indicator(s): %s", ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
