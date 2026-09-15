"""Fetch USDA FAS World Agricultural Production (WAP) monthly PDFs to raw S3.

Published once a month (same day as WASDE, ~10th of each month) by USDA FAS.
Each release is a single PDF covering wheat, corn, rice, soybeans, cotton and
other oilseeds with country-level area / production / trade estimates.

Source
------
    https://www.fas.usda.gov/data/world-agricultural-production
    report_type = 13286  (manifest: 289 entries, 2002-08 .. 2026-09, as of 2026-09-15)

URL patterns
------------
    Recent (2025-present): {CDN}/{YYYY-MM}/production.pdf
    2024:                  {CDN}/{YYYY-MM}/production - {Month} {YYYY}.pdf
    Pre-2024:              {CDN}/{migration-date}/{YYYY}-{Mon}-{Production|WAP}.pdf

    The CDN folder and filename vary unpredictably across years because USDA
    did a bulk CDN migration in mid-2025.  The only reliable approach is to
    scrape each report's landing page to obtain the actual PDF URL.
    Landing pages are Akamai-protected; uses ``curl_cffi`` with Chrome
    impersonation to bypass bot-detection.

S3 key structure
----------------
    raw/production/source=usda_wap/release_month={YYYY-MM}/production.pdf

Modes
-----
--discover
    Paginate the FAS search results for report type 13286 to collect all
    WAP landing-page URLs, then fetch each landing page to extract the real
    PDF download URL (which varies across years due to the 2025 CDN
    migration).  Results are written to
    ``configs/sources/usda_wap_manifest.yaml``.  No AWS credentials required.

Normal (no --discover)
    Load the manifest, probe the INCREMENTAL TAIL (below), and download/upload
    each PDF to raw S3.

The incremental tail (2026-09-15)
---------------------------------
THE FREEZE THIS CLOSES, measured.  The scheduled run iterated the manifest and
nothing else, and the manifest was last rebuilt 2026-07-17, so its newest entry
was 2026-07.  The August circular (published 2026-08-12) and the September one
(2026-09-11) were never enumerated on any fire, and canonical
``silver/wap_table01_revisions`` sat at max ``release_month`` 2026-07 from
2026-08-14 onward -- 42 days -- while every instrument in the estate reported
the family healthy.  The fetch job's own log said ``errors=0`` each time,
truthfully: it wrote every month it was told about.

So after the manifest loads, every month STRICTLY AFTER its newest entry up to
and including the current month is HEAD-probed at the modern CDN path
``{CDN}/{YYYY-MM}/production.pdf``.  A found month is appended IN MEMORY ONLY
and fetched in the same run through the SAME ``_upload_entry`` -- one key
function, one validation path.  ``_save_manifest`` is never called here: the
manifest is a tracked file baked into the worker image, so a container write is
lost on exit, which would be a fix that appears to work once and then silently
stops.

Three outcomes, and the difference between the last two is the whole point:

    found        HTTP 200 -- fetched this run.
    declined     HTTP 404/410 -- USDA has not published that month yet.  Normal
                 on the 12th; counted and NAMED with the URL that was tried, so
                 a CDN reorganisation reads as a decline nobody has to guess at.
    unreachable  403 / 5xx / timeout / DNS -- we could not ASK.  NEVER read as
                 "not published": no month is appended, the manifest months
                 still fetch to completion, and the list is NAMED in the
                 tripwire's exit message so an operator reading a STALE-SOURCE
                 failure can tell "USDA stopped" from "Akamai stopped us".

Measured 2026-09-15 from a laptop: 2026-08 -> 200, 1,645,992 B; 2026-09 -> 200,
21,431,027 B; 2026-10 -> a clean 404.  ``--discover`` is UNCHANGED and remains
the manifest-rebuild lane, run by hand from a host FAS admits -- the search
pagination and the report home page both return Akamai 403 to a laptop.

Staleness tripwire
------------------
Nothing in the estate could see that freeze.  The freshness alarm reads S3
object mtime and the silver task rewrites its shadow object on every fire, so
the lag read ~0 on a 42-day-stale table; the gate's data-freshness stage is
dark and ``year_month``-keyed while this card is ``vintage``; and the parity
stage's own docstring concedes that identically-wrong-on-both-backends is a
clean PASS.  So the fetcher carries its own: when the newest release month this
run LANDED IN RAW S3 is two or more months behind the wall clock, everything
fetchable is written first and the run then exits non-zero, stopping the chain
before the promote and lighting the existing ``BatchJobFailed`` alarm.  ONE
month behind is normal before publication and never trips.

IT READS THE WRITE, NOT THE PROBE.  The first version of this instrument read
the HEAD probe, so a tail month that was FOUND and then failed to download still
counted as progress: the run logged ``PASS``, exited 0, and the raw prefix stood
still -- this same freeze through a different door, and permanent, because the
next month counted two such months as progress.  The whole outcome set now lives
in one pure function (``_tail_verdict``): a found month that was not written is
``UNLANDED-TAIL`` and exits non-zero whether a failed fetch or this run's own
``--limit``/``--year-to`` is why; a run that landed nothing newer than the
threshold is ``STALE-SOURCE``; a hand run that NARROWED its own scope gets the
verdict logged and not acted on.  Any ``error`` at all is non-zero on its own,
before the staleness verdict is even computed.  Disarmed only by ``--no-tail``
or ``--no-tail-tripwire``: an ``unreachable`` probe no longer buys silence,
because this instrument measures whether OUR PREFIX IS ADVANCING, which is
equally untrue whether USDA stopped publishing or Akamai stopped answering.  The
fail-open lives in the threshold instead, where a single fire's outage leaves
the newest written month one behind and never trips.

Idempotency
-----------
``--skip-existing-s3`` is ON BY DEFAULT since 2026-09-15.  It was already on the
jobdef's default command, but the deployed submission replaces the command array
wholesale with just the script path, so the flag never reached argparse and all
287 manifest PDFs (1,051,731,539 bytes) were re-downloaded from fas.usda.gov on
every fire.  The code default is the only lever that survives that override.
Pass ``--no-skip-existing-s3`` to force a re-download.
Pass ``--dry-run`` to print S3 keys and the predicted tripwire verdict without
downloading anything or touching AWS (the tail's HEAD probes still fire; add
``--no-tail`` for a preview that makes no network calls at all).
"""
from __future__ import annotations

import argparse
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from curl_cffi import requests as cr

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_wap_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CDN_BASE = "https://www.fas.usda.gov/sites/default/files"
_PDF_MAGIC = b"%PDF"
_REQUEST_TIMEOUT_S = 60

# (_START_YM = (2003, 1) lived here with the comment "earliest month to probe". It had NO consumer
# anywhere in the repo, and the fact it stated was wrong besides: the manifest starts 2002-08. A
# constant nobody reads and nobody can be wrong-footed by is still a wrong fact sitting in the file,
# so it is deleted rather than corrected -- the tail below probes FORWARD from the manifest's own
# newest entry and has no need of a floor.)

_IMPERSONATE = "chrome136"

# ---------------------------------------------------------------------------
# The incremental tail (see the module docstring for the freeze it closes)
# ---------------------------------------------------------------------------

_TAIL_FILENAME = "production.pdf"
_TAIL_HEAD_TIMEOUT_S = 30
# HARD CAP on how many months ONE run will probe. The tail starts at the manifest's newest entry
# + 1, so an image whose baked-in manifest has gone stale by years must not turn a single fire into
# an unbounded 404 walk. Six months is two full quarters of slack over a monthly cadence; past that
# the manifest itself is the thing to repair (--discover from a host FAS admits), and the run says
# so instead of pretending the newest six are the whole gap.
_TAIL_MAX_MONTHS = 6

# The tripwire threshold, in WHOLE MONTHS behind the wall clock. 1 is NORMAL and must never trip: a
# circular for month M is published on the 8th-12th of M and this chain fires at 18:00Z on days
# 12-14, so on the 12th the newest reachable month is legitimately M-1. 2 is a freeze.
_TAIL_FREEZE_MONTHS = 2

_TAIL_FOUND = "found"
_TAIL_DECLINED = "declined"
_TAIL_UNREACHABLE = "unreachable"

# The tripwire's five verdicts, decided in ONE pure function (`_tail_verdict`) from facts measured
# AFTER the upload loop. They are constants and not bare strings because two call sites read them --
# the live run and the --dry-run preview -- and a preview that predicts a different word than the
# run emits is a preview nobody can trust.
_V_PASS = "PASS"
_V_STALE = "STALE-SOURCE"
_V_UNLANDED = "UNLANDED-TAIL"
_V_REPORT_ONLY = "REPORT-ONLY"
_V_DISARMED = "DISARMED"

# A REPORT, NOT A FENCE. `MIN_RAW_FILE_SIZES` carries no `usda_wap` entry, so `check_min_file_size`
# -- which reads like validation at its call site below -- is a NO-OP for this source and the only
# real validation is the 4-byte %PDF magic. ELEVEN raw objects sit under the 100,000-byte floor
# below (measured 2026-09-15 over the whole raw prefix, against a 1.6-26 MB norm): the smallest is
# 1999-09 at 6,463 B; 2025-10 at 19,090 B and 2025-11 at 29,106 B are two of the eight release
# months absent from silver; the rest are 2005-2006 circulars of 39-99 KB. Re-fetching them cannot help
# (their manifest URLs are wrong, so the same wrong bytes come back forever), so this floor never
# REFUSES a download: it NAMES one, on the way in, while an operator is still reading the log.
# Raising a real floor belongs in `src/leviathan/storage/raw_metadata.py`, which is another lane's
# file -- proposed there, not edited here.
_SUSPICIOUS_PDF_BYTES = 100_000

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent
    / "configs"
    / "sources"
    / "usda_wap_manifest.yaml"
)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_pdf(data: bytes, url: str) -> None:
    if data[:4] != _PDF_MAGIC:
        raise RuntimeError(
            f"Response from {url} is not a PDF (got {data[:4]!r})"
        )


def _fetch(url: str, timeout: int = _REQUEST_TIMEOUT_S, stream: bool = False) -> cr.Response:
    """GET with Chrome impersonation (curl_cffi) to bypass Akamai bot detection."""
    return cr.get(url, impersonate=_IMPERSONATE, timeout=timeout,
                  allow_redirects=True, stream=stream)


def _head(url: str, timeout: int = _TAIL_HEAD_TIMEOUT_S) -> cr.Response:
    """HEAD with Chrome impersonation -- headers only, no body.

    Split from ``_fetch`` on purpose: the tail asks "does this month exist" 1-6 times a run and
    must not pull a 21 MB body to answer it, and keeping the two verbs in separate functions lets a
    test stub the probe without stubbing the download (and the reverse), which is how the
    found/declined/unreachable directions get driven with no network at all.
    """
    return cr.head(url, impersonate=_IMPERSONATE, timeout=timeout, allow_redirects=True)


# ---------------------------------------------------------------------------
# Incremental tail -- pure month arithmetic first, so the whole RULE is unit-testable
# ---------------------------------------------------------------------------

def _today_ym() -> str:
    """The current release month, read in UTC. The run's ONE clock read, in one patchable place.

    UTC and not ``date.today()``: Batch runs UTC and the owner's laptop is UTC+3, so a hand run
    between 21:00Z and midnight on the last day of a month read the NEXT month -- one
    guaranteed-404 probe, and the tripwire's reference month shifted by one. The 18:00Z day-12-14
    schedule never sits near that boundary, so this was hygiene rather than a live defect; removing
    the class costs one line and stops it being re-reasoned about.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _ym_to_int(ym: str) -> int:
    """'YYYY-MM' -> a month ordinal. Pure."""
    y, m = ym.split("-")
    return int(y) * 12 + (int(m) - 1)


def _int_to_ym(n: int) -> str:
    """The inverse of :func:`_ym_to_int`. Pure."""
    return "%04d-%02d" % (n // 12, n % 12 + 1)


def _ym_behind(ym: str, today_ym: str) -> int:
    """Whole months ``ym`` sits BEHIND ``today_ym`` (negative if ahead). Pure."""
    return _ym_to_int(today_ym) - _ym_to_int(ym)


def _tail_months(max_manifest_ym: str, today_ym: str, cap: int = _TAIL_MAX_MONTHS) -> list[str]:
    """Every 'YYYY-MM' STRICTLY AFTER the manifest's newest entry, up to and including the current
    month, oldest first, at most ``cap`` of them. Pure.

    Two boundaries, both load-bearing. Starting strictly AFTER the manifest's max is what keeps a
    fire from re-probing 289 months it already knows; stopping AT the current month is what keeps
    it from walking forward into an unbounded run of 404s. When the manifest is already current
    (max == today) the answer is the empty list, and the caller says so and probes nothing.

    When the gap exceeds ``cap`` the NEWEST ``cap`` months are returned, not the oldest: currency
    is the thing this instrument exists for, and the caller WARNs that the older half of the gap
    needs a manifest refresh rather than leaving it to be inferred from a short list.
    """
    start = _ym_to_int(max_manifest_ym) + 1
    end = _ym_to_int(today_ym)
    if end < start:
        return []
    months = [_int_to_ym(n) for n in range(start, end + 1)]
    return months[-cap:] if cap and len(months) > cap else months


def _cdn_tail_url(ym: str) -> str:
    """The modern FAS CDN path for a release month: ``{CDN}/{YYYY-MM}/production.pdf``.

    MEASURED, and the caveat below is this mechanism's own failure mode, stated rather than
    guessed. The pattern holds for twelve consecutive months -- 2025-12..2026-07 in the committed
    manifest, plus 2026-08 and 2026-09 HEAD-verified 2026-09-15 -- but the CDN folder is the UPLOAD
    month, not the release month, and the two did NOT coincide for 2025-10 / 2025-11, whose
    manifest URLs are ``.../2025-12/Oct%202025%20World%20Agricultural%20Production.pdf``. Through
    any future reorganisation this probe 404s. That is exactly why a 404 is DECLINED and named with
    the URL that was tried instead of being silently skipped: the operator's next step -- a
    ``--discover`` manifest refresh from a host FAS admits -- is then already in the log.

    The alternative mechanism, walking the FAS search pagination the way ``--discover`` does, was
    refused because its primary drive cannot be proven before arming: ``/data/search`` and
    ``/data/world-agricultural-production`` both return Akamai 403 to this estate's laptop
    (re-measured 2026-09-15 through this module's own ``_fetch``), and masking a client to get past
    a bot fence is refused on principle.
    """
    return f"{_CDN_BASE}/{ym}/{_TAIL_FILENAME}"


def _probe_tail(ym: str, sleep_seconds: float = 0.0) -> tuple[str, str]:
    """ONE HEAD against the CDN for one release month. Returns ``(outcome, url)``.

    The classification is the instrument. ``declined`` means THE SOURCE SAID NO -- it has not
    published that month yet, which is the normal state of the current month on the 12th.
    ``unreachable`` means WE COULD NOT ASK -- a transport failure, an Akamai 403, a 5xx. The two
    never collapse into one bucket: a declined month is a fact about the SOURCE and an unreachable
    one is a fact about the TRANSPORT, and the tripwire's exit message names them separately so the
    operator reading a failure knows which of the two it is looking at. (Neither is appended to the
    fetch list -- only a ``found`` month is.)
    """
    url = _cdn_tail_url(ym)
    try:
        status = _head(url).status_code
    except Exception as exc:  # noqa: BLE001 - any transport failure is "could not ask", not "not published"
        logger.warning("Tail %s: UNREACHABLE (%s: %s) - %s", ym, type(exc).__name__, exc, url)
        outcome = _TAIL_UNREACHABLE
    else:
        if status == 200:
            logger.info("Tail %s: FOUND  %s", ym, url)
            outcome = _TAIL_FOUND
        elif status in (404, 410):
            logger.info("Tail %s: declined (HTTP %s - not published at this path) %s",
                        ym, status, url)
            outcome = _TAIL_DECLINED
        else:
            logger.warning("Tail %s: UNREACHABLE (HTTP %s) - %s", ym, status, url)
            outcome = _TAIL_UNREACHABLE
    if sleep_seconds:
        time.sleep(sleep_seconds)
    return outcome, url


def _discover_tail(
    entries: list[dict],
    today_ym: str,
    sleep_seconds: float = 0.0,
    cap: int = _TAIL_MAX_MONTHS,
) -> tuple[list[dict], list[str], list[str]]:
    """Probe the months after the manifest's newest entry.

    Returns ``(found_entries, declined_months, unreachable_months)``. Each found entry has EXACTLY
    the manifest entry's shape -- ``{"release_month", "url"}`` -- so it rides the same
    ``_upload_entry`` as every other month and there is no second place for the S3 key to be
    computed.

    ADDITIVE AND IN MEMORY ONLY: ``_save_manifest`` is never called from here.
    """
    found: list[dict] = []
    declined: list[str] = []
    unreachable: list[str] = []
    if not entries:
        logger.warning("Tail: the manifest is empty, so there is no newest entry to extend from; "
                       "skipping the tail probe")
        return found, declined, unreachable

    max_ym = max(e["release_month"] for e in entries)
    months = _tail_months(max_ym, today_ym, cap=cap)
    if not months:
        logger.info("Tail: manifest newest entry %s is current at %s - nothing to probe",
                    max_ym, today_ym)
        return found, declined, unreachable

    span = _ym_behind(max_ym, today_ym)
    if span > cap:
        logger.warning("Tail: manifest newest entry %s is %d months behind %s - probing only the "
                       "newest %d (%s..%s). The older part of the gap needs a --discover manifest "
                       "refresh; this run cannot reach it.",
                       max_ym, span, today_ym, cap, months[0], months[-1])
    logger.info("Tail: probing %d month(s) after manifest max %s: %s",
                len(months), max_ym, months)
    for ym in months:
        outcome, url = _probe_tail(ym, sleep_seconds=sleep_seconds)
        if outcome == _TAIL_FOUND:
            found.append({"release_month": ym, "url": url})
        elif outcome == _TAIL_DECLINED:
            declined.append(ym)
        else:
            unreachable.append(ym)
    return found, declined, unreachable


def _tail_is_frozen(newest_written_ym: str | None, today_ym: str,
                    threshold_months: int = _TAIL_FREEZE_MONTHS) -> bool:
    """The staleness tripwire predicate. PURE, so the whole rule is pinnable with no clock, no
    network and no S3.

    ``newest_written_ym`` is the newest release month THIS RUN LANDED IN RAW S3 -- uploaded, or
    found already present by the existence check. It is deliberately NOT the newest month the HEAD
    probe could reach: a month that is FOUND at the CDN and then fails to download or upload is
    reachable and absent, and reading the probe would have the instrument assert health while the
    prefix stands still (see ``_tail_verdict``). ``None`` (this run landed nothing at all) is a
    freeze by definition.

    The truth table, with the cases that made the threshold 2 and not 1:
        (2026-09, 2026-09) -> False   current
        (2026-09, 2026-10) -> False   ONE behind on the 12th, before that month's circular lands
        (2026-08, 2026-10) -> True    the August circular is the newest thing in S3 in October
        (2026-07, 2026-09) -> True    the state measured 2026-09-15, before this fix
    """
    if not newest_written_ym:
        return True
    return _ym_behind(newest_written_ym, today_ym) >= threshold_months


def _tail_verdict(*, armed: bool, scope_narrowed: bool, today_ym: str,
                  newest_written: str | None, unlanded_found: list[str],
                  threshold_months: int = _TAIL_FREEZE_MONTHS) -> str:
    """THE WHOLE TRIPWIRE RULE, in one pure function, decided from facts measured AFTER the upload
    loop. Returns one of the five ``_V_*`` verdicts. No clock, no network, no S3.

    It is one function and not a ladder of ``if`` statements grown one round at a time because the
    first version of this instrument was exactly that ladder, and it had a hole: it read the HEAD
    probe, so a tail month that was FOUND and then failed to WRITE still counted as progress, the
    run logged PASS and exited 0, and the next month it counted TWO such months as progress. The
    instrument asserted health while the table froze -- the same failure it exists to close, reached
    through a different door. The whole outcome set is therefore enumerated here, once:

      armed=False                    -> DISARMED     --no-tail / --no-tail-tripwire, the operator's
                                                     explicit "I know, do not fail me".
      unlanded_found non-empty       -> UNLANDED     the CDN is SERVING a month this run did not put
                                                     in S3. Either the fetch failed, or this run's
                                                     own --limit/--year-to refused it. Both mean the
                                                     prefix did not advance past a published month.
      not frozen                     -> PASS         the newest month in S3 is current or one behind
                                                     (one behind is the normal day-12 state).
      frozen and scope_narrowed      -> REPORT-ONLY  a hand run that asked a SMALLER question
                                                     (--limit 5, --year-from 2010) landed old months
                                                     by construction; its landed set is not the
                                                     estate's answer, so the verdict is logged and
                                                     not acted on.
      frozen                         -> STALE-SOURCE nothing newer than the threshold reached S3.

    WHAT IS NOT IN THIS SET, and why. An earlier design DISARMED the whole tripwire whenever any one
    probe came back ``unreachable``, on the doctrine that a source we cannot reach is not a source
    that has stopped. That doctrine is right about the SOURCE and this instrument does not measure
    the source: it measures whether OUR RAW PREFIX IS ADVANCING, which is equally untrue whether
    USDA stopped publishing or Akamai stopped answering us. The fail-open now lives in the threshold
    instead, where it is granular: a single fire's outage leaves the newest written month ONE behind
    and never trips, while an outage long enough to leave the table two months stale is an incident
    that has to be looked at. This closes a residual the old rule could not: FAS already answers 403
    (not 404) to this estate on /data/search, so a CDN reorganisation that 403s the production.pdf
    path made EVERY probe unreachable and disarmed the tripwire permanently, with nothing but a
    warning nobody reads. Unreachable months are still classified, still logged, and still NAMED in
    the exit message -- they no longer buy silence.
    """
    if not armed:
        return _V_DISARMED
    if unlanded_found:
        return _V_UNLANDED
    if not _tail_is_frozen(newest_written, today_ym, threshold_months):
        return _V_PASS
    return _V_REPORT_ONLY if scope_narrowed else _V_STALE


def _split(pool: list[dict], pred) -> tuple[list[dict], list[dict]]:
    """Partition ``pool`` into (kept, dropped) by ``pred``. Pure; exists so every filter in
    ``main`` can NAME what it dropped instead of narrowing the list silently."""
    kept: list[dict] = []
    dropped: list[dict] = []
    for e in pool:
        (kept if pred(e) else dropped).append(e)
    return kept, dropped


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

# Regex for WAP landing-page slugs embedded in FAS search result pages.
_LANDING_RE = re.compile(
    r'href="(/data/world-agricultural-production-(\d{2})(\d{2})(\d{4}))"'
)
# Regex for the PDF link on each WAP landing page.
_PDF_RE = re.compile(
    r'href="(https?://(?:www\.)?fas\.usda\.gov/sites/default/files/[^"]+\.pdf[^"]*)"'
)
_SEARCH_URL = (
    "https://www.fas.usda.gov/data/search"
    "?reports%5B0%5D=report_type%3A13286&page={page}"
)
_MAX_SEARCH_PAGES = 35


def _discover(sleep_seconds: float) -> list[dict]:
    """
    Two-stage FAS website scrape to build the complete WAP manifest.

    Stage 1 -- paginate through the FAS search results for report type 13286
    and collect every report landing-page URL (format:
    ``/data/world-agricultural-production-MMDDYYYY``).

    Stage 2 -- fetch each landing page with Chrome impersonation and extract
    the real PDF download URL, which varies across years because USDA
    reorganised their CDN in mid-2025.
    """
    # ------------------------------------------------------------------
    # Stage 1: collect all landing-page paths via paginated search
    # ------------------------------------------------------------------
    landing_paths: list[tuple[str, str]] = []  # (path, release_month)
    for page in range(_MAX_SEARCH_PAGES):
        url = _SEARCH_URL.format(page=page)
        try:
            r = _fetch(url, timeout=20)
        except Exception as exc:  # noqa: BLE001 -- any HTTP error stops this discovery page; loop breaks or continues
            logger.warning("Search page %d error: %s -- stopping", page, exc)
            break
        if r.status_code != 200:
            logger.info("Search page %d -> HTTP %s -- stopping", page, r.status_code)
            break

        matches = _LANDING_RE.findall(r.text)
        if not matches:
            logger.info("Search page %d: no landing URLs found -- done", page)
            break

        for path, mm, dd, yyyy in matches:
            release_month = f"{yyyy}-{mm}"
            landing_paths.append((path, release_month))

        logger.info(
            "Search page %d: %d landing URLs (total: %d)",
            page, len(matches), len(landing_paths),
        )
        time.sleep(sleep_seconds)

    logger.info("Stage 1 complete: %d landing pages", len(landing_paths))

    # ------------------------------------------------------------------
    # Stage 2: fetch each landing page to get the real PDF URL
    # ------------------------------------------------------------------
    confirmed: list[dict] = []
    for path, release_month in landing_paths:
        landing_url = f"https://www.fas.usda.gov{path}"
        try:
            r = _fetch(landing_url, timeout=20)
            if r.status_code != 200:
                logger.warning("  MISS   %s  HTTP %s", release_month, r.status_code)
                time.sleep(sleep_seconds)
                continue

            pdf_match = _PDF_RE.search(r.text)
            if pdf_match:
                pdf_url = pdf_match.group(1)
                # Normalise protocol-relative / non-www variants
                pdf_url = pdf_url.replace("//fas.usda.gov", "//www.fas.usda.gov")
                confirmed.append({"release_month": release_month, "url": pdf_url})
                logger.info("  FOUND  %s  ->  %s", release_month, pdf_url)
            else:
                logger.warning(
                    "  MISS   %s  -- no PDF link in %s", release_month, landing_url
                )
        except Exception as exc:  # noqa: BLE001 -- any HTTP error on landing page fetch is logged; loop continues
            logger.warning("  ERROR  %s  %s: %s", release_month, landing_url, exc)
        time.sleep(sleep_seconds)

    confirmed.sort(key=lambda e: e["release_month"])
    logger.info(
        "Discovery complete: %d/%d months confirmed",
        len(confirmed), len(landing_paths),
    )
    return confirmed


def _save_manifest(entries: list[dict]) -> None:
    _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _MANIFEST_PATH.open("w", encoding="utf-8") as fh:
        fh.write("# USDA FAS World Agricultural Production -- monthly PDF archive\n")
        fh.write("# Generated by: python jobs/ingest/fetch_usda_wap.py --discover\n")
        fh.write("# URLs scraped from FAS landing pages (vary by year due to 2025 CDN migration)\n\n")
        fh.write("releases:\n\n")
        for e in entries:
            fh.write(f"  - release_month: \"{e['release_month']}\"\n")
            fh.write(f"    url: \"{e['url']}\"\n")
            fh.write("\n")
    logger.info("Manifest saved: %d entries -> %s", len(entries), _MANIFEST_PATH)


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------

def _load_manifest() -> list[dict]:
    data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8"))
    releases: list[dict] = data.get("releases") or []
    logger.info("Manifest: loaded %d entries from %s", len(releases), _MANIFEST_PATH.name)
    return releases


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def _upload_entry(
    entry: dict,
    bucket: str,
    region: str,
    skip_existing: bool,
    sleep_seconds: float,
) -> str:
    """Download one WAP PDF and upload to raw S3.  Returns 'uploaded', 'skipped', or 'error'.

    ONE KEY, COMPUTED ONCE. ``s3_key`` is derived from ``raw_wap_key(ym)`` a single time and that
    same string is handed to BOTH ``s3_object_exists`` (a ``head_object``) and
    ``upload_bytes_to_s3``. That is the property that makes ``--skip-existing-s3`` mean anything:
    an existence check that keys differently from the write is a skip that never fires (or, worse,
    one that fires on the wrong object). It is also the reason the incremental tail hands its found
    months through THIS function rather than writing its own upload path -- a second place to
    compute the key is a second place for it to drift.

    Manifest months and tail months are indistinguishable here on purpose: both arrive as
    ``{"release_month", "url"}``.
    """
    ym = entry["release_month"]
    url = entry["url"]
    s3_key = raw_wap_key(ym)

    try:
        # BEFORE the download, not after: the skip has to save the GET (1-26 MB from
        # fas.usda.gov), not merely the PUT.
        if skip_existing and s3_object_exists(bucket, s3_key, region):
            # No polite sleep here: a skip is one S3 HEAD and never touches fas.usda.gov, and the
            # scheduled run skips all ~289 manifest months (287 x 1.5 s was ~7 min of pure sleep).
            logger.info("Skipping - already in S3: %s", s3_key)
            return "skipped"

        logger.info("Downloading %s  %s ...", ym, url)
        resp = _fetch(url)
        resp.raise_for_status()
        data = resp.content

        _validate_pdf(data, url)
        if len(data) < _SUSPICIOUS_PDF_BYTES:
            logger.warning(
                "SIZE-FLOOR %s: %d bytes, under %d - a valid PDF far below the 1.6-26 MB norm for "
                "this circular. WRITTEN ANYWAY (these are the bytes the URL served, and re-fetching "
                "a wrong URL returns them forever); read the bronze log for whether Table 01 "
                "extracts at all. %s",
                ym, len(data), _SUSPICIOUS_PDF_BYTES, url,
            )
        # NOTE, measured 2026-09-15: MIN_RAW_FILE_SIZES carries no 'usda_wap' key, so this call is a
        # NO-OP for this source however much it reads like validation. The warning above is the
        # instrument that actually fires; a real floor belongs in raw_metadata.py (another lane).
        check_min_file_size(data, "usda_wap", context=url)

        upload_bytes_to_s3(data, bucket, s3_key, region)
        write_raw_s3_metadata(bucket, s3_key, data, url, "application/pdf", region)

        logger.info(
            "Uploaded %s  (%.1f KB)  ->  s3://%s/%s",
            ym, len(data) / 1024, bucket, s3_key,
        )
        time.sleep(sleep_seconds)
        return "uploaded"

    except Exception as exc:  # noqa: BLE001 -- any download, validation, or S3 error is logged; caller accumulates errors
        logger.error("Failed %s (%s): %s", ym, url, exc)
        time.sleep(sleep_seconds)
        return "error"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description=(
            "Download USDA FAS World Agricultural Production monthly PDFs to raw S3. "
            "One PDF per month from 2002-08: every month in the tracked manifest, plus any "
            "newer month the FAS CDN already carries (the incremental tail)."
        )
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help=(
            "Scrape the FAS website to collect all WAP report landing pages, "
            "extract the real PDF URL from each, and rebuild "
            "configs/sources/usda_wap_manifest.yaml.  No AWS credentials required."
        ),
    )
    # DEFAULT ON since 2026-09-15. The flag was already on the jobdef's default command, but the
    # deployed submission replaces the command array wholesale, so it never reached argparse and
    # 287 PDFs were re-downloaded every fire. The jobdef command is terraform's and the DAG that
    # overrides it is another lane's file, so the CODE DEFAULT is the only lever that reaches the
    # scheduled run. A hand run that WANTS a re-download now passes --no-skip-existing-s3;
    # jobs/submit/submit_batch_wap_backfill.py passes --skip-existing-s3 explicitly and is
    # unaffected by the flip in either direction.
    parser.add_argument(
        "--skip-existing-s3",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip PDFs whose S3 key already exists (default: on). "
             "Use --no-skip-existing-s3 to force a re-download.",
    )
    parser.add_argument(
        "--tail",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Probe the FAS CDN for release months newer than the manifest's newest entry and "
             "fetch any that exist (default: on). Use --no-tail for the manifest alone.",
    )
    parser.add_argument(
        "--tail-tripwire",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Exit non-zero when the newest release month this run LANDED in raw S3 is 2 or more "
             "months behind the current month, or when a month the CDN is serving was not landed "
             "(default: on). Everything fetchable is written first. Reports and does not act when "
             "--limit/--year-* narrowed the scope.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print S3 keys and the tripwire verdict without downloading anything or touching AWS. "
             "NOT offline: the incremental tail still issues up to 6 HEAD probes against "
             "fas.usda.gov -- add --no-tail for a preview that makes no network calls at all.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=1.0,
        help="Polite delay between HTTP requests in seconds (default: 1.0).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process at most N files -- use 1-5 for smoke tests.",
    )
    parser.add_argument(
        "--year-from",
        type=int,
        default=None,
        metavar="YYYY",
        help="Process only entries with release year >= YYYY.",
    )
    parser.add_argument(
        "--year-to",
        type=int,
        default=None,
        metavar="YYYY",
        help="Process only entries with release year <= YYYY.",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Discover mode
    # ------------------------------------------------------------------
    if args.discover:
        entries = _discover(sleep_seconds=args.sleep_seconds)
        _save_manifest(entries)
        return

    # ------------------------------------------------------------------
    # Upload mode
    # ------------------------------------------------------------------
    entries = _load_manifest()
    manifest_max = max((e["release_month"] for e in entries), default=None)
    today_ym = _today_ym()

    # ------------------------------------------------------------------
    # The incremental tail -- BEFORE the year/limit filters, so a filter that drops a month the
    # CDN actually carries can say so instead of narrowing the list in silence.
    # ------------------------------------------------------------------
    tail_found: list[dict] = []
    tail_declined: list[str] = []
    tail_unreachable: list[str] = []
    if args.tail:
        tail_found, tail_declined, tail_unreachable = _discover_tail(
            entries, today_ym, sleep_seconds=args.sleep_seconds,
        )
        entries = entries + tail_found          # IN MEMORY ONLY: _save_manifest is not called here
    else:
        logger.info("Tail: disarmed (--no-tail); the manifest's newest entry is %s", manifest_max)
    tail_yms = {e["release_month"] for e in tail_found}
    armed = bool(args.tail and args.tail_tripwire)

    # A filter NARROWED this run's scope: --limit/--year-* answer a smaller question than the
    # estate's, so a hand backfill that lands only old months must not read as a freeze. Recorded
    # rather than inferred, because "did anything get dropped" is not recoverable from the survivors.
    scope_narrowed = False
    filters_applied: list[str] = []

    def _tail_dropped(dropped: list[dict], reason: str) -> None:
        nonlocal scope_narrowed
        if dropped:
            scope_narrowed = True
            filters_applied.append(reason)
        lost = sorted(tail_yms.intersection({e["release_month"] for e in dropped}))
        if lost:
            logger.warning(
                "Tail month(s) %s dropped by %s - found on the CDN and NOT fetched this run. The "
                "FILTER is why they are missing, not the source. (The jobdef's default command "
                "carries --year-to 2026, which the deployed override drops; restore that override "
                "and this line is what says the tail died rather than nothing at all.)",
                lost, reason,
            )

    if args.year_from is not None:
        entries, dropped = _split(entries, lambda e: int(e["release_month"][:4]) >= args.year_from)
        _tail_dropped(dropped, f"--year-from {args.year_from}")
    if args.year_to is not None:
        entries, dropped = _split(entries, lambda e: int(e["release_month"][:4]) <= args.year_to)
        _tail_dropped(dropped, f"--year-to {args.year_to}")
    if args.limit:
        entries, dropped = entries[: args.limit], entries[args.limit:]
        _tail_dropped(dropped, f"--limit {args.limit}")

    in_scope = {e["release_month"] for e in entries}

    def _unlanded_exit(unlanded: list[str], uploaded: int, skipped: int, errors: int) -> SystemExit:
        """The exit a FOUND-but-absent tail month earns, whether a filter refused it or the fetch
        failed. One message, so the two doors into the same freeze read the same in the log."""
        return SystemExit(
            f"UNLANDED-TAIL: the FAS CDN is serving release month(s) {unlanded} and this run did "
            f"not land them in raw S3 (uploaded={uploaded} skipped={skipped} errors={errors}; "
            f"filters {filters_applied or 'none'}). A month that is FOUND and not WRITTEN leaves "
            f"the raw prefix exactly as frozen as a month that was never enumerated, so the chain "
            f"stops here rather than reporting a clean run. If the scope was deliberate, say so "
            f"with --no-tail (or --no-tail-tripwire) instead of letting a filter decide it."
        )

    if not entries:
        # TWO VERY DIFFERENT SITUATIONS REACHED THIS LINE, and the old code exited 0 for both. A
        # deliberately narrow hand run (--year-from 2030) writing nothing is correct and stays a
        # clean exit. A manifest that loaded ZERO entries is a BROKEN IMAGE -- the YAML is baked in
        # at build time -- and a clean exit there is the same shape of silence as the freeze this
        # change exists to close: nothing written, nothing said, chain green.
        # This fence is about the IMAGE, not the tail: --no-tail / --no-tail-tripwire are the
        # operator's word about staleness and never a licence to exit 0 on an empty manifest.
        if not manifest_max:
            raise SystemExit(
                f"STALE-SOURCE: the manifest at {_MANIFEST_PATH} loaded ZERO entries, so this run "
                f"had nothing to fetch and no newest entry to probe forward from. That is a broken "
                f"image, not an empty month. Exiting non-zero rather than reporting a clean run "
                f"that wrote nothing."
            )
        # ...and a filter narrow enough to drop EVERY entry can still have dropped a month the CDN
        # is serving. Same door, same verdict as the loop below; it just reaches it earlier.
        if armed and tail_yms and not args.dry_run:
            raise _unlanded_exit(sorted(tail_yms), 0, 0, 0)
        logger.warning("No entries to process after filtering.")
        return

    if args.dry_run:
        # STILL CREDENTIAL-FREE: this branch returns before load_env()/get_required_env, so
        # --dry-run runs on any host. It is NOT network-free -- the tail probe above has already
        # issued its HEADs; --no-tail is the offline preview. The verdict is PREDICTED here through
        # the SAME pure function the live run uses, over the set this run WOULD land, and never
        # acted on: a preview must not exit non-zero.
        print(f"Would process {len(entries)} files:")
        for e in entries:
            mark = "   (tail)" if e["release_month"] in tail_yms else ""
            print(f"  {e['release_month']}  ->  {raw_wap_key(e['release_month'])}{mark}")
        print(f"tail: found={sorted(tail_yms)} declined={tail_declined} "
              f"unreachable={tail_unreachable}")
        would_land = max(in_scope, default=None)
        verdict = _tail_verdict(
            armed=armed, scope_narrowed=scope_narrowed, today_ym=today_ym,
            newest_written=would_land, unlanded_found=sorted(tail_yms - in_scope),
        )
        print(f"newest release month this run would land: {would_land}  "
              f"(current month {today_ym})  tripwire would report {verdict}")
        return

    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    uploaded = skipped = errors = 0
    # THE SET THE TRIPWIRE READS. A month lands when this run PUT it in S3 ('uploaded') or the
    # existence check FOUND it there ('skipped'); an 'error' month is reachable and absent, which is
    # the distinction the first version of this instrument could not make.
    landed: list[str] = []
    failed: list[str] = []
    for entry in entries:
        result = _upload_entry(
            entry,
            bucket,
            region,
            skip_existing=args.skip_existing_s3,
            sleep_seconds=args.sleep_seconds,
        )
        if result == "uploaded":
            uploaded += 1
            landed.append(entry["release_month"])
        elif result == "skipped":
            skipped += 1
            landed.append(entry["release_month"])
        else:
            errors += 1
            failed.append(entry["release_month"])

    newest_written = max(landed, default=None)
    unlanded_found = sorted(tail_yms - set(landed))

    logger.info("Done. uploaded=%d  skipped=%d  errors=%d | newest written=%s | tail: found=%s "
                "declined=%s unreachable=%s", uploaded, skipped, errors, newest_written,
                sorted(tail_yms), tail_declined, tail_unreachable)

    # A RUN THAT COULD NOT WRITE WHAT IT WAS TOLD TO WRITE IS NOT A CLEAN RUN, and this fence is
    # NOT disarmable: --no-tail-tripwire is the operator's word about STALENESS, never a licence to
    # report success over a failed download. Measured 2026-09-15 and the reason this is safe to make
    # blanket: all 287 pre-existing manifest months are present in raw S3 and --skip-existing-s3 is
    # now on by default, so the scheduled run fetches ONLY new months and no permanently-dead old
    # URL can fail it every fire. (Read BEFORE the staleness verdict, so that verdict is only ever
    # computed over a run that landed everything in its scope.)
    if errors:
        raise SystemExit(
            f"FETCH-FAILED: {errors} of {len(entries)} release month(s) could not be written: "
            f"{failed} (uploaded={uploaded} skipped={skipped}; tail months among them: "
            f"{sorted(tail_yms.intersection(failed)) or 'none'}). The newest month this run landed "
            f"in raw S3 is {newest_written}. Exiting non-zero rather than reporting a clean run: a "
            f"month that is FOUND and not WRITTEN freezes the prefix exactly as a month that was "
            f"never enumerated does."
        )

    # ------------------------------------------------------------------
    # The staleness tripwire, AFTER the upload loop on purpose: every manifest month and every
    # reachable tail month is written first, and only then does the run refuse to report success.
    # It reads the LANDED set, never the HEAD probe -- see _tail_verdict for the whole rule.
    # Stopping the chain here is the fence doing its job -- under a real freeze the silver shadow
    # is stale too, so a clean exit would promote a frozen table over a healthy-looking estate.
    # (The CPC-soil lesson, verbatim: a run can hold every published day, decline nothing, write
    # nothing, and still exit non-zero because the source has not moved.)
    # ------------------------------------------------------------------
    verdict = _tail_verdict(
        armed=armed, scope_narrowed=scope_narrowed, today_ym=today_ym,
        newest_written=newest_written, unlanded_found=unlanded_found,
    )
    if verdict == _V_DISARMED:
        logger.info("Tripwire: disarmed by %s; newest written release month %s, current month %s",
                    "--no-tail" if not args.tail else "--no-tail-tripwire",
                    newest_written, today_ym)
    elif verdict == _V_UNLANDED:
        raise _unlanded_exit(unlanded_found, uploaded, skipped, errors)
    elif verdict == _V_REPORT_ONLY:
        logger.warning(
            "Tripwire: REPORT-ONLY - the newest release month this run landed is %s against "
            "current month %s (%d behind), but %s narrowed the scope, so this run's landed set is "
            "not the estate's answer and the verdict is not acted on.",
            newest_written, today_ym, _ym_behind(newest_written, today_ym) if newest_written else -1,
            filters_applied,
        )
    elif verdict == _V_STALE:
        raise SystemExit(
            f"STALE-SOURCE: the newest WAP release month this run landed in raw S3 is "
            f"{newest_written} and the current month is {today_ym} - {_TAIL_FREEZE_MONTHS} or more "
            f"months behind. Every month this run could write HAS been written (uploaded={uploaded} "
            f"skipped={skipped} errors={errors}); the chain stops here so a frozen table cannot "
            f"promote clean. The tail declined {tail_declined or 'nothing'} and could not ASK about "
            f"{tail_unreachable or 'nothing'} - if that second list is not empty the source may be "
            f"fine and unreachable, but the prefix has stopped advancing either way. Check "
            f"{_cdn_tail_url(today_ym)} and, if the CDN has been reorganised, rebuild the manifest "
            f"with --discover from a host FAS admits."
        )
    else:
        logger.info("Tripwire: PASS - newest written release month %s, current month %s (%d "
                    "behind, threshold %d)", newest_written, today_ym,
                    _ym_behind(newest_written, today_ym), _TAIL_FREEZE_MONTHS)


if __name__ == "__main__":
    main()
