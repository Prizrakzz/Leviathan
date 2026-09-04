"""Backfill World Bank Pink Sheet VINTAGES into the ARCHIVE raw prefix. Two phases.

Every Pink Sheet release restates the whole monthly history back to 1960-01, so one workbook IS one
complete as-published history.  The estate holds four of them (2026M05/M07/M08/M09) because that is
when the scheduled capture started; every earlier release the World Bank ever published is a vintage
this estate could have had and does not.  This job goes and gets them.

    --phase origin    $0, no archive traffic. GET the RETIRED document-ID epochs that still serve a
                      workbook. MEASURED YIELD IS TWO -- 2025M01 (765,246 B, n=780) and 2026M01
                      (778,415 B, n=792). Three further sighted epochs are measured 404, and the
                      2016 epoch's unhyphenated URL 200s with 100,826 bytes of HTML under an xlsx
                      Content-Type (body_not_workbook). Run this FIRST: it is free, fast, needs no
                      politeness budget, and a retired epoch folder that still serves is an OBSERVED
                      behaviour the World Bank never promised and can garbage-collect at any time.

    --phase wayback   The archive. In-VPC only. A PAGED, SERVER-SIDE-FILTERED worldbank.org DOMAIN
                      census first (--census-only), then bounded harvests.

WHERE THE BYTES LAND, AND WHY IT IS A SEPARATE PREFIX
-----------------------------------------------------
``raw/production/source=world_bank_pink_sheet_archive/release={YYYYMmm}/{filename}``.

``jobs/batch/pink_sheet_task.py`` relists exactly ``raw/production/source=world_bank_pink_sheet/``
and nothing else, so a backfilled vintage is STRUCTURALLY unreachable from the scheduled bronze fire
and therefore from the served latest-only table.  That is served-set invariance by PREFIX, not by a
runtime flag the 8th-of-month cron would have to remember to pass -- and the trailing slash is what
makes it true.  Pinned in ``tests/unit/test_pink_sheet_prefix_fence.py``.

THE FOUR LAWS THIS JOB IS BUILT AROUND
--------------------------------------
1. MAGIC BYTES FIRST, ALWAYS.  ``workbook_kind`` runs before anything tries to parse a body, on
   every body from every source.  ``body_not_workbook`` (a lying origin) and ``format_unsupported``
   (a real legacy OLE2/.xls) are counted APART, because they have different causes and different
   answers.

2. THE CONTENT KEY DECIDES THE MONTH.  Never the URL, never the epoch, never the capture timestamp,
   never a wished-for date.  ``derived_release_ym`` = last monthly row + one month.

3. THE SERVED CAPTURE IS VERIFIED, NOT ASSUMED.  ``/web/{ts}id_/`` does NOT 404 on an unmatched
   timestamp -- it 200s with the NEAREST capture.  Every archive body goes through
   ``wayback.served_capture_ts`` + ``wayback.capture_drift``.  This is the law that cost CEPEA nine
   years.

4. THE ARCHIVE'S CLOCK IS NOT THE ORIGIN'S.  On a replay, rung 1 of the release-clock ladder reads
   ``X-Archive-Orig-Last-Modified`` AND NOTHING ELSE.  The replay's own ``Last-Modified`` is the
   ARCHIVE's, and feeding it to the ladder would stamp the CRAWL date as ``release_date`` under a
   token asserting the opposite.  A body with no origin header takes ``derived_month_first_archive``,
   a DISTINCT token, so the corpus can tell an origin-clocked vintage from an archive-clocked one.

NEW CODE, NO BORROWED PRECEDENT -- SAID OUT LOUD
------------------------------------------------
CDX appears in this estate at ``backfill_minagro_wayback.py`` and ``backfill_unica_wayback.py``, and
NEITHER reads ``X-Archive-Orig-*`` and neither sweeps a DOMAIN.  The politeness constants, the
``parse_cdx_rows``/``select_captures`` discipline and the replay/verify pair are lifted from the
minagro leg verbatim; the origin-header rule and the paged domain sweep are NEW SPECS with their own
unit tests (``tests/unit/test_wayback_pink_sheet.py``), citing no analogue they do not have.

WHY THE CENSUS IS A DOMAIN SWEEP AND NOT A thedocs PREFIX
----------------------------------------------------------
Wayback's CDX indexes by the URL AS CRAWLED.  The CMO workbook was served from
``pubdocs.worldbank.org`` and earlier ``siteresources.worldbank.org`` before the thedocs migration,
so a ``thedocs.worldbank.org`` prefix census returns ZERO pre-2021 captures BY CONSTRUCTION -- it
would close the lane on a measurement that cannot answer the question.  The census is therefore
``matchType=domain&url=worldbank.org`` with a server-side filename filter, paged on ``resumeKey``,
and EVERY capture row records its HOST so the era-to-host map is MEASURED rather than assumed.

Usage
-----
    python jobs/ingest/backfill_pink_sheet_vintages.py --phase origin --dry-run
    python jobs/ingest/backfill_pink_sheet_vintages.py --phase origin
    python jobs/ingest/backfill_pink_sheet_vintages.py --phase wayback --census-only
    python jobs/ingest/backfill_pink_sheet_vintages.py --phase wayback --max-captures 40
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import io
import json
import logging
import sys
import time
from typing import Any, Optional

import requests
from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.common.pink_sheet_release import (
    KIND_NOT_WORKBOOK,
    KIND_OLE2,
    KIND_XLSX,
    derived_release_ym,
    expected_month_count,
    is_full_restatement,
    monthly_rows,
    release_clock,
    workbook_kind,
)
from leviathan.common.wayback import capture_drift, replay_url, served_capture_ts
from leviathan.storage.paths import raw_pink_sheet_archive_key

logger = get_logger("backfill_pink_sheet_vintages")

SOURCE = "world_bank_pink_sheet_archive"

# ---------------------------------------------------------------------------
# THE CLOSED DECLINE VOCABULARY. `sum(landed) + sum(declines) == census rows`, EXACTLY -- a capture
# that is neither landed nor declined under one of these names is an unaccounted row, and an
# unaccounted row is how a backfill claims coverage it does not have.
# ---------------------------------------------------------------------------
DECLINE_CAPTURE_DRIFT = "capture_drift"
DECLINE_UNPINNABLE_TIMESTAMP = "unpinnable_timestamp"
DECLINE_CONTENT_KEY_MISMATCH = "content_key_mismatch"
DECLINE_NOT_FULL_RESTATEMENT = "not_full_restatement"
DECLINE_EXTRACT_NARROW = "extract_narrow"
DECLINE_DUPLICATE_VALUES = "duplicate_values"
DECLINE_NON_200 = "non_200"
DECLINE_BODY_NOT_WORKBOOK = "body_not_workbook"
DECLINE_FORMAT_UNSUPPORTED = "format_unsupported"
# FIRST CAPTURE WINS is a DECLINE, not a landing. `_land` returns 'held' WITHOUT writing when the
# key already exists; counting that as landed inflates coverage and, because `landed` is keyed by
# RELEASE, silently collapses two captures of one release into one accounted row.
DECLINE_ALREADY_HELD = "already_held"

DECLINES: frozenset[str] = frozenset({
    DECLINE_CAPTURE_DRIFT, DECLINE_UNPINNABLE_TIMESTAMP, DECLINE_CONTENT_KEY_MISMATCH,
    DECLINE_NOT_FULL_RESTATEMENT, DECLINE_EXTRACT_NARROW, DECLINE_DUPLICATE_VALUES,
    DECLINE_NON_200, DECLINE_BODY_NOT_WORKBOOK, DECLINE_FORMAT_UNSUPPORTED,
    DECLINE_ALREADY_HELD,
})

# WHERE `widens_served_set` WENT, AND WHY IT WAS NEVER A HARVEST DECLINE.
# A tag named `widens_served_set` sat in this vocabulary and no code path could ever emit it: the
# widening question is "does this archived release carry governed keys that NO strictly-newer
# SCHEDULED release carries", and a harvest has no scheduled frames in hand to answer it. It is
# answered one layer down, by `served_set_census()` in jobs/batch/pink_sheet_archive_task.py, which
# reads both bronze prefixes and reports per release. It is a FINDING about an object that has
# already landed -- the object stays in raw, un-bronzed if the owner says so, and counted -- not a
# reason to refuse a capture. Leaving the tag here advertised a harvest-time guard that did not
# exist, so it is removed and its real home is named instead.
WIDENING_IS_MEASURED_IN = "jobs/batch/pink_sheet_archive_task.py::served_set_census"

# ---------------------------------------------------------------------------
# PHASE 0 -- the retired document-ID epochs.
#
# The World Bank's download URL carries an opaque document ID that rotates. A RETIRED epoch folder
# sometimes keeps serving the workbook it held when it rotated, which is a frozen vintage for free.
# It is an OBSERVED behaviour and never a promise: the WB may garbage-collect any of these at any
# time, which is why Phase 0 runs before the archive rather than after it.
#
# `probe` records what a 2026-09-03 measurement of each epoch returned. It is documentation, not a
# gate -- the run re-measures every one.
# ---------------------------------------------------------------------------
_FILENAMES: tuple[str, ...] = (
    "CMO-Historical-Data-Monthly.xlsx",     # the modern, hyphenated spelling
    "CMOHistoricalDataMonthly.xlsx",        # the pre-2020 unhyphenated spelling
)

_EPOCHS: tuple[dict[str, str], ...] = (
    {"doc_id": "18675f1d1639c7a34d463f59263ba0a2-0050012025",
     "probe": "2026-09-03: 200, 765,246 B, derives 2025M01 (n=780)"},
    {"doc_id": "5d012ca19a04946d16d528e6989f1489-0350012021",
     "probe": "2026-09-03: 200, 778,415 B, derives 2026M01 (n=792)"},
    {"doc_id": "23511bd1d63c6e6ac66b4c78d0b5c81f-0350012021",
     "probe": "2026-09-03: 404 on CMO-Historical-Data-Monthly.xlsx"},
    {"doc_id": "5d012ca19a04946d16d528e6989f1489-0050012021",
     "probe": "2026-09-03: 404 on CMO-Historical-Data-Monthly.xlsx"},
    {"doc_id": "561011486076157149-0090022016",
     "probe": "2026-09-03: 404 hyphenated; unhyphenated 200s with 100,826 B of HTML "
              "(first bytes '<!DOCTYPE') under an xlsx Content-Type -> body_not_workbook"},
)

_EPOCH_URL = "https://thedocs.worldbank.org/en/doc/{doc_id}/related/{filename}"

# ---------------------------------------------------------------------------
# PHASE 1 -- the CDX census.
#
# `.?` spans the hyphen so BOTH filename spellings match in one server-side filter.
# `showResumeKey` + the trailing resumeKey row is what makes this PAGED: a domain sweep of
# worldbank.org is not a one-call query, and budgeting it as one is how a lane discovers at run time
# that it only saw the first page.
# ---------------------------------------------------------------------------
CDX_BASE = "https://web.archive.org/cdx/search/cdx"
CDX_QUERY = (
    "?url=worldbank.org&matchType=domain"
    "&output=json&fl=timestamp,original,digest,statuscode,length"
    "&filter=statuscode:200"
    "&filter=original:.*CMO.?Historical.?Data.?Monthly.*"
    "&collapse=digest&showResumeKey=true"
)
_CDX_PAGE_LIMIT = 1000
# A hard ceiling on pages so a runaway resumeKey loop cannot spend the politeness budget forever.
# Hitting it is a FINDING (the census is incomplete and says so), never a silent stop.
_CDX_MAX_PAGES = 50

# POLITENESS -- reused VERBATIM from jobs/ingest/backfill_minagro_wayback.py. archive.org is a
# LIBRARY, not a CDN.
_SLEEP_BETWEEN_FETCHES_S = 2.5
_CDX_TIMEOUT_S = 90
_FETCH_TIMEOUT_S = 120
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = 10
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

_USER_AGENT = "Leviathan-PinkSheet-Backfill/1.0 (research; non-commercial)"
_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# The ONE header that may reach rung 1 of the clock ladder on an archive body.
ORIGIN_LAST_MODIFIED_HEADER = "X-Archive-Orig-Last-Modified"


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
                logger.warning("HTTP %d (attempt %d/%d) -- retrying in %ds: %s",
                               resp.status_code, attempt, _MAX_ATTEMPTS, backoff, url)
            else:
                resp.raise_for_status()
                return resp
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= _MAX_ATTEMPTS:
                break
            logger.warning("fetch failed (attempt %d/%d): %s -- retrying in %ds",
                           attempt, _MAX_ATTEMPTS, exc, backoff)
        time.sleep(backoff)
        backoff *= 2
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"failed to fetch {url} after {_MAX_ATTEMPTS} attempts")


# ---------------------------------------------------------------------------
# Pure helpers -- no network, no clock
# ---------------------------------------------------------------------------

def cdx_digest(payload: bytes) -> str:
    """The CDX ``digest`` form of *payload*: unpadded base32 of its SHA-1.

    PROVENANCE ONLY, never a payload check: measured on the minagro leg, the index digest matched
    only 9 of 12 served bodies, so a mismatch is a logged note and never a refusal.
    """
    return base64.b32encode(hashlib.sha1(payload).digest()).decode("ascii").rstrip("=")


def parse_cdx_rows(payload: Any) -> list[dict[str, str]]:
    """A CDX JSON body -> one dict per row, plus the trailing resume key when present.

    CDX's JSON is a HEADER ROW plus data rows, so field names are zipped on from row 0. With
    ``showResumeKey=true`` the LAST row is a one-element list carrying the key (preceded by a blank
    row); it is returned separately by :func:`split_resume_key`, never mistaken for a capture.
    An empty index answers ``[]`` -- "the archive holds nothing" is a real answer, not an error.
    """
    if isinstance(payload, (bytes, bytearray, str)):
        payload = json.loads(payload)
    if not payload or len(payload) < 2:
        return []
    fields = payload[0]
    out: list[dict[str, str]] = []
    for row in payload[1:]:
        if not row or len(row) != len(fields):
            continue                      # the blank row / resume-key row are not captures
        out.append(dict(zip(fields, row)))
    return out


def split_resume_key(payload: Any) -> Optional[str]:
    """The trailing ``resumeKey`` of a paged CDX answer, or ``None`` when the page is the last one.

    The key rides as the FINAL row, a one-element list, separated from the data by a blank row. Its
    absence is what ends the loop -- not a page-size heuristic, which would stop early on a page
    that happened to come back short.
    """
    if isinstance(payload, (bytes, bytearray, str)):
        payload = json.loads(payload)
    if not payload:
        return None
    tail = payload[-1]
    if isinstance(tail, list) and len(tail) == 1 and str(tail[0]).strip():
        return str(tail[0]).strip()
    return None


def capture_host(original: str) -> str:
    """The HOST a capture was crawled from, so the era-to-host map is MEASURED, not assumed."""
    text = str(original or "")
    if "//" in text:
        text = text.split("//", 1)[1]
    return text.split("/", 1)[0].lower()


def select_captures(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """CDX rows -> the captures worth fetching: HTTP 200, pinnable timestamp, one per digest.

    Pure. The server-side ``filter``/``collapse`` already do most of this and it is re-done anyway:
    ``collapse=digest`` is an ADJACENT-RUN collapse, so a digest that recurs later in the ordering
    still arrives twice, and an unpinnable timestamp must never become a replay request -- that is
    precisely the CEPEA failure mode.  The EARLIEST capture of each state is kept: it is the closest
    witness to the release that produced it.
    """
    seen: dict[str, dict[str, str]] = {}
    for row in rows:
        if str(row.get("statuscode") or "") != "200":
            continue
        ts = str(row.get("timestamp") or "")
        if len(ts) != 14 or not ts.isdigit():
            logger.warning("CDX row with an unusable timestamp %r -- skipped: a capture that "
                           "cannot be pinned must never become a replay request", ts[:32])
            continue
        digest = str(row.get("digest") or "")
        if not digest:
            logger.warning("CDX row %s carries no digest -- skipped: without it there is no way to "
                           "tell one page state from a re-crawl of the same one", ts)
            continue
        original = str(row.get("original") or "")
        prior = seen.get(digest)
        if prior is None or ts < prior["timestamp"]:
            seen[digest] = {
                "timestamp": ts,
                "digest": digest,
                "original": original,
                "host": capture_host(original),
                "statuscode": "200",
                "length": str(row.get("length") or ""),
            }
    out = sorted(seen.values(), key=lambda c: c["timestamp"])
    for cap in out:
        cap["replay_url"] = replay_url(cap["timestamp"], cap["original"])
    return out


def value_matrix_hash(xlsx_bytes: bytes) -> str:
    """A hash of the PARSED 'Monthly Prices' value matrix -- the de-duplication key.

    NEVER raw bytes.  The World Bank regenerates the workbook without changing the data: the display
    regime moved from full float to 2 decimals between 2026M05 and 2026M07 and the file went
    783,157 -> 575,636 bytes.  Two byte-different objects can be one vintage, and landing that
    vintage twice under two months is exactly what this prevents.  The CDX digest stays provenance.
    """
    import pandas as pd

    frame = pd.read_excel(io.BytesIO(xlsx_bytes), sheet_name="Monthly Prices", header=4,
                          engine="openpyxl")
    first = frame.columns[0]
    mask = frame[first].astype(str).str.match(r"^\d{4}M\d{2}$")
    frame = frame.loc[mask.fillna(False)].copy()
    frame = frame.sort_values(first)
    payload = frame.to_csv(index=False, float_format="%.10g").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def capture_date(timestamp: str) -> dt.date:
    """The calendar date of a 14-digit CDX timestamp."""
    return dt.date(int(timestamp[:4]), int(timestamp[4:6]), int(timestamp[6:8]))


def classify_body(body: bytes) -> Optional[str]:
    """``None`` when these bytes are an xlsx, else the decline tag naming what they are instead."""
    kind = workbook_kind(body)
    if kind == KIND_XLSX:
        return None
    if kind == KIND_OLE2:
        return DECLINE_FORMAT_UNSUPPORTED
    if kind == KIND_NOT_WORKBOOK:
        return DECLINE_BODY_NOT_WORKBOOK
    return DECLINE_BODY_NOT_WORKBOOK


def release_within_capture_bound(release_date_iso: str, timestamp: str) -> Optional[str]:
    """``None`` when the derived release date is on or before the capture, else why it is refused.

    A workbook cannot have been published AFTER the crawl that captured it.  The capture timestamp
    is a WITNESS BOUND, never the release month.
    """
    captured = capture_date(timestamp)
    released = dt.date.fromisoformat(release_date_iso)
    if released > captured:
        return (f"the derived release date {release_date_iso} is AFTER capture {timestamp} "
                f"({captured.isoformat()}) -- a workbook cannot be published after the crawl that "
                f"archived it, so either the derived clock or the capture pin is wrong")
    return None


# ---------------------------------------------------------------------------
# PHASE 0 -- origin epochs
# ---------------------------------------------------------------------------

def origin_plan() -> list[dict[str, str]]:
    """Every (epoch, filename) URL Phase 0 will probe, in order. Pure."""
    return [
        {"doc_id": epoch["doc_id"], "filename": filename, "probe": epoch["probe"],
         "url": _EPOCH_URL.format(doc_id=epoch["doc_id"], filename=filename)}
        for epoch in _EPOCHS
        for filename in _FILENAMES
    ]


def _land(
    body: bytes,
    release_ym: str,
    filename: str,
    *,
    bucket: str,
    aws_region: str,
    source_url: str,
    extra: dict[str, Any],
    force: bool,
) -> tuple[str, str]:
    """FIRST CAPTURE WINS.  ``('landed'|'held', key)``.

    An existing object is NEVER overwritten without ``--force``: raw is the asset and immutable by
    contract, and an archived re-render is not an improvement on bytes already held.
    """
    from leviathan.storage.raw_metadata import write_raw_s3_metadata
    from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

    key = raw_pink_sheet_archive_key(release_ym, filename)
    if s3_object_exists(bucket, key, aws_region) and not force:
        logger.info("already held (first capture wins) -- not overwriting: %s", key)
        return "held", key
    upload_bytes_to_s3(body, bucket, key, aws_region)
    write_raw_s3_metadata(bucket, key, body, source_url, _CONTENT_TYPE, aws_region, extra=extra)
    logger.info("landed %s (%d bytes)", key, len(body))
    return "landed", key


def run_origin(args: argparse.Namespace) -> int:
    """Phase 0: the retired document-ID epochs. No archive traffic, no politeness budget."""
    plan = origin_plan()
    if args.dry_run:
        print(f"epochs     : {len(_EPOCHS)}")
        print(f"urls       : {len(plan)}  (each epoch x both filename spellings)")
        for item in plan:
            print(f"  {item['url']}")
            print(f"      prior probe: {item['probe']}")
        print("(dry-run -- NOTHING was fetched and no S3 write was attempted)")
        print("release months are NOT predicted here: the month is a property of the BYTES, and")
        print("naming a key nobody has read out of a workbook is the habit the content key forbids.")
        return 0

    load_env()
    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    landed: dict[str, str] = {}                 # release_ym -> url that won it
    landed_probes: list[dict[str, str]] = []    # one entry per URL that actually WROTE
    declines: list[dict[str, str]] = []
    seen_values: dict[str, str] = {}            # value-matrix hash -> release_ym
    attempted = 0

    for item in plan:
        url = item["url"]
        attempted += 1
        logger.info("origin probe: %s", url)
        try:
            resp = _http_get(url, timeout=_FETCH_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 -- a 404 on a retired epoch is an ANSWER
            declines.append({"url": url, "decline": DECLINE_NON_200, "detail": str(exc)[:200]})
            logger.info("  -> %s (%s)", DECLINE_NON_200, str(exc)[:120])
            continue
        body = resp.content
        bad = classify_body(body)
        if bad:
            declines.append({"url": url, "decline": bad,
                             "detail": f"{len(body)} bytes, first 8 {body[:8]!r}"})
            logger.warning("  -> %s (%d bytes, first 8 %r)", bad, len(body), body[:8])
            continue
        try:
            release = derived_release_ym(body)
            months = monthly_rows(body)
        except Exception as exc:  # noqa: BLE001
            declines.append({"url": url, "decline": DECLINE_CONTENT_KEY_MISMATCH,
                             "detail": str(exc)[:200]})
            logger.warning("  -> %s (%s)", DECLINE_CONTENT_KEY_MISMATCH, str(exc)[:160])
            continue
        if not is_full_restatement(months):
            declines.append({"url": url, "decline": DECLINE_NOT_FULL_RESTATEMENT,
                             "detail": f"derives {release}, {len(months)} rows vs "
                                       f"{expected_month_count(release)} expected"})
            logger.warning("  -> %s (%s: %d rows vs %d)", DECLINE_NOT_FULL_RESTATEMENT,
                           release, len(months), expected_month_count(release))
            continue
        vhash = value_matrix_hash(body)
        if vhash in seen_values:
            declines.append({"url": url, "decline": DECLINE_DUPLICATE_VALUES,
                             "detail": f"same parsed values as {seen_values[vhash]}"})
            logger.info("  -> %s (same parsed values as %s)", DECLINE_DUPLICATE_VALUES,
                        seen_values[vhash])
            continue

        last_modified = resp.headers.get("Last-Modified")
        release_date, clock_source = release_clock(release, body,
                                                   http_last_modified=last_modified)
        status, key = _land(
            body, release, item["filename"], bucket=bucket, aws_region=aws_region,
            source_url=url, force=args.force,
            extra={
                "source": SOURCE,
                "capture_kind": "origin_retired_epoch",
                "backfill_job": "backfill_pink_sheet_vintages",
                "backfill_phase": "origin",
                "derived_release_ym": release,
                "expected_month_count": expected_month_count(release),
                "observed_month_count": len(months),
                "is_full_restatement": True,
                "release_date": release_date,
                "release_date_source": clock_source,
                "http_last_modified": last_modified,
                # An origin-phase fetch reaches the World Bank itself, so its Last-Modified IS the
                # origin header: record it under the ONE key the vintages task reads on the archive
                # prefix (`origin_last_modified`), or every pre-Wayback vintage silently takes rung 2
                # (re-review 2026-09-04). LAW 4 is intact -- this is not the archive's clock.
                "origin_last_modified": last_modified,
                "http_content_length": resp.headers.get("Content-Length"),
                "value_matrix_sha256": vhash,
                "body_sha256": hashlib.sha256(body).hexdigest(),
            },
        )
        if status == "held":
            # NOTHING WAS WRITTEN. First capture wins, so this probe is a counted decline and the
            # value hash is not banked against the release it did not land.
            declines.append({"url": url, "decline": DECLINE_ALREADY_HELD,
                             "detail": f"{key} already held; first capture wins"})
            logger.info("  -> %s %s release=%s (nothing written)",
                        DECLINE_ALREADY_HELD, key, release)
            continue
        seen_values[vhash] = release
        landed[release] = url
        landed_probes.append({"release_ym": release, "url": url, "key": key})
        logger.info("  -> %s %s release=%s n=%d clock=%s/%s",
                    status, key, release, len(months), release_date, clock_source)
        if args.limit and len(landed) >= args.limit:
            break

    print(json.dumps({
        "phase": "origin",
        "urls_probed": len(plan),
        # ATTEMPTED, not planned: --limit breaks the loop early, so `len(plan)` is not the
        # denominator the identity balances against.
        "attempted": attempted,
        "landed": sorted(landed),
        "n_landed_probes": len(landed_probes),
        "n_releases_landed": len(landed),
        "landed_probes": landed_probes,
        "declines": declines,
        "n_declines": len(declines),
        # THE IDENTITY: every URL ATTEMPTED is either landed or declined under a named tag. It is
        # counted over ATTEMPTS, never over releases -- two URLs can win one release, and a
        # release-keyed tally silently collapses them.
        "accounted": len(landed_probes) + len(declines),
        "identity_holds": (len(landed_probes) + len(declines)) == attempted,
        "unknown_tags": sorted({d["decline"] for d in declines} - DECLINES),
        "widening_measured_in": WIDENING_IS_MEASURED_IN,
    }, indent=1))
    return 0


# ---------------------------------------------------------------------------
# PHASE 1 -- the archive
# ---------------------------------------------------------------------------

def census_pages(fetch=None) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Walk the paged worldbank.org DOMAIN census. Returns (rows, report).

    ``fetch`` is the HTTP seam (defaults to :func:`_http_get`) so a test can drive two pages and a
    terminating page with no network. The loop ends when a page carries NO resume key -- never on a
    short page, which is a page-size heuristic and stops early.
    """
    fetch = fetch or (lambda url: _http_get(url, timeout=_CDX_TIMEOUT_S))
    rows: list[dict[str, str]] = []
    pages = 0
    resume: Optional[str] = None
    truncated = False
    while True:
        url = f"{CDX_BASE}{CDX_QUERY}&limit={_CDX_PAGE_LIMIT}"
        if resume:
            url += f"&resumeKey={resume}"
        logger.info("CDX page %d: %s", pages + 1, url)
        payload = fetch(url)
        body = getattr(payload, "content", payload)
        rows.extend(parse_cdx_rows(body))
        pages += 1
        resume = split_resume_key(body)
        if not resume:
            break
        if pages >= _CDX_MAX_PAGES:
            # A FINDING, not a silent stop: the census is incomplete and every downstream number
            # derived from it is a floor.
            truncated = True
            logger.error("CDX census hit the %d-page ceiling with a resume key still present -- "
                         "the census is INCOMPLETE and its counts are FLOORS, not totals",
                         _CDX_MAX_PAGES)
            break
        time.sleep(_SLEEP_BETWEEN_FETCHES_S)

    captures = select_captures(rows)
    by_host: dict[str, int] = {}
    by_year: dict[str, int] = {}
    for cap in captures:
        by_host[cap["host"]] = by_host.get(cap["host"], 0) + 1
        by_year[cap["timestamp"][:4]] = by_year.get(cap["timestamp"][:4], 0) + 1
    report = {
        "pages": pages,
        "truncated": truncated,
        "cdx_rows": len(rows),
        "distinct_captures": len(captures),
        "distinct_digests": len({c["digest"] for c in captures}),
        "earliest_capture": captures[0]["timestamp"] if captures else None,
        "latest_capture": captures[-1]["timestamp"] if captures else None,
        "by_host": dict(sorted(by_host.items())),
        "by_year": dict(sorted(by_year.items())),
    }
    return captures, report


def fetch_capture(cap: dict[str, str], fetch=None) -> tuple[Optional[bytes], Optional[str],
                                                            dict[str, Any]]:
    """Replay ONE capture. ``(body|None, decline|None, meta)``.

    The order is the cheapest true statement first: verify the SERVED capture is the PINNED one
    (law 3), then the magic bytes (law 1), then the content key (law 2), then the capture bound.
    """
    fetch = fetch or (lambda url: _http_get(url, timeout=_FETCH_TIMEOUT_S))
    meta: dict[str, Any] = {"pinned_capture_ts": cap["timestamp"], "host": cap.get("host")}
    try:
        resp = fetch(cap["replay_url"])
    except Exception as exc:  # noqa: BLE001
        meta["detail"] = str(exc)[:200]
        return None, DECLINE_NON_200, meta

    try:
        served = served_capture_ts(resp)
    except ValueError as exc:
        # The response disagrees with ITSELF (URL vs Memento-Datetime) -- provenance cannot be
        # established at all, which is the drift class by another route.
        meta["detail"] = str(exc)[:200]
        return None, DECLINE_CAPTURE_DRIFT, meta
    meta["served_capture_ts"] = served
    drift = capture_drift(cap["timestamp"], served, what="this archived workbook")
    if drift:
        meta["detail"] = drift
        return None, DECLINE_CAPTURE_DRIFT, meta

    body = resp.content
    bad = classify_body(body)
    if bad:
        meta["detail"] = f"{len(body)} bytes, first 8 {body[:8]!r}"
        return None, bad, meta

    try:
        release = derived_release_ym(body)
        months = monthly_rows(body)
    except Exception as exc:  # noqa: BLE001
        meta["detail"] = str(exc)[:200]
        return None, DECLINE_CONTENT_KEY_MISMATCH, meta
    meta["derived_release_ym"] = release
    meta["observed_month_count"] = len(months)
    meta["expected_month_count"] = expected_month_count(release)
    if not is_full_restatement(months):
        return None, DECLINE_NOT_FULL_RESTATEMENT, meta

    # LAW 4: on an archive body, ONLY the origin header may reach rung 1. The replay's own
    # Last-Modified is the ARCHIVE's; passing it here would stamp the CRAWL date as release_date
    # under a token asserting it came from the origin.
    origin_lm = (getattr(resp, "headers", None) or {}).get(ORIGIN_LAST_MODIFIED_HEADER)
    release_date, clock_source = release_clock(release, body, http_last_modified=origin_lm,
                                               archive=True)
    meta["release_date"] = release_date
    meta["release_date_source"] = clock_source
    meta["origin_last_modified"] = origin_lm
    meta["archive_last_modified_IGNORED"] = (getattr(resp, "headers", None) or {}).get(
        "Last-Modified")

    bound = release_within_capture_bound(release_date, cap["timestamp"])
    if bound:
        meta["detail"] = bound
        return None, DECLINE_CONTENT_KEY_MISMATCH, meta

    meta["cdx_digest"] = cap.get("digest")
    meta["cdx_payload_digest"] = cdx_digest(body)
    if meta["cdx_digest"] and meta["cdx_payload_digest"] != meta["cdx_digest"]:
        # PROVENANCE ONLY -- measured 9/12 on the minagro leg. A note, never a refusal.
        logger.info("capture %s: CDX digest %s != recomputed %s (provenance note only)",
                    cap["timestamp"], meta["cdx_digest"], meta["cdx_payload_digest"])
    return body, None, meta


def run_wayback(args: argparse.Namespace) -> int:
    """Phase 1: the paged domain census, then bounded harvests."""
    captures, report = census_pages()
    logger.info("census: %s", json.dumps(report))

    if args.census_only or args.dry_run:
        print(json.dumps({"phase": "wayback", "census": report,
                          "captures": [{k: c[k] for k in ("timestamp", "host", "digest",
                                                          "original", "length")}
                                       for c in captures]}, indent=1))
        print("(census only -- NO capture bodies were fetched and no S3 write was attempted)")
        print("release months are NOT predicted here: the month is a property of the BYTES.")
        return 0

    if not captures:
        logger.error("ZERO CAPTURES: the worldbank.org domain census holds no 200-status capture "
                     "of either filename spelling. The pre-2021 history is NOT recoverable from "
                     "the archive -- that is a FINDING, not a success, so this run is not green")
        return 1

    todo = captures[: args.max_captures] if args.max_captures else captures
    logger.info("harvesting %d of %d capture(s) (bounded on purpose: a run that dies at 280 of 300 "
                "with no manifest is the shape of failure to avoid)", len(todo), len(captures))

    load_env()
    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    # THE UNIT OF ACCOUNT IS THE ATTEMPT, NEVER THE RELEASE. `landed` was a dict keyed by release,
    # so two captures of one release collapsed into one accounted row and the identity below read
    # False on a perfectly normal harvest -- exactly the shape the World Bank's own measured
    # same-month regeneration produces. `landed_captures` counts CAPTURES; `landed` keeps the
    # release -> timestamp map for the human-readable roster.
    landed: dict[str, str] = {}
    landed_captures: list[dict[str, str]] = []
    declines: list[dict[str, Any]] = []
    seen_values: dict[str, str] = {}

    for i, cap in enumerate(todo):
        if i:
            time.sleep(_SLEEP_BETWEEN_FETCHES_S)
        body, decline, meta = fetch_capture(cap)
        if decline:
            declines.append({"timestamp": cap["timestamp"], "decline": decline, **meta})
            logger.warning("capture %s -> %s (%s)", cap["timestamp"], decline,
                           str(meta.get("detail", ""))[:160])
            continue
        release = str(meta["derived_release_ym"])
        vhash = value_matrix_hash(body)
        if vhash in seen_values:
            declines.append({"timestamp": cap["timestamp"], "decline": DECLINE_DUPLICATE_VALUES,
                             "detail": f"same parsed values as {seen_values[vhash]}", **meta})
            logger.info("capture %s -> %s (same parsed values as %s)", cap["timestamp"],
                        DECLINE_DUPLICATE_VALUES, seen_values[vhash])
            continue
        status, key = _land(
            body, release, _FILENAMES[0], bucket=bucket, aws_region=aws_region,
            source_url=cap["replay_url"], force=args.force,
            extra={
                "source": SOURCE,
                "capture_kind": "wayback_replay",
                "backfill_job": "backfill_pink_sheet_vintages",
                "backfill_phase": "wayback",
                "origin_url": cap["original"],
                "replay_url": cap["replay_url"],
                "wayback_capture_ts": cap["timestamp"],
                "wayback_served_capture_ts": meta.get("served_capture_ts"),
                "value_matrix_sha256": vhash,
                "body_sha256": hashlib.sha256(body).hexdigest(),
                "is_full_restatement": True,
                **{k: meta[k] for k in
                   ("derived_release_ym", "expected_month_count", "observed_month_count",
                    "release_date", "release_date_source", "origin_last_modified",
                    "cdx_digest", "cdx_payload_digest") if k in meta},
            },
        )
        if status == "held":
            # NOT A LANDING. `_land` wrote nothing -- the key was already there and first capture
            # wins -- so this capture is a counted DECLINE, and the value hash is NOT banked: a
            # discarded capture must not claim a release's duplicate-value slot.
            declines.append({"timestamp": cap["timestamp"], "decline": DECLINE_ALREADY_HELD,
                             "detail": f"{key} already held; first capture wins", **meta})
            logger.info("capture %s -> %s %s release=%s (nothing written)", cap["timestamp"],
                        DECLINE_ALREADY_HELD, key, release)
            continue
        seen_values[vhash] = release
        landed[release] = cap["timestamp"]
        landed_captures.append({"release_ym": release, "timestamp": cap["timestamp"], "key": key})
        logger.info("capture %s -> %s %s release=%s clock=%s/%s", cap["timestamp"], status, key,
                    release, meta.get("release_date"), meta.get("release_date_source"))

    by_tag: dict[str, int] = {}
    for row in declines:
        by_tag[row["decline"]] = by_tag.get(row["decline"], 0) + 1
    print(json.dumps({
        "phase": "wayback",
        "census": report,
        "attempted": len(todo),
        "landed": sorted(landed),
        # BOTH NUMBERS, NAMED APART: `n_landed_captures` is what the identity balances against
        # `attempted`; `n_releases_landed` is how many DISTINCT vintages those captures represent.
        # They differ whenever one release lands from more than one capture, and reporting only the
        # second made the identity read False on a normal harvest.
        "n_landed_captures": len(landed_captures),
        "n_releases_landed": len(landed),
        "landed_captures": landed_captures,
        "declines_by_tag": dict(sorted(by_tag.items())),
        "n_declines": len(declines),
        # THE IDENTITY, and it must hold EXACTLY: every ATTEMPTED capture is landed or declined
        # under a name from the closed vocabulary.
        "accounted": len(landed_captures) + len(declines),
        "identity_holds": (len(landed_captures) + len(declines)) == len(todo),
        "unknown_tags": sorted(set(by_tag) - DECLINES),
        "widening_measured_in": WIDENING_IS_MEASURED_IN,
    }, indent=1))
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Backfill World Bank Pink Sheet vintages into the ARCHIVE raw prefix. Phase "
                     "'origin' probes retired document-ID epochs ($0, no archive traffic); phase "
                     "'wayback' runs the paged worldbank.org DOMAIN census and bounded harvests."))
    parser.add_argument("--phase", choices=["origin", "wayback"], required=True)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the plan (origin) or the census (wayback). No body fetches on "
                             "origin, no body fetches and no S3 writes on either.")
    parser.add_argument("--census-only", action="store_true", dest="census_only",
                        help="wayback: run the paged CDX census and print it. Fetches NO bodies.")
    parser.add_argument("--max-captures", type=int, default=0, dest="max_captures",
                        help="wayback: harvest at most N captures. Run in bounded batches -- a run "
                             "that lands 40 vintages is recoverable where a 300-capture run that "
                             "dies at 280 with no manifest is not.")
    parser.add_argument("--limit", type=int, default=0,
                        help="origin: stop after N landed vintages (smoke tests).")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite an already-landed release key. Use ONLY to repair a "
                             "known-bad object: first capture wins, and an archived re-render is "
                             "not an improvement on bytes already held.")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        stream=sys.stderr)
    args = _parse_args(argv)
    if args.phase == "origin":
        return run_origin(args)
    return run_wayback(args)


if __name__ == "__main__":
    raise SystemExit(main())
