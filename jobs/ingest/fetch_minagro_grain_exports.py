#!/usr/bin/env python
"""MINAGRO -- the Ukrainian grain / pulse / flour export table producer (raw landing only).

SOURCE
------
    https://minagro.gov.ua/napryamki/eksport-do-krain-ies/
        eksport-z-ukrayini-zernovih-zernobobovih-ta-boroshna

ONE STANDING SLUG, UPDATED IN PLACE
-----------------------------------
Ukraine's Ministry of Agrarian Policy publishes its State Customs export table -- marketing-year
cumulative grain, pulse and flour exports in thousand tonnes -- at a single permanent URL that it
edits in place, roughly weekly (observed: Thursdays). There is no per-release URL, no archive index,
no document id and no RSS. That shapes everything below:

  * the raw key is dated by the TABLE'S OWN ``станом на`` date, never by the fetch date, so an
    unchanged page re-fetched five times lands ONE object rather than five;
  * FIRST CAPTURE WINS -- an existing object under an ``as_of=`` key is that release and is never
    overwritten, because a re-fetch would replace the capture with a later re-render of the same
    release and raw is the layer nothing downstream can repair;
  * a missed week is UNRECOVERABLE. The prior release is simply gone from the live page. This leg is
    forward-accumulation, exactly like Bursa, which is why the schedule cadence in the
    prepared_commands below is part of the contract rather than a preference.

WHY A BROWSER
-------------
minagro.gov.ua sits behind a Cloudflare MANAGED CHALLENGE. A plain HTTP GET answers 403 with an
interstitial from every IP class tried, so this producer runs on the BROWSER image
(``leviathan-dev-browser-runner``) and drives headless Chromium through the shared
:mod:`leviathan.ingest.browser_fetch` session, exactly as the Euronext MATIF leg does. The landed
object is the rendered ``<main>`` outerHTML -- a DOM snapshot rather than a wire response -- and the
``raw_meta`` companion carries the page URL, the capture UTC and the CMS publish stamp so the
provenance survives the difference.

A CHALLENGE PAGE MUST FAIL LOUDLY, NEVER LAND BYTES
----------------------------------------------------
The failure this producer exists to make impossible is landing a Cloudflare interstitial (or a 404,
or a half-rendered page) under an ``as_of=`` key that claims to be the ministry's customs table. Raw
is immutable: once such an object exists, nothing downstream can tell it from the real capture, and
the as-of it was filed under is burned forever. So:

  * the ready check waits for a ``<table>`` carrying the total row -- a challenge body never
    satisfies it, and a page that never satisfies it inside the budget raises ``ChallengeFailed``
    and exits :data:`EXIT_CHALLENGE_FAILED` (7);
  * the captured markup is then sniffed against the transform's own
    :func:`~leviathan.transforms.raw_to_bronze.minagro_grain_exports.looks_like_the_export_table`
    marker set, and a capture that fails it is REFUSED with the reason written to the log and to
    stdout, exit :data:`EXIT_TABLE_MARKERS_ABSENT` (6). Nothing is uploaded on that path;
  * the as-of date is read from the CAPTURED markup before anything is written, so a page that
    renders but carries no ``станом на`` date has no key to land under and refuses too.

Exit 7 says "the venue never gave us the table" (the challenge did not clear for this IP class);
exit 6 says "the venue gave us SOMETHING and it was not the table". Both are refusals, and keeping
them apart is what lets a CloudWatch metric filter read the first Fargate run as the answer to
whether the challenge clears from a datacenter IP. Exit 1 stays a plain failure (network, S3,
unexpected) and says nothing about the WAF.

AND THAT IS WHY THE EXISTENCE PROBE FAILS CLOSED (verdict 2026-08-20)
---------------------------------------------------------------------
``raw_exists`` is the LAST gate before the only PUT on this leg: by the time it runs, the browser
has captured, the marker sniff has passed and the as-of has been read, so there is nothing between
it and ``land_bytes``. The estate house idiom (``except Exception: return False``) answers "absent"
to a throttle, a 5xx, an expired token or a denied head -- which on this leg means a transient S3
failure silently repeals FIRST CAPTURE WINS, the rule stated as law two sections above. The overwrite
it grants is not hypothetical: the ministry re-renders the standing slug in place, so the second
fetch of a release is a DIFFERENT set of bytes for the same fact, and the landed one is the closer
witness. A missed week is unrecoverable here for the same reason.

That is the ``fetch_moex_agro_indices.py`` argument verbatim -- a family whose raw layer is
first-capture-wins BY LAW cannot leave the enforcement of that law to whether S3 happened to answer.
So only a genuine 404 means absent; any other ``HeadObject`` error fails the run (exit 1) with
NOTHING written. ``--force`` still skips the probe entirely, so an operator asking for an overwrite
still gets one. Exit 1 is Class D EXIT in ``infra/terraform/modules/batch/main.tf``
``local.producer_retry_rules``, terminal after ONE attempt -- so a failed probe cannot become a
retry storm that re-drives Chromium at a Cloudflare-fronted ministry.

S3 LAYOUT
---------
    raw/production/source=minagro_grain_exports/as_of={YYYYMMDD}/page.html
    raw_meta/<that key>_meta.json    (sha256, size, page URL, capture UTC, publish stamp)

Usage
-----
    python jobs/ingest/fetch_minagro_grain_exports.py
    python jobs/ingest/fetch_minagro_grain_exports.py --dry-run
    python jobs/ingest/fetch_minagro_grain_exports.py --dry-run --as-of-date 2026-08-14
    python jobs/ingest/fetch_minagro_grain_exports.py --force        # re-capture an existing as_of

PREPARED COMMANDS -- NOTHING BELOW IS ARMED, AND NONE OF IT HAS BEEN FIRED
--------------------------------------------------------------------------
No jobdef was registered and no schedule was created in this wave. What follows is the paste-ready
submit shape and the cadence proposal, to be run only on an owner's word.

PRECONDITION, AND IT IS ABSOLUTE: **the browser image must be REBUILT to carry this script.**
``leviathan-dev-browser-runner:3`` is pinned BY DIGEST to an image built before this file existed,
so a submit against the current digest fails at container start with
``python: can't open file '/app/jobs/ingest/fetch_minagro_grain_exports.py'``. The rebuild moves the
``browser_runner_image`` digest in ``infra/terraform/modules/batch/variables.tf`` IN THE SAME CHANGE
that pushes the image (the variable's own comment states this: an apply that does not move it
re-pins the OLD build). Note also the estate's worktree lesson -- serving/eval images must be built
from the MAIN tree, never a worktree, or gitignored configs are silently absent from the layer.

    # 1) rebuild + push the browser image, then re-pin the digest, then re-register the jobdef.
    #    (the jobdef itself is terraform-owned: aws_batch_job_definition.browser_runner)

    # 2) ONE capture, on demand -- the submit shape (leviathan-dev-queue is SPOT and is the
    #    ON-DEMAND queue for this fleet):
    aws batch submit-job \\
      --job-name minagro-grain-exports-capture \\
      --job-queue leviathan-dev-queue \\
      --job-definition leviathan-dev-browser-runner:3 \\
      --container-overrides '{"command":["python","jobs/ingest/fetch_minagro_grain_exports.py"]}'

    # 3) the SMOKE that must precede any schedule, with the EXACT command the schedule would fire.
    #    The law is the estate's own: smoke-test a new schedule's exact command before its first
    #    fire, and READ THE EXIT CODE -- rc 0 landed or skipped, rc 6 refused (not the table),
    #    rc 7 the Cloudflare challenge did not clear from a datacenter IP, rc 1 a real failure.
    #    rc 7 on this smoke is the answer to the only open question this leg has, and it is why the
    #    smoke exists: it must NEVER be discovered by a scheduled fire at 06:00Z on a Friday.
    aws batch describe-jobs --jobs <jobId> --query 'jobs[0].container.exitCode'

    # 4) CADENCE PROPOSAL (not created): Fri 06:00Z, weekly.
    #    The ministry updates the standing slug ~Thursday. Firing Friday morning UTC puts the
    #    capture a full business day after the release with the whole Thursday buffered, and 06:00Z
    #    is 09:00 in Kyiv -- after the CMS's own working morning, before the next week's edit. A
    #    missed week is UNRECOVERABLE (the prior release is gone from the live page), which is why
    #    the buffer sits AFTER the release rather than tight against it.
    #    cron(0 6 ? * FRI *)  -- UTC, and the weekday is derived from the cron field, never
    #    hand-labelled from a date.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.storage.paths import (  # noqa: E402
    MINAGRO_GRAIN_EXPORTS_FILENAME,
    raw_minagro_grain_exports_key,
)
from leviathan.transforms.raw_to_bronze.minagro_grain_exports import (  # noqa: E402
    MIN_SNIFF_ROWS,
    PAGE_URL,
    SOURCE,
    TOTAL_ROW_MARKER,
    as_of_date_from_page,
    ascii_safe,
    looks_like_the_export_table,
    publish_stamp,
)

logger = get_logger("fetch_minagro_grain_exports")

MINAGRO_BASE_URL = "https://minagro.gov.ua"
_PAGE_PATH = PAGE_URL[len(MINAGRO_BASE_URL):]
_CONTENT_TYPE = "text/html"

# Mirrored from leviathan.ingest.browser_fetch so this module's exit contract is readable without
# importing playwright. :func:`_browser` binds the two and FAILS if they ever drift -- a producer
# that exits 7 while the shared module means something else by 7 is worse than no code at all.
EXIT_CHALLENGE_FAILED = 7
# The refusal code, and it is deliberately NOT 7. A page that rendered SOMETHING which is not this
# table is a different fact from a challenge that never cleared: the first is a layout change or a
# CMS error and is a code/ops question, the second is the IP-class answer. Collapsing them would
# make an ordinary ministry redesign read as "Cloudflare blocks Fargate".
EXIT_TABLE_MARKERS_ABSENT = 6

# The only S3 error codes that mean "this key is genuinely not there". Everything else raises --
# see raw_exists(). Mirrors fetch_eex_freight._ABSENT_ERROR_CODES.
_ABSENT_ERROR_CODES = frozenset({"404", "NotFound", "NoSuchKey"})

# The challenge dance measured seconds on the sibling W1c venues; 90 s is the shared default and is
# generous enough that a timeout means "refused", not "slow".
_DEFAULT_MAX_WAIT_S = 90
# After the table is present, give the CMS's own late requests a moment to quiesce so the DOM we
# snapshot is the settled one. NOT a readiness signal: a page that polls forever never goes idle,
# which is why the marker check above is what decides readiness and this is best-effort.
_NETWORKIDLE_TIMEOUT_MS = 15_000

# The ready check and the capture, both expressed against ``main``. The ministry's CMS puts no id or
# class on the table, so readiness is "a table exists inside main and its text carries the total
# row" -- the same marker the transform's sniff and ``find_table`` use, so the producer cannot wait
# on one element and capture another.
_READY_JS = """
() => {
  const root = document.querySelector('main') || document.body;
  if (!root) { return false; }
  for (const t of root.querySelectorAll('table')) {
    const text = (t.innerText || t.textContent || '').toLowerCase();
    if (text.includes('%s') && t.querySelectorAll('tr').length >= %d) { return true; }
  }
  return false;
}
""" % (TOTAL_ROW_MARKER, MIN_SNIFF_ROWS)
_MAIN_OUTER_HTML_JS = """
() => { const m = document.querySelector('main'); return m ? m.outerHTML : null; }
"""


def _browser():
    """The shared browser module, imported LAZILY.

    Lazy on purpose: playwright lives on the browser image only, and the parser tests import this
    module to exercise its pure helpers on a laptop that has neither Chromium nor the extra. The
    exit-code bind is asserted here rather than at import for the same reason."""
    from leviathan.ingest import browser_fetch

    if browser_fetch.EXIT_CHALLENGE_FAILED != EXIT_CHALLENGE_FAILED:
        raise RuntimeError(
            f"exit-code drift: browser_fetch.EXIT_CHALLENGE_FAILED is "
            f"{browser_fetch.EXIT_CHALLENGE_FAILED}, this producer mirrors {EXIT_CHALLENGE_FAILED}"
        )
    return browser_fetch


def page_url() -> str:
    """The absolute page URL (recorded in raw_meta; the session navigates by path)."""
    return PAGE_URL


def page_path() -> str:
    """The path the browser session navigates to."""
    return _PAGE_PATH


def table_is_rendered(page) -> bool:
    """``goto_and_settle``'s ready check: a table with the total row is present inside ``main``.

    A Cloudflare managed-challenge interstitial has no such table, so the challenge simply never
    settles and the budget expiring IS the refusal."""
    try:
        return bool(page.evaluate(_READY_JS))
    except Exception:  # noqa: BLE001 -- a mid-navigation evaluate throws; that is "not yet"
        return False


def capture_main_html(session) -> Optional[str]:
    """The rendered ``<main>`` outerHTML via the session's page escape hatch, or None."""
    return session.page.evaluate(_MAIN_OUTER_HTML_JS)


def raw_exists(bucket: str, key: str, region: str) -> bool:
    """True when the object is already landed. **Only a genuine 404 means "absent".**

    THIS DIVERGES FROM THE ESTATE HOUSE IDIOM ON PURPOSE -- see the module docstring's verdict.
    ``except Exception: return False`` turns a throttle, a 5xx or an expired credential into
    "nothing is landed", which on this leg is a silent repeal of FIRST CAPTURE WINS: the ministry
    re-renders the standing slug in place, so the bytes that would replace the landed release are a
    later render of it, and the release they overwrite cannot be fetched back.

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


def land_bytes(bucket: str, key: str, data: bytes, *, region: str, extra: dict) -> None:
    """Upload the capture + its ``write_raw_s3_metadata`` companion, after the size floor.

    The house raw-landing convention (``fetch_euronext_eod.land_bytes``). NOTE that
    ``check_min_file_size`` returns SILENTLY when the source key is absent from
    ``MIN_RAW_FILE_SIZES`` -- a missing entry is a DISABLED floor, not an error -- so
    ``constants.MIN_RAW_FILE_SIZES['minagro_grain_exports']`` is part of this producer, not
    decoration. ``extra`` carries the capture UTC and the CMS publish stamp; core metadata fields
    win on any key collision."""
    from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
    from leviathan.storage.s3 import upload_bytes_to_s3

    check_min_file_size(data, SOURCE, context=key)
    upload_bytes_to_s3(data, bucket, key, region)
    write_raw_s3_metadata(bucket, key, data, page_url(), _CONTENT_TYPE, region, extra=extra)
    logger.info("raw written -> s3://%s/%s (%d bytes)", bucket, key, len(data))


def capture_metadata(html: str, captured_at: Optional[str] = None) -> dict:
    """The ``raw_meta`` extras for one capture: when we took it, and what the CMS said it was.

    ``capture_timestamp_utc`` is the only wall-clock fact this leg records, and it is recorded as
    PROVENANCE and never as a date of record: the row's date is the table's own ``станом на``
    value. ``publish_stamp_text`` / ``published_at`` come from ``div.publish_date`` -- kept because
    a shifting publish stamp over an unchanged as-of is the fingerprint of a CMS re-publish, which
    is precisely the event first-capture-wins refuses to re-land."""
    stamp = publish_stamp(html)
    return {
        "source": SOURCE,
        "capture_timestamp_utc": captured_at or datetime.now(tz=timezone.utc).isoformat(
            timespec="seconds"
        ),
        "capture_kind": "rendered_main_outerhtml",
        "publish_stamp_text": stamp["publish_stamp_text"],
        "published_at": stamp["published_at"],
    }


def _refuse(reason: str) -> int:
    """Write ONE refusal line to the log and to stdout, and answer the refusal exit code.

    stdout as well as the log because a Batch failure is read from the task's log stream and a
    refusal that only exists as a WARNING is a refusal nobody sees. ASCII by construction -- the
    reason routinely carries Ukrainian page text."""
    line = f"REFUSED minagro capture: {ascii_safe(reason, 600)}"
    logger.error("%s -- exiting rc %d. NOTHING was landed: raw is immutable and a challenge or "
                 "error page filed under an as_of= key is indistinguishable from the real table "
                 "forever after", line, EXIT_TABLE_MARKERS_ABSENT)
    print(line)
    return EXIT_TABLE_MARKERS_ABSENT


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        stream=sys.stderr)
    load_env()
    ap = argparse.ArgumentParser(
        description="Ukrainian ministry grain/pulse/flour export table -> raw S3 (browser leg)")
    ap.add_argument("--as-of-date", "--as-of", default=None, dest="as_of",
                    help="DRY-RUN ONLY: the as-of used to illustrate the key. A real capture ALWAYS "
                         "takes its as-of from the landed page's own 'станом на' date, because that "
                         "is the only thing distinguishing one release from the next on a slug the "
                         "ministry updates in place")
    # The flag SPELLINGS mirror the W1c producers on purpose: an operator or a scheduler copying an
    # invocation between browser legs must not get an argparse error, and --force must mean the same
    # thing everywhere (it CLEARS skip-existing; it is not a second switch to be ANDed with it).
    ap.add_argument("--skip-existing", action="store_true", default=True, dest="skip_existing",
                    help="(the default) FIRST CAPTURE WINS -- skip when this as-of is already "
                         "landed; --force overrides")
    ap.add_argument("--force", dest="skip_existing", action="store_false",
                    help="re-capture and OVERWRITE an already-landed as-of. Use only to repair a "
                         "known-bad object: the live page re-renders, so this replaces a capture "
                         "with a later render of the same release")
    ap.add_argument("--headless", action="store_true", default=True, dest="headless",
                    help="(the default) run Chromium headless")
    ap.add_argument("--headful", "--headed", action="store_false", dest="headless",
                    help="local debugging only; NEVER on Fargate")
    ap.add_argument("--max-wait-s", type=int, default=_DEFAULT_MAX_WAIT_S, dest="max_wait_s",
                    help="seconds to wait for the challenge to clear and the table to render "
                         "before ChallengeFailed")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--aws-region", default=None, dest="aws_region")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the URL and the key shape; no browser, no writes")
    args = ap.parse_args(argv)

    if args.dry_run:
        as_of = args.as_of or datetime.now(tz=timezone.utc).date().isoformat()
        print(f"url      : {page_url()}")
        print(f"as_of    : {as_of}  (illustrative -- a real capture reads the page's own "
              f"'stanom na' date)")
        print(f"key      : {raw_minagro_grain_exports_key(as_of)}")
        print(f"filename : {MINAGRO_GRAIN_EXPORTS_FILENAME}")
        print("(dry-run -- no browser, no writes)")
        return 0

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    bf = _browser()
    try:
        with bf.BrowserSession(MINAGRO_BASE_URL, headless=args.headless) as session:
            session.goto_and_settle(page_path(), ready_check=table_is_rendered,
                                    max_wait_s=args.max_wait_s)
            # Best-effort quiesce AFTER the table is present. A page that long-polls never goes
            # idle, so a timeout here is a debug line and never a failure.
            try:
                session.page.wait_for_load_state("networkidle",
                                                 timeout=_NETWORKIDLE_TIMEOUT_MS)
            except Exception as exc:  # noqa: BLE001 -- see above
                logger.debug("networkidle not reached (%s) -- the table is already present",
                             ascii_safe(exc))
            html = capture_main_html(session)
    except bf.ChallengeFailed as exc:
        # THE IP-CLASS ANSWER. One ASCII line, one dedicated exit code: the first Fargate run of
        # this job is what tells us whether the Cloudflare managed challenge clears from a
        # datacenter IP. Nothing was landed.
        logger.error("CHALLENGE_FAILED minagro: the export table never rendered within %ds (%s) -- "
                     "exiting rc %d. This run IS the residual probe: the Cloudflare managed "
                     "challenge did not clear for this IP class",
                     args.max_wait_s, type(exc).__name__, EXIT_CHALLENGE_FAILED)
        return EXIT_CHALLENGE_FAILED

    bad = looks_like_the_export_table(html)
    if bad:
        return _refuse(bad)

    try:
        as_of = as_of_date_from_page(html)
    except ValueError as exc:
        return _refuse(str(exc))

    key = raw_minagro_grain_exports_key(as_of.isoformat())
    if args.skip_existing:
        # THE ONLY raw_exists CALL SITE ON THIS LEG, and it is the LAST gate before land_bytes --
        # there is no second fence behind it. An existence probe that cannot answer must be read
        # neither as "absent" (which is how the old swallow-all raw_exists destroyed captures) nor
        # as "already landed" (a silent skip that would discard a capture we already paid a browser
        # run for). It fails the run instead: exit 1 with NOTHING written, and the capture is
        # recovered by re-running -- the page still holds this release until the ministry's next
        # edit. Note the ordering: the browser session has already closed by this point, so the
        # refusal costs no cleanup.
        try:
            already_landed = raw_exists(bucket, key, aws_region)
        except Exception as exc:  # noqa: BLE001 -- raw_exists fails CLOSED and may raise here
            logger.error(
                "FAILED minagro %s: the raw existence probe could not answer (%s: %s) -- NOTHING "
                "WRITTEN. Refusing to land: an unanswerable probe must never be read as 'absent' "
                "and PUT over a landed capture on a family whose raw layer is first-capture-wins "
                "by law and whose page the CMS re-renders in place",
                as_of.isoformat(), type(exc).__name__, exc,
            )
            return 1
        if already_landed:
            # FIRST CAPTURE WINS. The page is a standing slug the CMS re-renders in place, so a
            # second fetch of the same release is a DIFFERENT set of bytes for the same fact. The
            # landed one is the release; this one is discarded.
            logger.info("minagro %s: already landed at s3://%s/%s -- skipping (first capture wins; "
                        "use --force only to repair a known-bad object)",
                        as_of.isoformat(), bucket, key)
            return 0

    data = html.encode("utf-8")
    land_bytes(bucket, key, data, region=aws_region, extra=capture_metadata(html))
    logger.info("minagro done: as_of=%s bytes=%d key=%s", as_of.isoformat(), len(data), key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
