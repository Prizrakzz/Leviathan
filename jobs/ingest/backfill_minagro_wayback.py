#!/usr/bin/env python
"""MINAGRO -- recover the ministry's export-table HISTORY from the Wayback Machine.

WHY THIS JOB EXISTS
-------------------
``jobs/ingest/fetch_minagro_grain_exports.py`` owns the LIVE leg and it is a forward-accumulation
producer: Ukraine's Ministry of Agrarian Policy publishes its State Customs export table at ONE
permanent URL and edits it IN PLACE, roughly weekly. There is no per-release URL, no archive index
and no document id, so the moment the ministry re-publishes, the previous release is simply GONE
from the origin. The live leg's own docstring states the consequence plainly: *a missed week is
UNRECOVERABLE*. On 2026-08-20 that leg landed its first observation (as_of 2026-08-14) and the
series therefore consisted of exactly one point.

It is unrecoverable FROM THE ORIGIN. The Wayback Machine crawled the standing slug independently,
and because the ministry edits the page in place, each distinct capture DIGEST is a distinct table
state -- i.e. a distinct weekly release, sitting in the archive, addressable. That is what this job
harvests. It is a ONE-SHOT repair, not a schedule: the archive's holdings for this slug do not grow
on a cadence we control, and the live leg is what keeps the series moving forward.

THE WAYBACK LAW (banked the expensive way, 2026-07-29, W1a/CEPEA)
-----------------------------------------------------------------
A wayback timestamp is a REQUEST, not a guarantee. ``/web/{ts}id_/{url}`` does NOT 404 when ``ts``
has no capture -- it silently 200s with the NEAREST capture, and those bytes then wear the requested
timestamp forever. So every capture here is PINNED from the CDX index and the SERVED capture is read
back off the response and compared; drift is REFUSED, never landed. The law and its two helpers live
in :mod:`leviathan.common.wayback` and this job does not re-derive them.

That law has a SECOND edge on this source, and it is the one that actually bites here. This family's
raw key is dated by the PAGE'S OWN ``станом на`` date, not by the capture date -- so a body served
from the wrong capture would not merely wear a wrong timestamp, it would land under a wrong
``as_of=`` key and mint a plausible, well-formed, WRONG weekly observation. Hence the third check
:func:`verify_capture` makes, which the binary-artifact legs (unica, cepea) have no analogue for:
the page's own as-of must be at or BEFORE the capture instant. The ministry cannot publish customs
figures dated after the day the crawler visited.

WHAT IS LANDED, AND WHY IT IS NOT THE ARCHIVED BYTES VERBATIM
--------------------------------------------------------------
The archived body is the WHOLE page (~69 KB: masthead, nav, breadcrumb, footer). The live producer
lands the rendered ``<main>`` outerHTML (~6 KB) -- a DOM snapshot, the Euronext W1c precedent -- and
``storage/paths.raw_minagro_grain_exports_key`` documents that as this family's raw contract. This
job therefore extracts ``<main>`` from the archived page and lands THAT, so bronze sees one single
object shape across the whole series and ``header_html``'s "everything above the first ``<table>``"
slice means the same thing in a 2024 capture as in a 2026 one.

The extraction is not a parse and it is auditable: the raw metadata records the sha256 AND the CDX
digest of the FULL archived body alongside the landed object, plus the replay URL, so anyone can
re-fetch the archived page and reproduce the extraction byte for byte. A capture with no ``<main>``
element is REFUSED and counted rather than landed under a second, undeclared shape.

THE GATE ORDER IS THE PRODUCER'S, DELIBERATELY
-----------------------------------------------
:func:`~leviathan.transforms.raw_to_bronze.minagro_grain_exports.looks_like_the_export_table` runs
BEFORE any key is derived, exactly as the live producer runs it -- so an archived Cloudflare
challenge body, a CMS error page or a redesign is SKIPPED with a written reason and a counter, never
landed. (The CDX filter ``statuscode:200`` already drops the twelve archived 403 interstitials this
slug carries; the sniff is the defence against a 200 that is not the table.) Raw is immutable: a
challenge body filed under an ``as_of=`` key is indistinguishable from the real table forever after.

FIRST CAPTURE WINS, ON TWO AXES
--------------------------------
The live leg's rule, honoured here without exception -- an existing object under an ``as_of=`` key
IS that release and is never overwritten:

  * ACROSS RUNS: an ``as_of=`` key already in S3 is skipped. Today's live 2026-08-14 capture is a
    real browser render of the origin; nothing from the archive may ever replace it.

    **And that is why the existence probe FAILS CLOSED (verdict 2026-08-20).** ``raw_exists`` is
    the only thing enforcing that sentence, and the estate house idiom
    (``except Exception: return False``) answers "absent" to a throttle, a 5xx, an expired token or
    a denied head -- so a transient ``HeadObject`` failure repeals it silently.

    Are the ARCHIVED bytes re-derivable? Yes: the capture is CDX-pinned, the archive is immutable
    and ``verify_capture`` refuses drift, so this is not the ``fetch_eex_freight.py`` argument. The
    argument that DOES bite is the one the sentence above states: the overwrite this enables is
    CROSS-SHAPE. What gets destroyed is not another archived capture but a
    ``rendered_main_outerhtml`` browser render OF THE ORIGIN -- and what replaces it is a
    ``wayback_main_outerhtml`` cut from a crawl, filed under the same ``as_of=`` key, distinguished
    from it afterwards only by a ``capture_kind`` field in ``raw_meta`` that nothing re-checks. The
    live leg's capture is the better witness and it is not re-derivable at all (the origin serves
    one release at a time), so the direction of the loss is strictly one-way.

    So only a genuine 404 means absent; any other ``HeadObject`` error raises, and the raise falls
    to the per-capture handler that already exists -- counted in ``errors``, logged as ``FAILED
    capture <ts>``, and the run exits 1. This is a ONE-SHOT repair: failing closed costs a re-run,
    which is nothing, and the archive is not going anywhere.

  * WITHIN A RUN: several distinct capture digests can carry the SAME ``станом на`` date, because
    the CMS re-publishes cosmetically between releases (new publish stamp, same customs numbers).
    The EARLIEST capture of a given as-of wins -- it is the closest witness to the release -- and
    the losers are logged with their timestamps rather than dropped silently.

MEASURED, 2026-08-20 (the first run of this job)
-------------------------------------------------
CDX holds 32 rows for this slug: 16 x 200, 12 x 403 (Cloudflare interstitials the crawler archived),
3 x 301, 1 x 520. The 16 successes collapse to 12 DISTINCT DIGESTS spanning 2024-03-05 .. 2025-05-28
(the five 2024-08-12 rows are one page state crawled five times in four hours). After 2025-05-28
every capture is a 403: the archive stopped being able to see this page, so the recoverable history
has a hard right edge there and the gap to the live leg's 2026-08-14 first observation is NOT
closable from the archive.

Two findings from that run, both recorded here because they are the kind that would otherwise be
re-derived from scratch:

  1. THE CDX DIGEST IS NOT A RELIABLE PAYLOAD CHECK. Recomputing the documented unpadded-base32
     SHA-1 over the served body matched the CDX ``digest`` column for only 9 of 12 captures. This
     settles, in the NEGATIVE, the open question ``backfill_unica_wayback.verify_payload`` left
     behind ("once a real run shows the digests matching, flip the default"): do NOT flip it. The
     digest is recorded as provenance and compared as a WARNING; the capture-drift check is what
     establishes provenance, and it is hard.
  2. ONE CAPTURE IS UNPARSEABLE FOR A TYPOGRAPHIC REASON, 20240305120831 (as-of 2024-03-04). The
     ministry's CMS split the day's two digits into separate ``<strong>`` elements
     (``<strong>0</strong><strong>4</strong>.03.2024``), so the page's text renders as
     "станом на 0 4 .03.2024" and ``_AS_OF_RE``'s ``(\\d{2})`` cannot match. It is a one-off, not a
     layout era -- the captures either side of it (20240316, 20240319) parse cleanly -- and it is
     REPORTED and skipped rather than repaired by loosening the date regex, because that regex is
     the single guard standing between this series and the silent-mis-dating class the transform's
     module docstring is built around. Loosening it is an owner's call, not a backfill's.

S3 LAYOUT (the family's normal layout -- nothing bespoke)
---------------------------------------------------------
    raw/production/source=minagro_grain_exports/as_of={YYYYMMDD}/page.html
    raw_meta/<that key>_meta.json   (sha256, replay URL, capture ts, CDX digest, full-page sha256)

Usage
-----
    # the plan: CDX enumeration + a per-capture verdict, and NOT ONE body fetched
    python jobs/ingest/backfill_minagro_wayback.py --dry-run

    # the repair itself
    python jobs/ingest/backfill_minagro_wayback.py

    # then fold the new captures into bronze + silver (no live fetch, no browser):
    python jobs/ingest/run_minagro_pipeline.py --skip-fetch
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import logging
import os
import sys
import time
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402
from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.common.wayback import capture_drift, replay_url, served_capture_ts  # noqa: E402
from leviathan.storage.paths import raw_minagro_grain_exports_key  # noqa: E402
from leviathan.transforms.raw_to_bronze.minagro_grain_exports import (  # noqa: E402
    PAGE_URL,
    SOURCE,
    as_of_date_from_page,
    ascii_safe,
    looks_like_the_export_table,
    publish_stamp,
)

logger = get_logger("backfill_minagro_wayback")

# ---------------------------------------------------------------------------
# The CDX query
# ---------------------------------------------------------------------------
# ``url=`` is the SCHEME-LESS origin path, which is how CDX canonicalises it -- the index holds this
# slug under both http:// and https:// and one urlkey covers both. Server-side ``filter`` and
# ``collapse`` on purpose: filtering here rather than in python means the archive never has to hand
# us the twelve 403 interstitials, and ``collapse=digest`` means ONE FETCH PER DISTINCT PAGE STATE
# instead of one per crawl (five 2024-08-12 crawls of one unchanged page = one fetch).
#
# NOTE what ``collapse=digest`` actually does: it is an ADJACENT-run collapse over the result
# ordering (CDX is sorted by timestamp), not a global unique. A digest that recurs after some other
# digest intervened comes back twice -- which is CORRECT here (the ministry reverting the page IS a
# second observation of that state) -- and :func:`plan_captures` de-duplicates on the axis that
# actually decides the key, the as-of date, rather than trusting the collapse to be a set.
CDX_TARGET = (
    "minagro.gov.ua/napryamki/eksport-do-krain-ies/"
    "eksport-z-ukrayini-zernovih-zernobobovih-ta-boroshna"
)
CDX_URL = (
    "https://web.archive.org/cdx/search/cdx"
    f"?url={CDX_TARGET}"
    "&output=json"
    "&fl=timestamp,original,digest,statuscode,length"
    "&filter=statuscode:200"
    "&collapse=digest"
)

# archive.org is a LIBRARY, not a CDN. One body fetch every 2.5 s, one CDX call per run, bounded
# retries only on the statuses it actually returns under load.
_SLEEP_BETWEEN_FETCHES_S = 2.5
_CDX_TIMEOUT_S = 90
_FETCH_TIMEOUT_S = 120
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = 10
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

_USER_AGENT = "Leviathan-MINAGRO-Backfill/1.0 (research; non-commercial)"
_CONTENT_TYPE = "text/html"

# The as-of may lag the capture (the crawler visits days after the ministry's release), but it may
# never LEAD it: a page whose own as-of is dated after the crawl is not the page that was crawled.
# The lag warning floor is advisory -- the ministry has published at 5-day lags -- and exists so an
# unusually stale body is visible in the log rather than silently minting an old week.
_MAX_PLAUSIBLE_LAG_DAYS = 21

# The only S3 error codes that mean "this key is genuinely not there". Everything else raises --
# see raw_exists(). Mirrors fetch_eex_freight._ABSENT_ERROR_CODES.
_ABSENT_ERROR_CODES = frozenset({"404", "NotFound", "NoSuchKey"})


# ---------------------------------------------------------------------------
# HTTP seam -- the ONLY place this module touches the network. Tests monkeypatch here.
# ---------------------------------------------------------------------------

def _http_get(url: str, *, timeout: int) -> "requests.Response":
    """GET with bounded retries on the transient statuses Wayback actually returns."""
    backoff = _BACKOFF_SECONDS
    last_error: Optional[Exception] = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=timeout)
            if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS:
                logger.warning("wayback HTTP %d (attempt %d/%d) -- retrying in %ds: %s",
                               resp.status_code, attempt, _MAX_ATTEMPTS, backoff, url)
            else:
                resp.raise_for_status()
                return resp
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= _MAX_ATTEMPTS:
                break
            logger.warning("wayback fetch failed (attempt %d/%d): %s -- retrying in %ds",
                           attempt, _MAX_ATTEMPTS, exc, backoff)
        time.sleep(backoff)
        backoff *= 2
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"failed to fetch {url} after {_MAX_ATTEMPTS} attempts")


# ---------------------------------------------------------------------------
# Phase A -- enumerate the CDX index (pure filtering, one network call)
# ---------------------------------------------------------------------------

def cdx_digest(payload: bytes) -> str:
    """The CDX ``digest`` form of *payload*: unpadded base32 of its SHA-1.

    Recorded and compared as PROVENANCE ONLY. Measured 2026-08-20 on this slug: it matched the
    index for 9 of 12 captures, so it is not a payload check and a mismatch is never a refusal --
    see the module docstring, finding (1)."""
    return base64.b32encode(hashlib.sha1(payload).digest()).decode("ascii").rstrip("=")


def parse_cdx_rows(payload: Any) -> list[dict[str, str]]:
    """The CDX JSON body -> a list of dicts, one per row.

    CDX's JSON is a HEADER ROW plus data rows, not objects, so the field names must be zipped on
    from row 0. An empty index answers ``[]`` (or a bare header), which is a real answer -- "the
    archive holds nothing" -- and not an error."""
    if isinstance(payload, (bytes, bytearray, str)):
        payload = json.loads(payload)
    if not payload or len(payload) < 2:
        return []
    fields = payload[0]
    return [dict(zip(fields, row)) for row in payload[1:]]


def select_captures(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """CDX rows -> the captures worth fetching: HTTP 200, well-formed timestamp, one per digest.

    Pure. No network, no clock. The server-side ``filter``/``collapse`` in :data:`CDX_URL` already
    do most of this, but they are re-done here rather than trusted:

      * ``statuscode`` -- a redirect (301) or an archived Cloudflare interstitial (403) is not a
        table, and this slug's index is 50% those. Re-checking costs nothing and means a caller who
        passes an unfiltered index gets the same answer;
      * ``timestamp`` -- 14 digits or it cannot be pinned, and an unpinnable row must not become a
        replay request (that is precisely the CEPEA failure mode);
      * ``digest`` -- ONE FETCH PER DISTINCT PAGE STATE. ``collapse=digest`` is an adjacent-run
        collapse server-side, so a digest that recurs later in the ordering still arrives twice;
        this is a global de-duplication and it keeps the EARLIEST capture of each state, which is
        the closest witness to the release that produced it.
    """
    seen: dict[str, dict[str, str]] = {}
    for row in rows:
        if str(row.get("statuscode") or "") != "200":
            continue
        ts = str(row.get("timestamp") or "")
        if len(ts) != 14 or not ts.isdigit():
            logger.warning("CDX row with an unusable timestamp %r -- skipped: a capture that "
                           "cannot be pinned must never become a replay request", ascii_safe(ts))
            continue
        digest = str(row.get("digest") or "")
        if not digest:
            logger.warning("CDX row %s carries no digest -- skipped: without it there is no way to "
                           "tell one page state from a re-crawl of the same one", ts)
            continue
        prior = seen.get(digest)
        if prior is None or ts < prior["timestamp"]:
            seen[digest] = {
                "timestamp": ts,
                "digest": digest,
                "original": str(row.get("original") or "") or PAGE_URL,
                "statuscode": "200",
                "length": str(row.get("length") or ""),
            }
    out = sorted(seen.values(), key=lambda c: c["timestamp"])
    for cap in out:
        cap["replay_url"] = replay_url(cap["timestamp"], cap["original"])
    return out


def fetch_cdx() -> list[dict[str, str]]:
    """The CDX index for this slug -> selected captures. ONE network call."""
    logger.info("CDX: %s", CDX_URL)
    rows = parse_cdx_rows(_http_get(CDX_URL, timeout=_CDX_TIMEOUT_S).content)
    captures = select_captures(rows)
    logger.info("CDX: %d row(s) -> %d distinct capture(s) worth fetching", len(rows), len(captures))
    return captures


# ---------------------------------------------------------------------------
# Phase B -- one archived body -> the landable payload, or a written refusal
# ---------------------------------------------------------------------------

def capture_date(timestamp: str) -> dt.date:
    """The calendar date of a 14-digit CDX timestamp."""
    return dt.date(int(timestamp[:4]), int(timestamp[4:6]), int(timestamp[6:8]))


def extract_main(archived_html: str) -> Optional[str]:
    """The archived page's ``<main>`` outerHTML, or None when it has none.

    This family's raw object is the rendered ``<main>`` outerHTML (the live producer's
    ``capture_kind``), and the archive holds the WHOLE page. Extracting rather than landing the
    whole page keeps ONE object shape across the series, which is what makes ``header_html``'s
    above-the-first-table slice mean the same thing in every capture. Returning None -- rather than
    falling back to the whole page -- is deliberate: a second, undeclared shape in the raw layer is
    worse than a capture the report names as skipped."""
    node = BeautifulSoup(archived_html, "html.parser").find("main")
    return str(node) if node is not None else None


def verify_capture(
    pin: dict[str, str],
    payload: bytes,
    served: Optional[str],
) -> Optional[str]:
    """``None`` when this response may be used, else the reason it must not be.

    Two hard checks, in the order that makes the cheapest true statement first:

      1. CAPTURE DRIFT. THE estate law -- an unmatched timestamp 200s with the NEAREST capture, so
         a response that does not name the pinned capture is some other day's bytes.
      2. NON-EMPTY. Wayback serves an HTML "not archived" placeholder with HTTP 200; a body far
         too small to be this ~69 KB page is that placeholder, and the marker sniff downstream
         would reject it anyway -- but saying so HERE names the actual cause.

    The CDX digest is compared afterwards by the caller and only ever WARNS: measured 9/12 on this
    slug (module docstring, finding 1)."""
    drift = capture_drift(pin["timestamp"], served, what="this archived page")
    if drift:
        return drift
    if len(payload) < 1024:
        return (
            f"the response is {len(payload)} byte(s) -- far too small to be this page. Wayback "
            f"serves an HTML 'not archived' placeholder with HTTP 200, so capture "
            f"{pin['timestamp']} does not actually hold this slug"
        )
    return None


def as_of_for_capture(pin: dict[str, str], main_html: str) -> dt.date:
    """The page's own ``станом на`` date, cross-checked against the capture instant.

    The date comes from the PAGE, via the transform -- never from the capture timestamp. The
    cross-check is the one this source needs that a PDF backfill does not: the raw key is dated by
    the page's own as-of, so a body from the wrong capture lands a well-formed WRONG week rather
    than merely a mis-stamped file. Customs figures cannot be dated after the day the crawler
    visited, so an as-of that LEADS the capture is a hard refusal."""
    as_of = as_of_date_from_page(main_html)
    captured = capture_date(pin["timestamp"])
    if as_of > captured:
        raise ValueError(
            f"the page's own 'stanom na' date is {as_of.isoformat()} but this capture was taken "
            f"{captured.isoformat()} -- the table is dated AFTER the crawl that archived it. The "
            f"ministry cannot publish customs figures for a day that has not closed, so these "
            f"bytes are not the capture they claim to be"
        )
    lag = (captured - as_of).days
    if lag > _MAX_PLAUSIBLE_LAG_DAYS:
        logger.warning(
            "minagro %s: capture %s is %d days after the table's own as-of. The page is a standing "
            "slug the ministry edits weekly, so a lag this long means the crawler caught a stale "
            "render -- the as-of is still the date of record, but the release may already have "
            "been superseded when this capture was taken",
            as_of.isoformat(), pin["timestamp"], lag,
        )
    return as_of


# ---------------------------------------------------------------------------
# First capture wins -- within the run, and across runs
# ---------------------------------------------------------------------------

def first_capture_wins(
    landed_as_of: dict[str, str],
    as_of: dt.date,
    timestamp: str,
) -> Optional[str]:
    """``None`` when this capture may claim *as_of*, else which capture already owns it.

    The WITHIN-RUN half of the live leg's rule. Several distinct digests can carry the same as-of
    because the CMS re-publishes cosmetically between releases -- a fresh publish stamp over
    unchanged customs numbers. Captures are processed in timestamp order, so the incumbent is
    always the EARLIER one and it keeps the key."""
    incumbent = landed_as_of.get(as_of.isoformat())
    if incumbent is None:
        return None
    return (
        f"as-of {as_of.isoformat()} was already landed from capture {incumbent} earlier in this "
        f"run; capture {timestamp} is a later re-render of the same release (first capture wins)"
    )


def raw_exists(s3_client: Any, bucket: str, key: str) -> bool:
    """Whether the raw object already exists. **Only a genuine 404 means "absent".**

    THIS DIVERGES FROM THE ESTATE HOUSE IDIOM ON PURPOSE -- see the module docstring's verdict.
    ``except Exception: return False`` turns a throttle, a 5xx or an expired credential into
    "nothing is landed", which here is a licence for an ARCHIVED re-render to overwrite a LIVE
    browser render of the origin under the same ``as_of=`` key. The archived bytes are re-derivable;
    the live capture is not, so the loss runs one way only.

    Takes an ``s3_client`` rather than a region because this job builds ONE client up front and
    threads it through -- the signature differs from the sibling producers, the semantics do not.

    The 403-instead-of-404 trap does NOT apply: ``batch_job_role`` carries ``s3:ListBucket`` on the
    bucket (infra/terraform/modules/iam/main.tf, sid ``ListDataLakeBucket``), so a HeadObject
    against a key that does not exist answers 404 rather than AccessDenied -- the narrowing cannot
    brick a first-ever capture.
    """
    from botocore.exceptions import ClientError

    try:
        s3_client.head_object(Bucket=bucket, Key=key)
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


def capture_metadata(
    pin: dict[str, str],
    archived: bytes,
    main_html: str,
    as_of: dt.date,
) -> dict[str, Any]:
    """The ``raw_meta`` extras for one archived capture.

    Everything needed to reproduce the landed object from the archive without this job: the replay
    URL, the pinned AND served capture timestamps, the CDX digest as indexed and as recomputed, and
    the sha256 of the FULL archived page the ``<main>`` was cut from. ``capture_kind`` is distinct
    from the live leg's ``rendered_main_outerhtml`` on purpose -- a consumer must be able to tell a
    browser render of the origin from a ``<main>`` cut out of an archived page, even though the two
    parse identically."""
    stamp = publish_stamp(main_html)
    return {
        "source": SOURCE,
        "capture_kind": "wayback_main_outerhtml",
        "backfill_job": "backfill_minagro_wayback",
        "as_of_date": as_of.isoformat(),
        "origin_url": pin["original"],
        "replay_url": pin["replay_url"],
        "wayback_capture_ts": pin["timestamp"],
        "wayback_served_capture_ts": pin.get("served_capture_ts"),
        "cdx_digest": pin["digest"],
        "cdx_payload_digest": cdx_digest(archived),
        "archived_page_sha256": hashlib.sha256(archived).hexdigest(),
        "archived_page_bytes": len(archived),
        "publish_stamp_text": stamp["publish_stamp_text"],
        "published_at": stamp["published_at"],
    }


# ---------------------------------------------------------------------------
# The plan -- what a dry run prints and a real run executes
# ---------------------------------------------------------------------------

def plan_captures(captures: list[dict[str, str]]) -> list[dict[str, Any]]:
    """The per-capture plan a dry run reports: what WILL be fetched, in what order.

    Deliberately shallow. A dry run may not fetch a body (that is the whole point of the flag), and
    the as-of, the sniff verdict and the S3 key are all properties OF THE BODY -- so the honest plan
    says "fetch and decide", and never guesses a key it cannot know. Reporting a predicted as_of
    here would be exactly the wished-for-date habit the wayback law exists to break."""
    return [
        {
            "timestamp": cap["timestamp"],
            "capture_date": capture_date(cap["timestamp"]).isoformat(),
            "digest": cap["digest"],
            "replay_url": cap["replay_url"],
            "verdict": "FETCH -- sniff, then key on the page's own 'stanom na' date",
        }
        for cap in captures
    ]


def _print_plan(captures: list[dict[str, str]]) -> None:
    plan = plan_captures(captures)
    print(f"cdx target : {CDX_TARGET}")
    print(f"captures   : {len(plan)} distinct digest(s) to fetch")
    if plan:
        print(f"capture span: {plan[0]['capture_date']} .. {plan[-1]['capture_date']}")
    for item in plan:
        print(f"  {item['timestamp']}  ({item['capture_date']})  digest {item['digest']}")
        print(f"      replay : {item['replay_url']}")
        print(f"      verdict: {item['verdict']}")
    print("(dry-run -- the CDX index was queried; NO capture bodies were fetched, no S3 writes)")
    print("as-of dates are NOT predicted here: the as-of is a property of the BODY, and pinning a")
    print("key to a date nobody has read out of the bytes is the habit the wayback law forbids.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill the MINAGRO grain/pulse/flour export table's HISTORY from CDX-pinned Wayback "
            "captures into raw S3. One object per distinct table state, keyed by the page's own "
            "'stanom na' date. First capture wins."
        )
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Query the CDX index and print the per-capture plan. No body fetches, no S3 writes.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite an already-landed as_of= key. Use ONLY to repair a known-bad object: the "
             "landed capture is the release, and an archived re-render is not an improvement on a "
             "live browser render of the origin.",
    )
    parser.add_argument("--limit", type=int, default=0,
                        help="Process at most N captures (smoke tests).")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        stream=sys.stderr)
    args = _parse_args(argv)

    captures = fetch_cdx()
    if args.limit:
        captures = captures[: args.limit]

    if args.dry_run:
        _print_plan(captures)
        return 0 if captures else 1

    if not captures:
        logger.error("ZERO CAPTURES: the CDX index holds no 200-status capture of this slug. The "
                     "history is NOT recoverable from the archive -- this is a finding, not a "
                     "success, so this run does not exit green")
        return 1

    load_env()
    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
    from leviathan.storage.s3 import get_thread_local_s3_client, upload_bytes_to_s3

    s3_client = get_thread_local_s3_client(aws_region)

    landed: dict[str, str] = {}          # as_of ISO -> the capture ts that won it
    skipped_challenge: list[str] = []    # captures the sniff / <main> gate refused
    skipped_duplicate: list[str] = []    # as-of already owned (this run or a prior landing)
    parse_failures: list[dict[str, str]] = []
    errors = 0

    for i, cap in enumerate(captures):
        if i:
            time.sleep(_SLEEP_BETWEEN_FETCHES_S)
        try:
            resp = _http_get(cap["replay_url"], timeout=_FETCH_TIMEOUT_S)
            archived = resp.content
            cap["served_capture_ts"] = served_capture_ts(resp)

            bad = verify_capture(cap, archived, cap["served_capture_ts"])
            if bad:
                logger.error("REFUSED capture %s: %s", cap["timestamp"], ascii_safe(bad, 500))
                skipped_challenge.append(cap["timestamp"])
                continue

            indexed, actual = cap["digest"], cdx_digest(archived)
            if indexed != actual:
                # PROVENANCE ONLY -- see the module docstring, finding (1). The drift check above
                # is what establishes which capture these bytes are.
                logger.warning("capture %s: CDX indexed digest %s, payload hashes to %s -- landing "
                               "anyway (measured 9/12 on this slug; the digest column is not a "
                               "payload check and the capture-drift check is what binds provenance)",
                               cap["timestamp"], indexed, actual)

            main_html = extract_main(archived.decode("utf-8", errors="replace"))
            if main_html is None:
                logger.error("REFUSED capture %s: the archived page carries no <main> element. This "
                             "family's raw object is the rendered <main> outerHTML and a second, "
                             "undeclared object shape in an immutable layer is worse than a gap",
                             cap["timestamp"])
                skipped_challenge.append(cap["timestamp"])
                continue

            # THE PRODUCER'S GATE, in the producer's order: a challenge body, a 404 or a CMS error
            # is refused BEFORE any key is derived from it.
            sniff = looks_like_the_export_table(main_html)
            if sniff:
                logger.error("REFUSED capture %s: %s", cap["timestamp"], ascii_safe(sniff, 500))
                skipped_challenge.append(cap["timestamp"])
                continue

            try:
                as_of = as_of_for_capture(cap, main_html)
            except ValueError as exc:
                # A FINDING, not a silent skip: the capture IS the export table (the sniff passed)
                # and something about its markup defeats the date read. Named, with its timestamp.
                logger.error("PARSE FAILURE capture %s (%s): %s", cap["timestamp"],
                             capture_date(cap["timestamp"]).isoformat(), ascii_safe(exc, 600))
                parse_failures.append({
                    "timestamp": cap["timestamp"],
                    "capture_date": capture_date(cap["timestamp"]).isoformat(),
                    "reason": ascii_safe(exc, 400),
                })
                continue

            dup = first_capture_wins(landed, as_of, cap["timestamp"])
            if dup:
                logger.info("skip %s: %s", cap["timestamp"], dup)
                skipped_duplicate.append(cap["timestamp"])
                continue

            key = raw_minagro_grain_exports_key(as_of.isoformat())
            # THE ONLY raw_exists CALL SITE ON THIS LEG, and the statements below it are the PUT.
            # raw_exists now fails CLOSED, and the raise deliberately gets NO handler of its own: it
            # falls to the per-capture `except` below, which is already the loud, correct behaviour
            # -- "FAILED capture <ts>", errors += 1, and the run exits 1 on the `if errors` line.
            # The capture is simply not landed; the other captures still run. There is no exit-0
            # fall-through for such a run to take -- `if errors: return 1` is the first verdict, and
            # it precedes the nothing-landed check.
            if not args.force and raw_exists(s3_client, bucket, key):
                logger.info("skip %s: as-of %s is ALREADY LANDED at s3://%s/%s -- first capture "
                            "wins, and a live browser render of the origin is never replaced by an "
                            "archived one", cap["timestamp"], as_of.isoformat(), bucket, key)
                skipped_duplicate.append(cap["timestamp"])
                landed.setdefault(as_of.isoformat(), "(pre-existing)")
                continue

            data = main_html.encode("utf-8")
            check_min_file_size(data, SOURCE, context=key)
            upload_bytes_to_s3(data, bucket, key, aws_region)
            write_raw_s3_metadata(bucket, key, data, cap["replay_url"], _CONTENT_TYPE, aws_region,
                                  extra=capture_metadata(cap, archived, main_html, as_of))
            landed[as_of.isoformat()] = cap["timestamp"]
            logger.info("landed  as_of=%s  capture=%s  (%d bytes of %d archived) -> s3://%s/%s",
                        as_of.isoformat(), cap["timestamp"], len(data), len(archived), bucket, key)
        except Exception:  # noqa: BLE001 -- counted and logged; one dead capture must not sink the run
            logger.exception("FAILED capture %s (%s)", cap["timestamp"], cap["replay_url"])
            errors += 1

    real = sorted(k for k, v in landed.items() if v != "(pre-existing)")
    logger.info("Done  landed=%d  skipped_challenge=%d  skipped_duplicate_as_of=%d  "
                "parse_failures=%d  errors=%d  (candidates=%d)",
                len(real), len(skipped_challenge), len(skipped_duplicate), len(parse_failures),
                errors, len(captures))
    if real:
        logger.info("as-of span landed: %s .. %s", real[0], real[-1])
    for failure in parse_failures:
        logger.warning("PARSE FAILURE (report, do not re-run blind): capture %s on %s -- %s",
                       failure["timestamp"], failure["capture_date"], failure["reason"])

    if errors:
        return 1
    if not real and not skipped_duplicate:
        logger.error("nothing landed and nothing was already present -- every capture was refused "
                     "or unparseable. A backfill that achieves nothing must not exit green")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
