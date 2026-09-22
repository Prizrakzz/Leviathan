"""AWS Batch entrypoint: WASDE raw files → text/ layer (Phase 1).

Processes WASDE digital PDFs (2000–2026, Section D) and WASDE TXT files
(1995–1999, Section E).  Writes one document.json per release to:

    text/source=usda_wasde/release_date={YYYY-MM-DD}/document.json

Scanned PDFs (1973–1994, Section F) are skipped here — they require
Textract and are handled in Phase 2.

Run locally for smoke tests:
    python jobs/batch/wasde_text_task.py --era digital --limit 5
    python jobs/batch/wasde_text_task.py --era txt --limit 5

Full run (all non-Textract WASDE files; 375 in scope on 2026-09-22):
    python jobs/batch/wasde_text_task.py --era all

SCHEDULED SINCE 2026-09-22 (lane L5): this task is the LAST task of the SILVER phase of
``configs/silver/dags/wasde_monthly.json``, on jobdef ``leviathan-dev-text-to-graphrag``. Before
that it was reachable by no schedule at all, which is why the 2026-09-11 WASDE sat in raw for
eleven days with no document and 27 commodity evidence slices shared a single 41-day tip.

AND BECAUSE IT IS IN THAT CHAIN, A DOCUMENT-LEVEL FAILURE NO LONGER EXITS NONZERO.
--------------------------------------------------------------------------------
Bronze, Silver and Promote are FAIL-FAST -- ``infra/terraform/modules/step_functions/main.tf`` says
so in its own DegradedNotify text: "Bronze, Silver and Promote stay FAIL-FAST, so a failed
derivation or publication leg still stops this run before canonical (INV-6)". At HEAD this file
ended with ``if counts["error"]: sys.exit(1)``, and the jobdef's retry strategy makes that terminal
(``leviathan-dev-text-to-graphrag`` rev 16 carries ``evaluateOnExit {onExitCode: "1", action:
"exit"}``). So ONE unreadable PDF out of 375 -- a layout change in the very release this leg exists
to add, or one non-404 ``ClientError`` among the ~750 ``head_object`` calls the skip path makes --
would have withheld the month's CANONICAL WASDE publish, on all six fires of the 8th-13th window,
because a persistent defect is persistent. The text layer must never cost the numbers.

THERE IS NOWHERE AFTER PROMOTE TO PUT IT, and that was checked rather than assumed:
``gen_sfn_inputs.lint_descriptor`` accepts only fetch/bronze/silver/gold, ``render_input`` folds a
``gold`` phase INTO the silver Map (there is no Gold Map), and the machine's one post-promote state
``Reconcile`` is a FIXED task whose command is generated from ``$.gate_baseline_uri`` -- no
descriptor phase runs after promote for any of the 28 families. The FETCH phase is tolerant but its
tolerance is bounded (at least one leg must succeed, and an infra-class failure still FAILS the
run), and the one non-fetch task sitting there today -- weather_daily's ``chirps_to_bronze`` -- is
recorded in that same notifier text as an ACCEPTED, DOCKETED wart, not a pattern to copy.

So the leg is tolerant BY ITS OWN EXIT CODE, and the failure is COUNTED, NEVER SWALLOWED: every
fire emits ``WasdeTextRuns``, ``WasdeTextDocsWritten``, ``WasdeTextErrors``, ``WasdeTextInfraErrors``
and ``WasdeTextKnownFailures`` to ``Leviathan/Silver`` (dimension ``Family=usda_wasde``), which is
how the two classes reach an alarm apart, prints a loud line naming every failed key,
and exits 0. ``--strict-exit`` restores the old nonzero for a hand run; the descriptor command does
NOT carry it, and a deck pins that. What is NOT tolerated: a failure that stops the job reaching its
own tally -- a LIST that raises, a missing bucket, a credential fault -- still propagates, because
that is an infra fault and no count of it exists.

THE CLASS IS READ OFF THE EXCEPTION, NEVER OFF A COUNT (round 4, census B-R3-2 / lane MAJOR-R3-1).
--------------------------------------------------------------------------------
Round 2 shipped ``return 0`` for ANY number of document errors -- raw present, text frozen, nothing
red, which is verbatim the state this lane was opened for -- and round 3 answered that with a
NUMBER: at most one error per fire, and never a fire in which every in-scope document failed. A
counter cannot see a class, and the round-3 reviewer measured that bound through the REAL
``_process_one`` against a stub S3 (``rv_r3_l5_class_conflation.py``, no AWS). It was BACKWARDS IN
BOTH DIRECTIONS:

    A. ONE head_object THROTTLE  (pure INFRA),    375 in scope -> rc=0  <-- TOLERATED
    B. TWO head_object THROTTLES (pure INFRA),    375 in scope -> rc=1
    C. TWO UNREADABLE PDFs       (pure DOCUMENT), 375 in scope -> rc=1  <-- BLOCKS CANONICAL
    D. ONE UNREADABLE PDF        (pure DOCUMENT), 375 in scope -> rc=0

Row A tolerated the one class this estate tolerates nowhere; row C withheld the month's canonical
WASDE over the one class this leg exists to absorb. The cause was one line: the pool loop's single
``except Exception`` flattened ``ClientError`` out of ``_last_modified`` and ``ValueError`` out of
the extractor into ONE tally. The classification is now read off the EXCEPTION, at the seam that
raised it:

  * ``ClientError`` / ``BotoCoreError`` out of the S3 seam (head, download, put) = **INFRA**. ANY
    number of them, including ONE, exits 1. The fire must RE-RUN; a throttle is not a document, it
    is a document that was never attempted, and the estate says so in its own fetch-phase
    InfraFailNotify text ("that is NOT a blocked source, so it was NOT tolerated ... canonical was
    never touched (INV-6)"). The remedy is cheap because the family fires SIX times in the
    8th-13th window, so a transient fault costs at most one day of the month's publish.
  * anything else -- the extractors, a parse, an unreadable body = **DOCUMENT**. Counted, named on
    stdout, RECORDED (below), carried on ``WasdeTextErrors`` -- and exit 0, because a document must
    never withhold the month's canonical numbers.
  * the ONE document red that remains: a fire in which every release that was not ALREADY KNOWN to
    be broken failed. Nothing left standing is not a document class, and that arm fires ONCE and
    then retires itself (see the backlog, below).

AND THE BACKLOG IS BOUNDED BY A RECORD, NEVER BY A COUNT.
--------------------------------------------------------------------------------
Round 3's number was defended as MEASURED ("a steady fire puts ONE document in the write path, so a
second failure has to be infra"), and that measurement holds only while the backlog is EMPTY -- and
the tolerance is what fills it. ``text_is_current`` returns False while no document exists, so a
failed release is re-attempted on EVERY fire, forever. Under the round-3 shape that was a trap with
a one-month fuse: month 1 the September PDF fails to parse -> ``errors=1``, exit 0, the ``> 1``
alarm silent, the tip frozen; month 2 the October release lands and the SAME layout change breaks
it too -> ``errors=2``, exit 1, ``States.TaskFailed``, and October's canonical is not published on
all six fires of the window, and every month after.

So a tolerated failure is RETIRED instead of being carried by a counter. ``record_document_failure``
writes one small marker object per failed release under
``text_extraction_failures/source=usda_wasde/release_date=.../extraction_failure.json`` (bucket-wide
PutObject is already granted to ``leviathan-dev-batch-job-role`` by
``leviathan-dev-s3-data-lake-rw`` -- NO NEW IAM, verified live 2026-09-22), and the next fire reads
that prefix with ONE list and counts those releases KNOWN:

  * a KNOWN failure never re-blocks: it is excluded from the "every in-scope release failed"
    denominator, so a permanently unparseable release cannot withhold canonical in month 2 or in
    any month after. The blast radius of a new unparseable release is at most ONE fire of six.
  * a KNOWN failure never goes dark either: it rides ``WasdeTextKnownFailures``, a BACKLOG DEPTH
    gauge, while ``WasdeTextErrors`` carries only the NEW ones. That is what lets the error alarm
    page on the EVENT and then CLEAR, instead of becoming an alarm that never clears -- the state
    that teaches an operator to ignore it (the estate has one of those already: H-L2-5).
  * a failure the fire could NOT record (the marker PUT failed) is NOT retired, so the next fire
    reads it as NEW and the alarm pages again, every fire, until a human acts. The un-retired case
    stays LOUD by construction; there is no count anywhere it can quietly cross.
  * a marker whose release later succeeds is never read again (the set is consulted only for a
    release that failed THIS fire) and the recovery is printed. Nothing is deleted.

WHERE THAT EXIT LANDS, STATED PLAINLY RATHER THAN HOPED, AND RE-MEASURED IN ROUND 4: this task is
the LAST task of the SILVER Map, and the Silver Map has NO per-item Catch (only the Fetch processor
does -- ``task_item_processors``, ``phase == "Fetch" ? local.fetch_only_batch_overrides : []``). So
exit 1 HERE raises ``States.TaskFailed``, the Map throws, [Gate] and [Promote] are never entered and
the month's canonical is NOT published. THERE IS NO PHASE AFTER PROMOTE TO MOVE THE LEG TO --
``gen_sfn_inputs.lint_descriptor`` accepts only fetch/bronze/silver/gold (line 300),
``render_input`` folds ``gold`` INTO the silver Map (line 545, "There is NO Gold Map"), and the
machine's one post-promote state ``Reconcile`` is a FIXED task built from ``$.gate_baseline_uri``.
The answer is therefore the SECOND one the ruling allows: CANONICAL IS MADE INDEPENDENT OF THIS LEG
BY ITS EXIT CODE, for every class that must not cost the numbers. What is left is the INFRA red and
the once-only nothing-left-standing red, and both are deliberate: they are the estate's own rule for
a fault whose remedy is a re-run, inside a window that re-runs five more times.

THE ALARM'S NUMBER IS ZERO, AND IT IS SPELLED ONCE (``WASDE_TEXT_ERROR_ALARM_THRESHOLD``). Because
the exit code no longer reds for the document class at all, the error alarm is that class's ONLY
same-fire detector, so it must speak at the FIRST new failure:
``WasdeTextErrors{Family=usda_wasde}`` ``Maximum > 0`` per fire (Maximum, never Sum: the family
fires six times a month and a daily Sum adds two fires together and invents a breach no single fire
had). Lane 7's ``wasde_text_errors`` is still built at ``> 1`` against round 3's retired constant,
and re-pointing it is that lane's to do -- it is named in this lane's still-open list, with the
second alarm the split makes possible: ``WasdeTextInfraErrors Maximum > 0``.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from botocore.exceptions import BotoCoreError, ClientError
from leviathan.storage.paths import parse_hive_key, text_wasde_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_text.wasde_digital import extract_wasde_digital
from leviathan.transforms.raw_to_text.wasde_txt import extract_wasde_txt
from leviathan.transforms.raw_to_text.writer import write_document

logger = logging.getLogger("wasde_text_task")

_RAW_PREFIX = "raw/production/source=usda_wasde/"
_DIGITAL_YEAR_MIN = 2000
_SCANNED_YEAR_MAX = 1999  # 1973–1994 PDF = scanned; 1995–1999 = TXT
_MAX_WORKERS = 30

# The instrument that pays for the tolerant exit. Namespace and dimension shape are the estate's
# own (`leviathan.graphrag.corpus_coverage.METRIC_NAMESPACE` / its one-constant-dimension rule) --
# spelled here rather than imported so this task keeps its light import set, with a deck pinning the
# two spellings equal. NO NEW IAM: jobdef `leviathan-dev-text-to-graphrag` rev 16 runs under
# `leviathan-dev-batch-job-role`, whose inline `leviathan-dev-freshness-put-metric` grants
# PutMetricData conditioned on exactly this namespace (verified live 2026-09-22).
METRIC_NAMESPACE = "Leviathan/Silver"
METRIC_FAMILY = "usda_wasde"
METRIC_RUNS = "WasdeTextRuns"
METRIC_WRITTEN = "WasdeTextDocsWritten"
METRIC_ERRORS = "WasdeTextErrors"
# ROUND 4: the two classes are emitted SEPARATELY, because an alarm that reads one tally cannot
# page on the right class either. `WasdeTextErrors` is the NEW document failures only (the band the
# exit code tolerates, so the alarm is its only same-fire detector); `WasdeTextInfraErrors` is the
# S3-seam class (which also reds the execution, so its alarm is a second, faster reader of the same
# fact); `WasdeTextKnownFailures` is the BACKLOG DEPTH -- releases that failed again this fire and
# were already recorded -- which is what an operator burns down and what keeps the error alarm able
# to CLEAR.
METRIC_INFRA = "WasdeTextInfraErrors"
METRIC_KNOWN = "WasdeTextKnownFailures"
METRIC_NAMES = (METRIC_RUNS, METRIC_WRITTEN, METRIC_ERRORS, METRIC_INFRA, METRIC_KNOWN)

# THE ALARM'S NUMBER, SPELLED ONCE (round 4). Round 3 spelled `MAX_TOLERATED_DOC_FAILURES = 1` and
# handed lane 7 the same 1 as an alarm threshold; that constant is RETIRED because the exit code no
# longer reds on a count of document errors, so a number named "max tolerated" would be a number
# that means nothing here and something else there. The error alarm is now the document class's
# ONLY same-fire detector and must speak at the FIRST new failure: Maximum > 0 per fire.
WASDE_TEXT_ERROR_ALARM_THRESHOLD = 0

# THE BACKLOG RECORD. One marker object per release whose DOCUMENT extraction failed, so the next
# fire can tell a release it has already reported from one it has not -- the difference between a
# bounded backlog and an unbounded tolerance. Deliberately NOT under `text/`: SEVEN modules in this
# estate paginate `text/` whole (corpus_recon, batch_extract, evidence, evidence_batch, e0_harness,
# causal.author, corpus_coverage), and a marker that lands in a census's object count is an
# instrument that moved the thing it measures.
_FAILURE_PREFIX = "text_extraction_failures/source=usda_wasde/"
_FAILURE_MARKER = "extraction_failure.json"


def _classify_key(key: str) -> str | None:
    """Return 'digital', 'txt', or None (scanned — skip in Phase 1)."""
    if key.endswith(".txt"):
        return "txt"
    if key.endswith(".pdf"):
        release_date = parse_hive_key(key, "release_date")
        if not release_date:
            return None
        year = int(release_date[:4])
        if year >= _DIGITAL_YEAR_MIN:
            return "digital"
        # year < 2000 with .pdf = scanned era — Phase 2
        return None
    return None


def _last_modified(s3, bucket: str, key: str):
    """The object's LastModified, or None when it does not exist.

    A non-404 ClientError is RAISED: a throttle or a denial must never be read as "absent", because
    "absent" is the branch that decides work happens.
    """
    try:
        return s3.head_object(Bucket=bucket, Key=key)["LastModified"]
    except ClientError as exc:
        if str(exc.response.get("Error", {}).get("Code")) in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def text_is_current(s3, bucket: str, raw_key: str, text_key: str) -> bool:
    """True when the document at *text_key* was written AFTER the raw object it derives from.

    THIS REPLACES A BARE `document_exists` AND THE REASON IS MEASURED, NOT ARGUED. A WASDE release
    is not an immutable object in this estate: `raw/production/source=usda_wasde/` held 626 objects
    across 626 DISTINCT release_date partitions on 2026-09-22 -- ZERO partitions carry a second
    object -- so a corrected re-issue that `fetch_usda_wasde.py --skip-existing-s3` re-fetches
    (source_url-aware, per this family's own descriptor note) OVERWRITES the same key. It is not a
    hypothesis that raw moves under a written document: all 251 objects of the 1973-1994 scanned era
    were re-fetched in place at 2026-08-13T18:06Z, newer than the documents derived from them -- and
    the artifact is named exactly, because a claim that cites the wrong object is a claim nobody can
    re-measure: those partitions' `document.json` objects carry 2026-05-28 and their `pages.json`
    objects carry 2026-07-08 (R2 MINOR-1; both predate the re-fetch, so the claim holds on either
    artifact). Under existence-only idempotency that correction is invisible FOREVER and the text
    layer serves the superseded edition -- the MPOB freeze class this estate paid for once already
    (cea8818a: a skip-existing on a MUTABLE source froze bronze year=2026 at 111 rows for 20 days).

    THE FENCE CORRECTS, IT DOES NOT DELETE, AND IT COSTS NOTHING TODAY. Measured over the 375
    in-scope (non-Textract) raw objects on 2026-09-22: the existence-only rule selects 1 of 375 and
    this rule selects the SAME 1 of 375 -- release_date=2026-09-11, the September WASDE, which has
    no document at all. Every other document is already newer than its raw. So the first fire under
    this rule does byte-identical work to the first fire without it, and a future correction is
    picked up on the NEXT fire instead of never.

    FAIL-CLOSED IN BOTH DIRECTIONS: no document means not current (extract), and a raw object that
    cannot be headed means not current (extract). Re-extraction is idempotent and free of LLM cost
    -- the Haiku chunk cache is keyed on `md5(text_key)` (corpus_coverage.doc_cache_name), never on
    the body -- so the expensive mistake is the one this function refuses to make, not the cheap one
    it may occasionally repeat.
    """
    text_mtime = _last_modified(s3, bucket, text_key)
    if text_mtime is None:
        return False
    raw_mtime = _last_modified(s3, bucket, raw_key)
    if raw_mtime is None:
        return False
    return text_mtime > raw_mtime


def _process_one(
    raw_key: str,
    era: str,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
) -> tuple[str, str]:
    """Fetch one raw file, extract text, write document.json.

    Returns (status, text_key) where status is 'skipped', 'written', or 'error'.
    """
    release_date = parse_hive_key(raw_key, "release_date")
    text_key = text_wasde_key(release_date)

    s3 = get_thread_local_s3_client(aws_region)

    if not force_overwrite and text_is_current(s3, bucket, raw_key, text_key):
        return ("skipped", text_key)

    raw_bytes = s3_download_with_retry(bucket, raw_key, s3)

    if era == "digital":
        doc = extract_wasde_digital(raw_bytes, raw_key)
    else:
        doc = extract_wasde_txt(raw_bytes, raw_key)

    write_document(s3, bucket, text_key, doc)
    return ("written", text_key)


def failure_marker_key(release_date: str) -> str:
    """The ONE key a recorded document failure lives at. One object per release, overwritten on a
    repeat, so the backlog's size is the number of broken releases and never the number of fires."""
    return f"{_FAILURE_PREFIX}release_date={release_date}/{_FAILURE_MARKER}"


def known_failed_releases(bucket: str, aws_region: str) -> set[str]:
    """The release_dates this leg has ALREADY reported as document failures.

    ONE list, and it NAMES ITS OWN OBJECT SET: a key that does not begin with `_FAILURE_PREFIX` is
    dropped even though the LIST was asked for that prefix. That is the same narrowing the fold's
    `newest_manifest_since` took in round 3 (`write_manifest_rebuild_`), and it exists because a
    reader that trusts a prefix filter it did not apply itself is one stub away from believing
    everything is known.

    FAIL-LOUD, NOT FAIL-QUIET: when the list raises, this returns the EMPTY set, so every failure
    this fire is counted NEW and the error alarm PAGES. The opposite default -- "assume they are
    all known" -- would silence the alarm on the fire whose instrument just broke.
    """
    try:
        keys = list_s3_keys(bucket, _FAILURE_PREFIX, aws_region=aws_region)
    except Exception as exc:  # noqa: BLE001 -- see FAIL-LOUD above
        logger.warning("BACKLOG READ FAILED (%s) -- every document failure this fire is counted "
                       "NEW, so %s pages rather than going quiet on a record nobody could read",
                       type(exc).__name__, METRIC_ERRORS)
        return set()
    out: set[str] = set()
    for key in keys:
        if not key.startswith(_FAILURE_PREFIX):
            continue
        release_date = parse_hive_key(key, "release_date")
        if release_date:
            out.add(release_date)
    return out


def record_document_failure(*, bucket: str, aws_region: str, raw_key: str, release_date: str,
                            exc: BaseException) -> bool:
    """RETIRE one document failure into the bounded backlog. Returns True when it was recorded.

    A recorded failure is counted KNOWN on the next fire: it stops re-filling the "every in-scope
    release failed" denominator (so it can never withhold canonical twice) and it moves from
    `WasdeTextErrors` to the `WasdeTextKnownFailures` depth gauge (so the error alarm can clear).

    A FAILED RECORD NEVER FAILS THE LEG -- that would hand the text layer back the blast radius
    this whole change exists to remove -- and it is not a swallow either: the release simply stays
    NEW, so it is re-counted and re-paged on every fire until a human acts. The un-retired case is
    the LOUD one, by construction.
    """
    if not release_date:
        logger.warning("NOT RECORDED: %s carries no release_date partition, so the backlog has no "
                       "key to write; this failure stays NEW on every fire", raw_key)
        return False
    key = failure_marker_key(release_date)
    body = json.dumps(
        {
            "release_date": release_date,
            "raw_key": raw_key,
            "error_class": type(exc).__name__,
            "error": str(exc)[:500],
            "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "recorded_by": "jobs/batch/wasde_text_task.py",
            "class": "DOCUMENT",
        },
        ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    try:
        s3 = get_thread_local_s3_client(aws_region)
        s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")
    except Exception as exc2:  # noqa: BLE001 -- see the docstring: an un-retired failure stays LOUD
        logger.warning("BACKLOG WRITE FAILED (%s) for %s -- this failure is NOT retired and will "
                       "be counted NEW again on the next fire", type(exc2).__name__, release_date)
        return False
    logger.info("recorded document failure -> s3://%s/%s", bucket, key)
    return True


def metric_datums(counts: dict) -> list[dict]:
    """The FIVE datums, minted FROM THE TALLY this fire just printed, so CloudWatch and the log can
    never disagree. One constant dimension, five names, no per-release cardinality.

    `WasdeTextRuns` is emitted on EVERY fire, including the quiet ones: that is what lets a missing
    datapoint mean "no fire ran" instead of "a fire ran and found nothing to do", which is the
    distinction the `graphrag_evidence` freshness family could not make for 41 days.
    """
    dim = [{"Name": "Family", "Value": METRIC_FAMILY}]
    pairs = ((METRIC_RUNS, 1.0),
             (METRIC_WRITTEN, float(counts.get("written", 0))),
             (METRIC_ERRORS, float(counts.get("error", 0))),
             (METRIC_INFRA, float(counts.get("infra", 0))),
             (METRIC_KNOWN, float(counts.get("known", 0))))
    return [{"MetricName": n, "Dimensions": list(dim), "Value": v, "Unit": "Count"}
            for n, v in pairs]


def tolerance_verdict(n_errors: int, n_work: int, *, n_infra: int = 0, n_known: int = 0,
                      era: str = "all", limit: int = 0,
                      strict_exit: bool = False) -> tuple[int, str]:
    """The leg's exit code and the ONE sentence that explains it. Pure; no S3, no clock.

    THE ARGUMENTS ARE CLASSES, NOT A TALLY (round 4): *n_errors* is the NEW document failures,
    *n_known* the ones already recorded in the backlog, *n_infra* the S3-seam faults. The caller
    reads each one off the EXCEPTION that raised it, because a count cannot tell them apart and the
    round-3 bound that tried was backwards in both directions (module docstring, rows A and C).

    THE ARMS, in the order they are asked, each pinned by the deck:

      * ``--era all`` with no ``--limit`` and ZERO in-scope releases is a LISTING fault, not a
        quiet month: 375 in-scope objects exist today, so an empty work list means the prefix, the
        bucket or the credential moved. (A quiet fire is real for ``--era txt`` and for a ``--limit``
        run, and those are still exit 0.)
      * ANY infra fault -> exit 1. Never tolerated, not even one: the fire must RE-RUN, and it has
        five more fires in the 8th-13th window to do it in.
      * every release that was not ALREADY KNOWN to be broken failed -> exit 1. Nothing left
        standing is not a document class. KNOWN releases are excluded from that denominator, which
        is what stops a permanently unparseable release from withholding canonical a second time:
        the arm fires ONCE, the record retires it, and the next fire is green.
      * otherwise the DOCUMENT class -> exit 0, counted on ``WasdeTextErrors`` (new) and
        ``WasdeTextKnownFailures`` (backlog depth), named on stdout, and NEVER a cost to the
        month's canonical numbers.
    """
    if not n_work and era == "all" and not limit:
        return 1, ("TEXT LEG BLIND: `--era all` listed ZERO in-scope releases, and 375 exist "
                   "(measured 2026-09-22). An empty work list on the scheduled command is a "
                   "listing, prefix, bucket or credential fault -- not a quiet month -- so this "
                   "leg FAILS rather than reporting a perfectly healthy fire that did nothing.")
    if n_infra:
        return 1, (f"TEXT LEG INFRA FAULT: {n_infra} release(s) failed at the S3 seam "
                   f"(ClientError / BotoCoreError -- a throttle, a denial, an expiry, a timeout). "
                   f"That class is tolerated NOWHERE in this estate (the fetch phase's own "
                   f"InfraFailNotify arm) and it is not tolerated here: a throttled release is not "
                   f"a bad document, it is a document that was never attempted, so this fire must "
                   f"RE-RUN -- and the family fires again tomorrow inside the 8th-13th window.")
    live_work = n_work - n_known
    if live_work > 0 and n_errors >= live_work:
        return 1, (f"TEXT LEG DEAD: every one of {live_work} release(s) that was not already "
                   f"recorded as broken failed this fire ({n_known} were already known). Nothing "
                   f"left standing is not a document class, so this leg FAILS rather than leaving "
                   f"raw present, text frozen and nothing red. It fails ONCE: these failures are "
                   f"recorded, so the next fire counts them KNOWN and canonical is not withheld "
                   f"again.")
    if (n_errors or n_known) and strict_exit:
        return 1, (f"--strict-exit: failing this run on {n_errors + n_known} document error(s).")
    return 0, ""


def emit_metrics(counts: dict, *, aws_region: str) -> None:
    """PUT the datums. A failed PUT does not fail the fire and that is not fail-open: the alarm this
    feeds owns its own missing data, and failing here would turn an instrument into a new way for
    the text leg to cost the month's numbers -- the exact blast radius this change exists to
    remove."""
    try:
        import boto3
        boto3.client("cloudwatch", region_name=aws_region).put_metric_data(
            Namespace=METRIC_NAMESPACE, MetricData=metric_datums(counts))
        logger.info("metrics -> %s %s", METRIC_NAMESPACE,
                    ", ".join("%s=%s" % (d["MetricName"], d["Value"])
                              for d in metric_datums(counts)))
    except Exception as exc:  # noqa: BLE001 -- an instrument must never fail the leg it measures
        logger.warning("METRIC EMIT FAILED (%s) -- the tally above STANDS and the failure is in "
                       "the log; never silently swallowed", type(exc).__name__)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(description="WASDE raw → text/ (Phase 1)")
    parser.add_argument("--bucket", default="leviathan-dev-shahem-001")
    parser.add_argument("--aws-region", default="us-east-1", dest="aws_region")
    parser.add_argument(
        "--era",
        choices=["digital", "txt", "all"],
        default="all",
        help="Which WASDE era to process (default: all non-Textract)",
    )
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        help="Re-extract and overwrite existing document.json objects",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Cap number of files processed (0 = no limit; useful for smoke tests)",
    )
    parser.add_argument(
        "--strict-exit",
        action="store_true",
        dest="strict_exit",
        help="exit 1 when ANY document failed (the pre-2026-09-22 behaviour). FOR A HAND RUN "
             "ONLY: this task is the LAST task of a FAIL-FAST silver phase, so in the scheduled "
             "chain a nonzero exit withholds the month's CANONICAL WASDE publish over one "
             "unreadable PDF. The descriptor command does not carry it and a deck pins that. It "
             "only ever ADDS reds: without it the leg still fails on ANY infra-class fault, and "
             "on a fire in which every release that was not already recorded as broken failed.",
    )
    args = parser.parse_args()

    logger.info(
        "Starting WASDE text extraction  era=%s  bucket=%s  force=%s",
        args.era,
        args.bucket,
        args.force_overwrite,
    )

    all_keys = list_s3_keys(args.bucket, _RAW_PREFIX, aws_region=args.aws_region)
    logger.info("Found %d raw keys under %s", len(all_keys), _RAW_PREFIX)

    # Filter by era
    work: list[tuple[str, str]] = []
    for key in all_keys:
        era_label = _classify_key(key)
        if era_label is None:
            continue
        if args.era != "all" and era_label != args.era:
            continue
        work.append((key, era_label))

    if args.limit:
        work = work[: args.limit]

    logger.info(
        "Queued %d files to process (era=%s, limit=%s)",
        len(work),
        args.era,
        args.limit or "none",
    )

    # THE BACKLOG, READ ONCE, BEFORE ANY WORK. A release already recorded as a document failure is
    # KNOWN: it may fail again without re-blocking canonical and without re-paging the error alarm,
    # and its depth rides its own gauge. One LIST of a prefix that holds one small object per broken
    # release -- it is the cheapest call this fire makes.
    known_before = known_failed_releases(args.bucket, args.aws_region)
    logger.info("Backlog: %d release(s) already recorded under s3://%s/%s",
                len(known_before), args.bucket, _FAILURE_PREFIX)

    counts: dict[str, int] = {"written": 0, "skipped": 0, "error": 0, "infra": 0, "known": 0}
    failed: list[str] = []
    infra_failed: list[str] = []
    known_failed: list[str] = []
    unrecorded: list[str] = []
    recovered: list[str] = []
    started_at = datetime.now(timezone.utc)

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {
            pool.submit(
                _process_one,
                raw_key=key,
                era=era_label,
                bucket=args.bucket,
                aws_region=args.aws_region,
                force_overwrite=args.force_overwrite,
            ): key
            for key, era_label in work
        }

        for fut in as_completed(futures):
            raw_key = futures[fut]
            release_date = parse_hive_key(raw_key, "release_date")
            try:
                status, text_key = fut.result()
                counts[status] += 1
                if status == "written":
                    logger.info("written  %s", text_key)
                    if release_date in known_before:
                        recovered.append(release_date)
                else:
                    logger.debug("skipped  %s", text_key)
            # THE CLASS IS THE EXCEPTION. `_last_modified` raises a non-404 ClientError BY DESIGN,
            # `s3_download_with_retry` and `write_document` raise at the same seam, and a timeout
            # arrives as BotoCoreError -- none of those is a bad document, so none of them may be
            # tolerated as one (census B-R3-2 row A: a single throttle used to exit 0).
            except (ClientError, BotoCoreError):
                counts["infra"] += 1
                infra_failed.append(raw_key)
                logger.exception("INFRA failure (S3 seam) processing %s", raw_key)
            # Everything else came out of an extractor or a parse: the DOCUMENT class. It is
            # tolerated, and it is RETIRED into the backlog so the tolerance cannot fill it
            # (census B-R3-2 row C: two unreadable PDFs used to withhold the month's canonical).
            except Exception as exc:  # noqa: BLE001 -- the document class, counted and recorded
                if release_date and release_date in known_before:
                    counts["known"] += 1
                    known_failed.append(raw_key)
                    logger.exception("DOCUMENT failure (ALREADY RECORDED) processing %s", raw_key)
                else:
                    counts["error"] += 1
                    failed.append(raw_key)
                    logger.exception("DOCUMENT failure (NEW) processing %s", raw_key)
                    if not record_document_failure(bucket=args.bucket,
                                                   aws_region=args.aws_region,
                                                   raw_key=raw_key,
                                                   release_date=release_date,
                                                   exc=exc):
                        unrecorded.append(raw_key)

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    logger.info(
        "Done in %.1fs written=%d  skipped=%d  document-new=%d  document-known=%d  infra=%d",
        elapsed,
        counts["written"],
        counts["skipped"],
        counts["error"],
        counts["known"],
        counts["infra"],
    )
    if recovered:
        logger.info("RECOVERED: %d release(s) that were recorded as broken now have a document "
                    "(%s). Their markers are stale and are never read again -- nothing is deleted.",
                    len(recovered), ", ".join(sorted(recovered)[:20]))
    if unrecorded:
        logger.error("BACKLOG NOT BOUNDED for %d release(s): the marker write failed, so they are "
                     "NOT retired and will be counted NEW -- and PAGED -- on every fire until a "
                     "human acts. Keys: %s", len(unrecorded), ", ".join(sorted(unrecorded)[:20]))

    rc, reason = tolerance_verdict(counts["error"], len(work),
                                   n_infra=counts["infra"], n_known=counts["known"],
                                   era=args.era, limit=args.limit,
                                   strict_exit=args.strict_exit)

    # THE FAILURE IS NAMED BEFORE IT IS COUNTED. A tolerant exit that printed only a number would be
    # the swallow this change is accused of; every failed key is on stdout, the tally is in the log,
    # and the count is on a metric an alarm can read. The sentence states which way the exit went,
    # because "the chain CONTINUES" printed on a fire that FAILS is a report nobody can trust.
    if failed or known_failed or infra_failed:
        logger.error(
            "TEXT LEG %s: %d of %d in-scope releases failed and are NOT in text/ "
            "(%d NEW document, %d already-recorded document, %d INFRA). %s "
            "The counts ride %s / %s / %s {Family=%s}. "
            "NEW document keys: %s | known: %s | infra: %s",
            "FAILING" if rc else "DEGRADED",
            len(failed) + len(known_failed) + len(infra_failed), len(work),
            len(failed), len(known_failed), len(infra_failed),
            reason or ("The chain CONTINUES -- this leg must never withhold the month's canonical "
                       "WASDE publish over the DOCUMENT class."),
            METRIC_ERRORS, METRIC_KNOWN, METRIC_INFRA, METRIC_FAMILY,
            ", ".join(sorted(failed)[:20]) or "-",
            ", ".join(sorted(known_failed)[:20]) or "-",
            ", ".join(sorted(infra_failed)[:20]) or "-",
        )

    # EMITTED BEFORE THE RETURN, ON EVERY PATH. The datum must exist even when this leg is about to
    # fail the execution: for the document class the alarm is the ONLY same-fire detector, and a
    # red run that emitted nothing would make CloudWatch and the execution history disagree.
    emit_metrics(counts, aws_region=args.aws_region)

    if rc:
        logger.error("%s", reason)
    return rc


if __name__ == "__main__":
    sys.exit(main())
