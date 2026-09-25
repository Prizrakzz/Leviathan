#!/usr/bin/env python
"""Phase G -- THE MONTHLY FOLD WRAPPER (backup -> gated rebuild -> blue-green pg -> swap).

G4 IS THE MONTHLY FOLD AND NOTHING ELSE, and the reason is measured, not argued. The draft's WEEKLY
DELTA ROUTE is STRUCK: `load_pg_evidence._load_one` passes the node string VERBATIM to
`pgstore.upsert` (load_pg_evidence.py:85-93), `pgstore.prop_id` hashes it
(`md5(f"{node}|{source_key}|{text}")`, pgstore.py:782-785), and every retrieval filters
`node = %(node)s` (pgstore.py:868, batched :1072). So delta rows would have landed under
`node = "delta/<run_id>/soybeans"`, which the `soybeans` query can NEVER match, which the fold could
NEVER overwrite (different ids), and whose prefix could not then be deleted without leaving pg rows
no S3 object backs. Aggravating: `evidence._evid_read` swallows ClientError and returns ""
(evidence.py:89-100), so a wrong delta path loads 0 records and prints "0 props" WITHOUT failing.
pg = f(S3 slices), full stop -- there is no second prefix and no unguarded delete on the corpus.

WHY THIS FILE EXISTS RATHER THAN THE SUBMITTER.

`assert_not_live_rebuild` and `build_gated_command` live INSIDE
`jobs/submit/submit_batch_evidence_maintenance.py` -- i.e. in the SUBMITTING PROCESS. A descriptor
fire never runs the submitter, and neither does the S3-staged `["-c", ...]` override seam, so both
of those paths bypass the live-prefix assertion, the `driver_slices_manifest --check` lint and the
`e1_census --diff` gate. That is why the design restricts the staged seam to READ-ONLY PROBES AND
THE G3 CHUNK LEG, and why A FOLD IS NEVER STAGED. This file carries the guards on the container side
by IMPORTING them from the submitter module (it ships in the image: the Dockerfile COPYs jobs/), so
there is exactly ONE definition of each guard and no copy to drift.

AND THE STEP THE DRAFT OMITTED ENTIRELY: THE PRE-REBUILD BACKUP. A live `--rebuild-slices` re-derives
every slice from the whole chunk cache and rewrites all 52 commodity + 144 driver objects IN PLACE;
only the pg half has a real rollback (`pg_evidence_swap --rollback`). The write guard is NOT a
substitute -- the 2026-08-21 manifest shows it emitting only WARNs on real population drops (`ddgs`
1312->1311, `palm_kernel` 4245->4238) while `barley_yellow_dwarf_virus` (prior 2 props) and
`wheat_blast` (prior 123) were recorded as `unwritten` rather than refused, because that pass ran
`--allow-churn 50.0`. Every prior slice-rewriting pass in this estate took a copy first
(`_backup_pre_ndw_20260720/`, `_backup_pre_waver_20260802T0035Z/`, `_backup_pre_x2_20260820/`,
`_backup_pre_completion_20260821/`, `chunks_backup_20260821/`). So the fold's FIRST act is
`graphrag_evidence/_backup_pre_corpuslane_<YYYYMMDD>/`, verified by object count, retained one full
cycle. $1.47/month of retained storage, carried in the design's cost table.

AND THE DEFECT THE FIX PASS CLOSED: `--evidence-s3` IS AN ENVIRONMENT BINDING, NOT AN ARGUMENT.
`evidence_batch` exposes no `--evidence-s3` flag at all -- `evidence._evid_s3()` (the `EVIDENCE_S3`
env var, evidence.py:42-43) is its ONLY channel -- so the first draft validated the shadow prefix in
GUARD 1 and then launched `--rebuild-slices` in a child that inherited the jobdef's baked LIVE
prefix. Measured: guard `PASS`, backup of the shadow's 199 objects, child resolving
`s3://leviathan-dev-shahem-001/graphrag_evidence`. `cc.bind_evidence_prefix` (GUARD 0) now binds the
flag before anything reads it and `child_env` pins it for every step; the post-condition below
refuses if the chain's prefix is ever not the one the guard cleared.

AND THE DEFECT ROUND 2 CLOSED: THE GATE WAS FROZEN AGAINST A SNAPSHOT NOTHING REFRESHED.

The scheduled fold's `--census-baseline` is an EventBridge Scheduler Input, frozen at apply time, so
every monthly fold forever diffed against ONE object -- `graphrag_evidence/eval/e1_census.json`,
written 2026-08-02T00:36:09Z. Nothing in the account refreshes it: `e1_census --diff` is a read-only
gate that never calls `write()`, and no schedule anywhere runs a plain census (all 30 schedules and
4 rules were listed). The gate's teeth are `population_drops` at a 10% fractional floor MEASURED
AGAINST THE BASELINE'S VALUE, and this lane exists to make the store grow every month -- so a slice
that doubles by 2027-03 could lose half of everything ingested since August, still sit above the
August number, and the fold would exit green. THE FOLD NOW ADVANCES ITS OWN BASELINE: step 4 of the
chain is a plain census WRITE that runs only after the lint, the rebuild and the gate all returned 0
(`run_chain` stops at the first nonzero -- NO ROLL ON RED), so each fold diffs against the previous
fold. GUARD 4 refuses a live fold whose declared baseline is not the key it rolls, and a green chain
whose rolled object did not move is turned RED by a post-condition HEAD. The shape is
`jobs/audit/advance_rolling_census.py`'s, which does exactly this for the silver estate's rolling
gate baselines.

AND THE INSTRUMENT ROUND 2 ADDED: THIS FOLD USED TO BE UNMEASURED IN EVERY DIRECTION.

At HEAD this file wrote no ledger, no heartbeat and no metric, and nothing else covered it: the
EventBridge rule `leviathan-dev-batch-job-failed` targets only a log group, the metric filter that
feeds an alarm WITH AN ACTION matches only MANAGED_BY_AWS jobs plus three named jobNames (none of
them corpus-*), and the catch-all backstop alarm has 0 alarm actions. A monthly fold that failed
every month would have paged nobody, and a DLQ alarm cannot see it (a DLQ catches a delivery
Scheduler could not make, never a job that ran and failed). Every fire now ends with a ledger line
at `<EVIDENCE_S3>/fold/last_run.json` and three datums in `Leviathan/Silver` --
`CorpusFoldRuns`, `CorpusFoldSlicesWritten`, `CorpusFoldFailures`, one constant dimension
`Family=graphrag_evidence`, no new IAM. The SLICE count and not `docs.written`: a fold is a
re-derivation, so `docs.written` is 0 on a perfect fold (measured: the 2026-08-21 manifest records
`docs {"written": 0}` beside 196 slice objects and 2,742,847 rows).

WHAT THIS FILE DELIBERATELY DOES NOT DO.

* IT NEVER PASSES `--allow-churn`. An add-only lane must never need it, and if the live rebuild
  refuses, THAT REFUSAL IS THE FINDING. There is no flag here to override it.
* IT THREADS NOTHING FOR DECLARED CHURN EITHER. A slice whose drop is INTENDED (a routing edit in
  driver_slices.yaml narrowed it) is declared in `configs/graphrag/declared_churn.json`, which the
  rebuild's own write guard reads from THIS image at every plan -- no flag, no env var, no path is
  passed. The 2026-09-23 fire (corpus-fold-h13c) refused on exactly that case:
  drivers/russia_export_tax_quota 583 -> 133 after the 2026-08-27 co_terms narrowing (commit
  d9af78ce), and the per-slice declaration -- not a layer-wide --allow-churn that would let every
  slice drop that far -- is the structural answer. GUARD 3 prints the declarations in force before
  any compute, read-only, so the log states what may pass the 10% line and why.
* The pg legs (`--with-pg-load`, `--with-pg-swap`) are OFF by default. R3 stays MANUAL for its first
  three cycles, driven from the operator's seat; these switches exist so the chain is expressible
  and rehearsable, not so a schedule can flip pg on its own.
* It never re-implements the rebuild, the census gate or the manifest lint -- it runs the existing
  entry points in order and exits on the first nonzero, exactly as `build_gated_command` does.
* It never deletes anything. The previous cycle's backup prefix is deleted by the OPERATOR after the
  NEXT clean fold; `write_guard` covers writes, not deletes, and no D-EI seam exists for a delete.

ASCII-only stdout (Windows console is cp1252).

    python jobs/batch/corpus_fold_task.py --stage fold \
        --evidence-s3 s3://leviathan-dev-shahem-001/graphrag_evidence/shadow_originpolicy --dry-run
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))
if str(_REPO) not in sys.path:                       # jobs/ is a namespace package in this tree
    sys.path.insert(0, str(_REPO))

from leviathan.graphrag import corpus_coverage as cc  # noqa: E402

BACKUP_PREFIX_FMT = "_backup_pre_corpuslane_%Y%m%d"
JOBDEF = "leviathan-dev-evidence-build"

# -- the rolling baseline (R2 FATAL-1) -----------------------------------------------------------
# `e1_census.write()` writes `<EVIDENCE_S3>/eval/e1_census.json` (+ .md) and archives any prior copy
# to `e1_census_<UTC>.json` first. That key IS the one the scheduled fold's frozen
# `--census-baseline` names, which is what makes the roll possible without touching the Input.
CENSUS_ARTEFACT = "eval/e1_census.json"

# -- the liveness instrument (R2 MAJOR-3) ---------------------------------------------------------
# Namespace and dimension are `corpus_coverage`'s, not new ones: ONE namespace, ONE constant
# dimension, three names. `leviathan-dev-batch-job-role` (which JOBDEF runs under) already grants
# PutMetricData conditioned on exactly this namespace -- no new IAM (verified live 2026-09-22).
METRIC_RUNS = "CorpusFoldRuns"
METRIC_SLICES_WRITTEN = "CorpusFoldSlicesWritten"
METRIC_FAILURES = "CorpusFoldFailures"
FOLD_METRIC_NAMES = (METRIC_RUNS, METRIC_SLICES_WRITTEN, METRIC_FAILURES)
FOLD_LEDGER_SUFFIX = "fold/last_run.json"


def _guards():
    """The submitter's guards, imported (never copied) so there is one definition of each."""
    sys.path.insert(0, str(_REPO / "jobs" / "submit"))
    import submit_batch_evidence_maintenance as sm  # noqa: E402
    return sm


def _slice_keys(s3, bucket: str, prefix: str) -> list[str]:
    """The 52 commodity slices (top level *.jsonl) + the 144 driver slices (drivers/*.jsonl). The
    chunk cache is NOT backed up here: `--rebuild-slices` READS chunks/ and never writes it, so the
    layer at risk from a fold is the slices."""
    out: list[str] = []
    pag = s3.get_paginator("list_objects_v2")
    for page in pag.paginate(Bucket=bucket, Prefix=prefix + "/", Delimiter="/"):
        out += [o["Key"] for o in page.get("Contents") or [] if o["Key"].endswith(".jsonl")]
    for page in pag.paginate(Bucket=bucket, Prefix=prefix + "/drivers/"):
        out += [o["Key"] for o in page.get("Contents") or [] if o["Key"].endswith(".jsonl")]
    return sorted(out)


def backup_plan(s3, evidence_s3: str, *, stamp: str) -> dict:
    """{src_key -> dst_key} for the pre-rebuild copy, plus the byte total. LIST only."""
    bkt, prefix = cc._split_s3(evidence_s3.rstrip("/"))
    keys = _slice_keys(s3, bkt, prefix)
    # The backup is a CHILD of the prefix being rewritten, mirroring the estate's five prior backup
    # prefixes (`graphrag_evidence/_backup_pre_ndw_20260720/`, `_backup_pre_x2_20260820/`, ...).
    # A SIBLING would put a shadow rehearsal's backup into the LIVE prefix's namespace, where it
    # could collide with the live fold's own backup of the same date -- measured on the first dry
    # run against `graphrag_evidence/shadow_originpolicy`, which wrote its plan to
    # `graphrag_evidence/_backup_pre_corpuslane_<date>`. `_slice_keys` lists `<prefix>/*.jsonl` with
    # Delimiter='/' plus `<prefix>/drivers/`, so a child backup prefix is never re-listed and the
    # copy cannot recurse.
    dst_root = "%s/%s" % (prefix, stamp)
    plan = {k: "%s/%s" % (dst_root, k[len(prefix) + 1:]) for k in keys}
    return {"bucket": bkt, "src_prefix": prefix, "dst_root": dst_root, "plan": plan,
            "n": len(plan)}


def take_backup(s3, bp: dict) -> int:
    """Do the copies and VERIFY BY OBJECT COUNT. `s3.copy` is the MANAGED copy (boto3's transfer
    manager), so a slice over the 5 GB single-part CopyObject ceiling -- `french_wheat` was measured
    at 1.68 GB and the population is growing -- is multiparted automatically instead of failing at
    the API."""
    for src, dst in sorted(bp["plan"].items()):
        s3.copy({"Bucket": bp["bucket"], "Key": src}, bp["bucket"], dst)
    landed = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bp["bucket"],
                                                             Prefix=bp["dst_root"] + "/"):
        landed += len([o for o in page.get("Contents") or [] if o["Key"].endswith(".jsonl")])
    if landed != bp["n"]:
        raise SystemExit("BACKUP REFUSED: copied %d of %d slice objects to s3://%s/%s -- the fold "
                         "does NOT proceed on a partial backup." % (landed, bp["n"], bp["bucket"],
                                                                    bp["dst_root"]))
    print("  backup verified: %d objects at s3://%s/%s" % (landed, bp["bucket"], bp["dst_root"]))
    return landed


def census_write_step() -> list[str]:
    """THE ROLL, derived from the submitter's own gate command so the two can never name different
    modules: it is `_CENSUS_GATE_CMD` MINUS `--diff`, i.e. a plain census run, which is the ONLY
    thing in the estate that writes `<EVIDENCE_S3>/eval/e1_census.json`. Hand-typing the module here
    would be a second definition free to drift from the gate it must roll."""
    sm = _guards()
    return [tok for tok in sm._CENSUS_GATE_CMD if tok != "--diff"]


def census_roll_target(evidence_s3: str) -> str:
    """The s3:// key a plain census run writes under the bound prefix -- i.e. the key step 4 rolls.

    `e1_census.write()` resolves its remote copy as `ev._evid_s3() + "/eval/" + name`
    (e1_census.py:400-408) and `child_env` PINS `EVIDENCE_S3` to exactly `evidence_s3`, so this is a
    derivation of where the roll lands, never a guess."""
    return "%s/%s" % (evidence_s3.rstrip("/"), CENSUS_ARTEFACT)


def assert_baseline_is_the_rolled_key(args, *, echo=print) -> None:
    """GUARD 4 -- THE FOLD MUST DIFF AGAINST THE KEY IT ROLLS, or the gate decays anyway.

    Step 4 writes `<EVIDENCE_S3>/eval/e1_census.json` and can write nowhere else (that is the whole
    point of `child_env`: a rehearsal must never be able to overwrite the live store's baseline). So
    if `--census-baseline` names some OTHER object, this fold advances one key and judges itself
    against another -- the frozen-snapshot defect wearing a rolling fold's clothes.

    On the LIVE path (`--i-know-this-is-live`, which is what the scheduled fold carries) that is
    REFUSED before a dollar is spent. A shadow rehearsal is NOT refused and must not be: a fresh
    shadow prefix holds no census at all, so its only legal baseline is a foreign one -- it diffs
    against the live census and rolls its OWN, which is correct and leaves the live key untouched.
    That case is reported loudly instead of being silently tolerated."""
    target = census_roll_target(args.evidence_s3)
    declared = (args.census_baseline or "").rstrip("/")
    if declared == target:
        echo("  GUARD baseline-roll: PASS (--census-baseline IS the key step 4 rolls, %s -- so next "
             "month's fold diffs against THIS month's store)" % target)
        return
    msg = ("REFUSED: --census-baseline %r is not the key this fold can roll (%s). A fold judges "
           "itself against the baseline and then ADVANCES it; if those are two different objects "
           "the baseline never moves and the gate decays into a no-op -- by construction, silently, "
           "and reading green. The baseline object named in the live schedule was written "
           "2026-08-02T00:36:09Z and NOTHING in the account refreshes it: `e1_census --diff` never "
           "calls write() and no schedule runs a plain census."
           % (args.census_baseline, target))
    if args.i_know_this_is_live and not args.dry_run:
        raise SystemExit(msg)
    echo("  GUARD baseline-roll: NOTE this fold diffs against a FOREIGN baseline (%s) and rolls its "
         "OWN (%s). Legal for a shadow rehearsal -- a fresh shadow prefix holds no census -- and the "
         "live key is NOT touched. It would be REFUSED on the live path."
         % (args.census_baseline, target))


def verify_baseline_advanced(s3, evidence_s3: str, *, since: datetime, echo=print) -> None:
    """THE POST-CONDITION on the roll: after a GREEN chain the rolled object must be NEWER than the
    fold's own start. One HEAD against a fence that would otherwise be decorative.

    `e1_census.write()`'s S3 leg is conditional on `ev._evid_s3()` being set and it prints rather
    than raises; a future refactor, a dropped environment variable or an `--local-only` creeping into
    the step would leave the chain green with the baseline untouched, and the NEXT month's gate would
    be frozen again with nobody told. A green fold whose baseline did not move is a red fold."""
    bkt, key = cc._split_s3(census_roll_target(evidence_s3))
    from botocore.exceptions import ClientError
    try:
        got = s3.head_object(Bucket=bkt, Key=key)["LastModified"]
    except ClientError as exc:
        raise SystemExit("REFUSED: the rolled census s3://%s/%s could not be read after a GREEN "
                         "chain (%s). The fold's own gate is judged against that object next month; "
                         "a fold that cannot prove it rolled did not roll."
                         % (bkt, key, type(exc).__name__)) from exc
    if got <= since:
        raise SystemExit("REFUSED: the chain returned 0 but s3://%s/%s still carries %s, which is "
                         "not newer than this fold's start (%s). The census WRITE step did not "
                         "reach the store, so next month's gate would diff against a snapshot this "
                         "fold never refreshed -- the exact frozen-baseline defect step 4 exists to "
                         "end." % (bkt, key, got.isoformat(), since.isoformat()))
    echo("  baseline ROLLED: s3://%s/%s now %s (the prior copy was archived to eval/e1_census_<UTC>"
         ".json by write()'s archive-before-overwrite)" % (bkt, key, got.isoformat()))


def slices_written(manifest: dict) -> int:
    """SLICE OBJECTS written by the rebuild, across every layer -- the fold's real work number.

    NOT `manifest["docs"]["written"]`, AND THE DIFFERENCE IS MEASURED, not a preference. A fold is a
    RE-DERIVATION from the chunk cache, never an ingestion, so `docs.written` is 0 on a PERFECT fold:
    the live manifest of the last real fold
    (eval/write_manifest_rebuild_20260821T212319Z.json, read 2026-09-22) records
    `docs {"written": 0, "overwritten": 0}` beside `slices {"commodity": 52, "drivers": 144}` and
    2,742,847 rows. An alarm on `docs.written == 0` would have paged on a 4 h 29 m fold that rewrote
    196 objects. 196 is the healthy value here; 0 means the fold wrote nothing."""
    return sum(len(recs or {}) for recs in (manifest.get("slices") or {}).values())


def newest_manifest_since(s3, evidence_s3: str, *, stamp: str) -> tuple[dict | None, str]:
    """The rebuild manifest THIS fold wrote: the newest `eval/write_manifest_*.json` whose UTC stamp
    is at or after `stamp` (the fold's start), by ONE LIST + at most one GET.

    Deliberately NOT `write_guard.newest_run_manifest()`: that helper prefers the LOCAL
    `configs/graphrag/eval/` archive, which on a laptop returns a 2026-08-21 manifest and would make
    this fold report another pass's numbers. Filtering on the fold's own start stamp means a fold
    that wrote no manifest reports 0 rather than inheriting someone else's 196.

    AND IT MATCHES `write_manifest_rebuild_` ALONE, NOT `write_manifest_*` (R2 MINOR-1). MEASURED
    2026-09-22: `graphrag_evidence/eval/` holds 9 `write_manifest_*` objects and FIVE of them are
    not rebuilds (`seed`, `retrieve` x2, `x2_tail`); the two that were read carry `slices == {}`,
    so `slices_written()` on one of them returns 0. A non-rebuild manifest stamped after this
    fold's own -- which a hand fire beside the chunk pass produces, even though the nominal crons
    (chunk SUN 04:00Z bounded by AttemptDurationSeconds=9000, fold 22nd 08:00Z) do not collide --
    would make a fold that wrote 196 objects report `CorpusFoldSlicesWritten = 0` and fire lane 7's
    `corpus_fold_wrote_nothing` alarm as a FALSE RED. A false green is worse than a red; a false
    RED is how an alarm gets muted."""
    bkt, prefix = cc._split_s3(evidence_s3.rstrip("/") + "/eval/")
    keys: list[str] = []
    try:
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bkt, Prefix=prefix):
            for o in page.get("Contents") or []:
                rel = o["Key"][len(prefix):]
                if (rel.startswith("write_manifest_rebuild_") and rel.endswith(".json")
                        and "/" not in rel):
                    if rel[:-len(".json")].rsplit("_", 1)[-1] >= stamp:
                        keys.append(o["Key"])
        if not keys:
            return None, ("no write_manifest_rebuild_* at or after %s under s3://%s/%s"
                          % (stamp, bkt, prefix))
        newest = max(keys, key=lambda k: (k.rsplit("/", 1)[-1][:-len(".json")].rsplit("_", 1)[-1], k))
        import json as _json
        doc = _json.loads(s3.get_object(Bucket=bkt, Key=newest)["Body"].read().decode("utf-8"))
        return doc, "s3://%s/%s" % (bkt, newest)
    except Exception as exc:                                    # noqa: BLE001 -- a metric never fails a fold
        return None, "manifest unreadable (%s)" % type(exc).__name__


def fold_metric_datums(*, slices: int, failed: bool) -> list[dict]:
    """The THREE family-rolled datums, one constant dimension, no per-slice cardinality.

    `CorpusFoldRuns` is emitted on EVERY outcome -- that is what lets a missing datapoint mean "no
    fold fired" instead of "a fold fired and failed", which is precisely the distinction the estate
    could not make: the EventBridge rule `leviathan-dev-batch-job-failed` targets only a log group,
    the metric filter that feeds the alarm WITH AN ACTION matches only MANAGED_BY_AWS jobs and three
    named jobNames (none of them corpus-*), and the catch-all backstop alarm has 0 alarm actions.
    A monthly fold that failed every month would have paged nobody."""
    dim = [{"Name": "Family", "Value": cc.FAMILY}]
    pairs = ((METRIC_RUNS, 1.0), (METRIC_SLICES_WRITTEN, float(slices)),
             (METRIC_FAILURES, 1.0 if failed else 0.0))
    return [{"MetricName": n, "Dimensions": list(dim), "Value": v, "Unit": "Count"}
            for n, v in pairs]


def fold_ledger_document(*, outcome: str, rc: int, started: datetime, finished: datetime,
                         evidence_s3: str, slices: int, rows: int | None,
                         manifest_label: str, manifest_docs_written: int | None,
                         baseline: str, note: str = "") -> dict:
    """The ledger line the fold leaves at `<EVIDENCE_S3>/fold/last_run.json`, mirroring the chunk
    pass's `coverage/last_run.json`. A leg nothing measures is the defect this lane was opened to
    end, and a CloudWatch datapoint expires -- the ledger is the durable half."""
    return {"stage": "fold", "outcome": outcome, "rc": int(rc),
            "started_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "finished_utc": finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "evidence_s3": evidence_s3.rstrip("/"),
            "slice_objects_written": int(slices),
            "rows_written": rows,
            "run_manifest": manifest_label,
            # Recorded BESIDE the slice count and never in place of it: on a re-derivation this is 0
            # by construction (2026-08-21 measured 0 while 196 objects and 2,742,847 rows moved).
            "manifest_docs_written": manifest_docs_written,
            "census_baseline": baseline,
            "census_rolled_to": census_roll_target(evidence_s3),
            "note": note}


def _emit_and_record(args, s3, doc: dict, datums: list[dict], *, echo=print) -> None:
    """Write the ledger line, then PUT the datums -- in that order and at the same commit point as
    the chunk pass, so a metric that says the fold moved is only true once the record of that move
    is durable. NEITHER failure fails the fold: the fold's own rc is the verdict, and the alarms'
    missing-data treatment owns a silence. Both failures are printed, never swallowed."""
    bkt, key = cc._split_s3("%s/%s" % (args.evidence_s3.rstrip("/"), FOLD_LEDGER_SUFFIX))
    import json as _json
    try:
        s3.put_object(Bucket=bkt, Key=key, Body=_json.dumps(doc).encode("utf-8"),
                      ContentType="application/json")
        echo("  fold ledger -> s3://%s/%s  (%s, %d slice objects)"
             % (bkt, key, doc["outcome"], doc["slice_objects_written"]))
    except Exception as exc:                                    # noqa: BLE001
        echo("  FOLD LEDGER WRITE FAILED (%s) -- the fold's exit code still carries the verdict."
             % type(exc).__name__)
    try:
        import boto3
        boto3.client("cloudwatch", region_name=args.aws_region).put_metric_data(
            Namespace=cc.METRIC_NAMESPACE, MetricData=datums)
        echo("  metrics -> %s %s" % (cc.METRIC_NAMESPACE,
                                     ", ".join("%s=%s" % (d["MetricName"], d["Value"])
                                               for d in datums)))
    except Exception as exc:                                    # noqa: BLE001
        echo("  METRIC EMIT FAILED (%s) -- the ledger STANDS and the missing datapoints read RED "
             "through the liveness alarm's treat_missing_data. Never silently swallowed."
             % type(exc).__name__)


def declared_churn_in_force(*, echo=print) -> dict:
    """GUARD 3's read-only report: the per-slice churn declarations the rebuild's write guard WILL
    read, via the very call `write_guard.plan_write` makes (`load_declared_churn()` -> this image's
    configs/graphrag/declared_churn.json). Printed before the backup and the rebuild so a refusal --
    or an admission -- is legible from the fold's own log.

    This is a REPORT, not a channel: nothing it returns reaches the chain. The child resolves the same
    file from the same image on its own. Never raises: an unreadable manifest is reported and, in
    the guard, admits nothing (fail closed)."""
    try:
        from leviathan.graphrag import write_guard as wg
        dc = wg.load_declared_churn()
    except Exception as exc:                                    # noqa: BLE001 -- a report never fails a fold
        echo("  GUARD churn: the declared-churn manifest could not be read (%s) -- the rebuild's write "
             "guard admits nothing it cannot read (fail closed)." % type(exc).__name__)
        return {"state": "unreadable"}
    rec = dc.record()
    if dc.state == "invalid":
        echo("  GUARD churn: declared-churn manifest INVALID at %s -- EVERY declaration is ignored and "
             "the 10%% line applies to every slice: %s"
             % (dc.path, "; ".join(rec["errors"])[:400]))
    elif not dc.active:
        echo("  GUARD churn: no per-slice churn declaration in force (%s: %s) -- the 10%% line applies "
             "to every slice." % (dc.path, dc.state))
    for key, e in sorted(dc.active.items()):
        span = e.get("expected_span") or {}
        echo("  GUARD churn: DECLARED %s -> expected_population %s, expected_span %s (declared_on %s, "
             "expires %s) -- admitted only at that population / those endpoints"
             % (key, e.get("expected_population", "-"),
                ",".join("%s=%s" % (k, span[k]) for k in sorted(span)) or "-",
                e["declared_on"], e["expires"]))
    for key, why in sorted(dc.inactive.items()):
        echo("  GUARD churn: the declaration for %s is NOT in force: %s" % (key, why))
    return rec


def chain_steps(args) -> list[list[str]]:
    """The gated chain, in order, reusing the submitter's own constants so a change there lands here:

        1. driver_slices_manifest --check   -- G2 / D-EI-1, BEFORE any compute: a term edit that
                                               never reached the tracked mirror re-routes the whole
                                               driver layer, and catching it after a 4h29m re-embed
                                               is catching it too late.
        2. evidence_batch --rebuild-slices  -- the fold itself. NO --allow-churn, ever.
        3. e1_census --diff --baseline <X>  -- the W1.3 standing gate, with an EXPLICIT baseline.
                                               Without one it resolves NOTHING on a shadow prefix
                                               and passes SILENTLY (a documented trap,
                                               submit_batch_evidence_maintenance.py:118-127).
        4. e1_census (a plain WRITE run)    -- THE ROLL. See below.

    STEP 4 IS THE R2 FATAL, AND IT IS THE WHOLE REASON THE GATE ABOVE MEANS ANYTHING NEXT MONTH.

    An EventBridge Scheduler Input is frozen at apply time, so `--census-baseline` names ONE key
    forever: `s3://leviathan-dev-shahem-001/graphrag_evidence/eval/e1_census.json`, whose object was
    written 2026-08-02T00:36:09Z and which NOTHING in the account refreshes -- `e1_census --diff` is
    a read-only gate that never calls `write()` (e1_census.py:763-766), and no schedule anywhere runs
    a plain census. The gate's teeth are `population_drops` (POP_DROP_REFUSE = 0.10), which compares
    each slice's `n_routed_props` to THE BASELINE'S value. This lane exists to make the store GROW
    every month, so a baseline that never moves decays into a no-op: by 2027-03 a slice carrying
    twice its August population could lose half of everything ingested since August and still sit at
    the August number, `population_drops` would find nothing, `run_diff` would return 0, and the
    operator would be told the fold was clean. A fence that reads green while a true regression
    passes is worse than no fence.

    THE SHAPE IS THE ESTATE'S OWN, not an invention: `jobs/audit/advance_rolling_census.py` (the SFN
    [Reconcile] task) re-runs its census after a GREEN gate and a GREEN promote and writes it to the
    key the NEXT gate reads, and it refuses to enshrine a dirty census as a baseline (`if rc != 0:
    return rc`, BEFORE the upload). Step 4 is the same act for this store: `run_chain` stops at the
    FIRST nonzero, so the write runs ONLY when the lint, the rebuild and the gate all returned 0 --
    NO ROLL ON RED. And `write()` copies the prior `e1_census.json` to `e1_census_<UTC>.json` (local
    and remote) BEFORE overwriting, so no BEFORE snapshot is lost; three such archives already exist
    on S3, so the mechanism is proven, not assumed.

    The frozen Input does not change: it goes on naming a key that the fold now ROLLS. The first
    fold after this change diffs against the 2026-08-02 object exactly once; every fold after that
    diffs against the previous fold's store, which is what a rolling regression gate means.
    """
    sm = _guards()
    steps = [list(sm._MANIFEST_LINT_CMD),
             sm.build_command(mode="rebuild-slices"),           # allow_churn deliberately omitted
             list(sm._CENSUS_GATE_CMD) + ["--baseline", args.census_baseline],
             census_write_step()]
    if args.with_pg_load:
        steps.append(["-m", "jobs.utils.load_pg_evidence", "--all",
                      "--table", args.pg_shadow_table])
    if args.with_pg_swap:
        steps.append(["-m", "jobs.utils.pg_evidence_swap", "--swap"])
    return steps


def child_env(evidence_s3: str, base=None) -> dict:
    """The environment every chain step runs in, with `EVIDENCE_S3` PINNED to the prefix the guards
    validated.

    THIS IS THE FIX FOR THE INVERTED GUARD, and it is worth stating exactly. `chain_steps` builds
    step 2 from `sm.build_command(mode="rebuild-slices")`, which is literally
    `["-m", "leviathan.graphrag.evidence_batch", "--rebuild-slices"]`
    (submit_batch_evidence_maintenance.py:55). `evidence_batch` HAS NO `--evidence-s3` FLAG: its only
    channel is `evidence._evid_s3()` = `os.environ["EVIDENCE_S3"]` (evidence.py:42-43). The first
    draft called `subprocess.call([sys.executable, *step])` with no `env=`, so the child inherited
    the jobdef's baked LIVE prefix while GUARD 1 had validated the SHADOW one -- MEASURED: with
    `EVIDENCE_S3=s3://leviathan-dev-shahem-001/graphrag_evidence` and
    `--evidence-s3 .../shadow_originpolicy` the guard printed PASS, the backup plan took the shadow's
    199 objects, and a child launched exactly as `run_chain` launched it resolved the LIVE prefix.
    A shadow rehearsal would have re-embedded ~107K vectors over the 196 live slice objects with no
    rollback for what it actually overwrote. `main` binds the variable for THIS process; this
    function pins it for every child, so neither an inherited value nor a later mutation can move it.

    NOT COVERED: the rest of the environment is inherited verbatim on purpose -- the bge-m3 backend,
    the AWS credentials chain and the pg DSN all ride it, and a scrubbed env would break the chain in
    ways that have nothing to do with the store's identity."""
    import os
    return {**(os.environ if base is None else base), "EVIDENCE_S3": evidence_s3.rstrip("/")}


def run_chain(steps: list[list[str]], *, env: dict) -> int:
    """Each step runs only if every earlier step exited 0, and the chain exits with the FIRST nonzero
    code -- so a failed rebuild is never masked by a clean census nor vice versa. `env` is REQUIRED
    (never defaulted to the ambient environment): see `child_env`."""
    for step in steps:
        print("  RUN: python %s" % " ".join(step))
        rc = subprocess.call([sys.executable, *step], env=env)
        if rc:
            print("  STEP FAILED rc=%d -- chain stops here." % rc)
            return rc
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Phase G monthly fold (backup -> gated rebuild -> pg)")
    ap.add_argument("--stage", required=True, choices=("fold",),
                    help="only 'fold' exists; the flag is required so the frozen schedule command "
                         "is explicit and the descriptor lint's required-option probe sees it")
    ap.add_argument("--evidence-s3", required=True, metavar="S3_URI", dest="evidence_s3",
                    help="REQUIRED read+write prefix. A SHADOW prefix for a rehearsal; the live "
                         "prefix only with --i-know-this-is-live and the owner's yes")
    ap.add_argument("--census-baseline", default=None, metavar="PATH_OR_S3URI",
                    help="the EXPLICIT prior e1_census.json the in-job gate diffs against. REQUIRED "
                         "for a live run: without it the gate resolves no baseline on a shadow "
                         "prefix and passes silently")
    ap.add_argument("--i-know-this-is-live", action="store_true", dest="i_know_this_is_live",
                    help="escape hatch for the live-prefix assertion (owner's yes, step iv)")
    ap.add_argument("--no-backup", action="store_true",
                    help="skip the pre-rebuild copy. ONLY legal against a shadow prefix that is "
                         "itself a backup; a live fold with no backup is refused below")
    ap.add_argument("--with-pg-load", action="store_true",
                    help="append the blue-green shadow load (OFF by default; R3 is manual for its "
                         "first three cycles)")
    ap.add_argument("--with-pg-swap", action="store_true",
                    help="append the transactional swap (OFF by default; needs the index assertion "
                         "and a free-space check first)")
    ap.add_argument("--pg-shadow-table", default="evidence_props_shadow")
    ap.add_argument("--aws-region", default="us-east-1", dest="aws_region")
    ap.add_argument("--dry-run", action="store_true")
    # THERE IS DELIBERATELY NO --allow-churn HERE. See the header: an add-only fold must never need
    # one, and a refusal on an add-only pass IS the finding. The deck pins the absence.
    return ap


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)

    started = datetime.now(timezone.utc)
    start_stamp = started.strftime("%Y%m%dT%H%M%SZ")
    stamp = started.strftime(BACKUP_PREFIX_FMT)
    print("stage=fold  evidence_s3=%s  dry_run=%s  backup=%s"
          % (args.evidence_s3, args.dry_run, "SKIPPED" if args.no_backup else stamp))

    # ---- GUARD 0: BIND THE PREFIX BEFORE ANYTHING READS IT ---------------------------------------
    # This runs FIRST, ahead of the live-prefix assertion, because everything below -- the guard, the
    # backup plan, and above all the `--rebuild-slices` child -- must describe ONE store. See
    # `child_env` for the measured inversion this closes.
    bound = cc.bind_evidence_prefix(args.evidence_s3, require=True)
    args.evidence_s3 = bound

    # ---- GUARD 1: the live-prefix assertion, INLINE (the descriptor path has no submitter) --------
    sm = _guards()
    try:
        sm.assert_not_live_rebuild(evidence_s3=args.evidence_s3, job_definition=JOBDEF,
                                   aws_region=args.aws_region,
                                   override=args.i_know_this_is_live)
        print("  GUARD live-prefix: PASS (%s is not the jobdef's baked EVIDENCE_S3, or the override "
              "was declared)" % args.evidence_s3)
    except SystemExit as exc:
        if not args.dry_run:
            raise
        # The submitter's own refusal text carries an em-dash; this stdout must stay ASCII (Windows
        # console is cp1252 and a Batch log line that cannot encode is a UnicodeEncodeError, not a
        # message). Sanitised on the way out, never rewritten at the source.
        msg = str(exc).replace("\n", " ").encode("ascii", "backslashreplace").decode("ascii")
        print("  GUARD live-prefix WOULD REFUSE: %s" % msg[:400])

    # ---- GUARD 2: an EXPLICIT census baseline, or the gate passes silently -----------------------
    if not args.census_baseline:
        msg = ("REFUSED: --census-baseline is required. Without an explicit baseline the "
               "e1_census --diff gate resolves NOTHING on a shadow prefix (no local archive "
               "in-image: configs/graphrag/eval/ is in .dockerignore; no eval/ prefix under a fresh "
               "shadow) and PASSES SILENTLY -- a documented trap at "
               "submit_batch_evidence_maintenance.py:118-127.")
        if not args.dry_run:
            raise SystemExit(msg)
        print("  " + msg)
        args.census_baseline = "<REQUIRED -- not supplied in this dry run>"

    # ---- GUARD 3: never --allow-churn ------------------------------------------------------------
    print("  GUARD churn: this task offers NO --allow-churn flag. An add-only fold must never need "
          "one; a refusal on an add-only pass IS the finding. (2026-08-21 ran --allow-churn 50.0 "
          "and lost barley_yellow_dwarf_virus and wheat_blast to 'unwritten'.) An INTENDED drop is "
          "declared per slice in configs/graphrag/declared_churn.json, which the rebuild reads itself:")
    declared_churn_in_force()

    import boto3
    s3 = boto3.client("s3", region_name=args.aws_region)

    # ---- GUARD 4: the baseline this fold judges itself against is the one it ROLLS ---------------
    # It runs here -- after the client, before the backup's LIST -- so a refusal costs nothing AND
    # still REPORTS. A pre-flight refusal is a fire that happened and wrote nothing; reported, the
    # failure alarm sees it the next day, and unreported a monthly fold could refuse for 35 days
    # before the liveness alarm noticed. (In a dry run this cannot raise, by construction.)
    try:
        assert_baseline_is_the_rolled_key(args)
    except SystemExit as exc:
        note = str(exc).replace("\n", " ").encode("ascii", "backslashreplace").decode("ascii")[:600]
        print("  REFUSED: %s" % note)
        _emit_and_record(
            args, s3,
            fold_ledger_document(outcome="CORPUS_FOLD_REFUSED", rc=1, started=started,
                                 finished=datetime.now(timezone.utc),
                                 evidence_s3=args.evidence_s3, slices=0, rows=None,
                                 manifest_label="<none: refused before any work>",
                                 manifest_docs_written=None, baseline=args.census_baseline,
                                 note=note),
            fold_metric_datums(slices=0, failed=True))
        return 1

    # ---- STEP 1: the pre-rebuild backup ----------------------------------------------------------
    bp = None
    if args.no_backup:
        if args.i_know_this_is_live:
            raise SystemExit("REFUSED: --no-backup with --i-know-this-is-live. A LIVE rebuild "
                             "rewrites all 52 commodity + 144 driver objects in place and the "
                             "write guard is demonstrably not a substitute for the copy.")
        print("  backup SKIPPED by flag (legal only against a shadow prefix).")
    else:
        bp = backup_plan(s3, args.evidence_s3, stamp=stamp)
        print("  backup plan: %d slice objects  s3://%s/%s  ->  s3://%s/%s"
              % (bp["n"], bp["bucket"], bp["src_prefix"], bp["bucket"], bp["dst_root"]))
        if bp["n"] == 0:
            print("  NOTE 0 slice objects under the prefix. On a SHADOW rebuild that is also the "
                  "embed-once seed's refusal condition: `_slice_object_names`' REVIEW-M3 rider says "
                  "a shadow target must ALREADY hold these slices or the seed refuses and the whole "
                  "lever is unused (evidence_batch.py:1481-1495).")

    steps = chain_steps(args)
    env = child_env(args.evidence_s3)
    # THE POST-CONDITION. The guard above validated `args.evidence_s3`; the chain below rebuilds
    # whatever `EVIDENCE_S3` names. If those two can differ the guard is decorative, so they are
    # compared here rather than assumed -- one string compare against a catastrophe that reports PASS.
    if env.get("EVIDENCE_S3", "").rstrip("/") != args.evidence_s3.rstrip("/"):
        raise SystemExit("REFUSED: the chain's EVIDENCE_S3 (%s) is not the prefix the live-prefix "
                         "guard validated (%s). A rebuild MUST run against the store the guard "
                         "cleared." % (env.get("EVIDENCE_S3"), args.evidence_s3))
    print("  chain EVIDENCE_S3 = %s (pinned into every child's environment; evidence_batch has NO "
          "--evidence-s3 flag, so this variable IS the store)" % env.get("EVIDENCE_S3"))
    print("  chain (%d steps, first nonzero wins):" % len(steps))
    for i, step in enumerate(steps, 1):
        print("    %d. python %s" % (i, " ".join(step)))

    if args.dry_run:
        # THE CHILD PROBE. The first draft's defect was invisible to a dry run precisely because the
        # dry run PRINTED the chain and never launched it, so nothing measured what a step would
        # actually read. This launches one throwaway child exactly as `run_chain` launches a step
        # and prints the prefix it resolves -- `os.environ["EVIDENCE_S3"]` is verbatim what
        # `evidence._evid_s3()` returns (evidence.py:42-43). It writes nothing and costs one process.
        try:
            probe = subprocess.run([sys.executable, "-c",
                                    "import os; print(os.environ.get('EVIDENCE_S3') or '<unset>')"],
                                   env=env, capture_output=True, text=True, timeout=60)
            print("  CHILD PROBE: a step launched exactly as run_chain launches it resolves "
                  "EVIDENCE_S3 -> %s" % (probe.stdout.strip() or "<no output>"))
        except Exception as exc:                            # noqa: BLE001
            print("  CHILD PROBE unavailable (%s) -- reported, never assumed" % type(exc).__name__)
        print("  DRY RUN: nothing copied, nothing rebuilt, nothing loaded, nothing swapped, "
              "NOTHING EMITTED and no ledger line (the lane's contract).")
        print("  WOULD ROLL: %s ; WOULD EMIT: %s"
              % (census_roll_target(args.evidence_s3),
                 ", ".join("%s=%s" % (d["MetricName"], d["Value"])
                           for d in fold_metric_datums(slices=0, failed=False))))
        print("  NEXT (operator, and NOT this task): pg shadow load -> missing_canonical_indexes "
              "assertion -> free-space check -> pg_evidence_swap --swap -> pg_ann_build recall "
              "re-certification -> timeline rebuild -> delete the PREVIOUS cycle's backup prefix.")
        return 0

    # ---- THE RUN, AND THE RECORD OF IT ----------------------------------------------------------
    # Every exit from here on leaves a ledger line and three datums, because the outcome this lane
    # could NOT previously distinguish is "the fold failed" from "the fold never fired": a direct
    # batch:submitJob schedule named corpus-fold matches no metric filter that feeds an alarm with
    # an action, and the catch-all backstop alarm has zero actions. `CorpusFoldRuns` is that
    # distinction; a refusal (a partial backup, a baseline that did not roll) is a fire that wrote
    # nothing and says so.
    rc, outcome, note = 0, "CORPUS_FOLD_OK", ""
    try:
        if bp is not None:
            take_backup(s3, bp)
        rc = run_chain(steps, env=env)
        if rc == 0:
            verify_baseline_advanced(s3, args.evidence_s3, since=started)
        else:
            outcome = "CORPUS_FOLD_CHAIN_FAILED"
            note = "the chain stopped at the first nonzero step; NO ROLL ON RED."
    except SystemExit as exc:                                   # a guard refused, mid-run
        rc, outcome = (int(exc.code) if isinstance(exc.code, int) and exc.code else 1), \
                      "CORPUS_FOLD_REFUSED"
        note = str(exc).replace("\n", " ").encode("ascii", "backslashreplace").decode("ascii")[:600]
        print("  REFUSED: %s" % note)
    except Exception as exc:                                    # noqa: BLE001 -- see below
        # R2 MINOR-2. "Every exit leaves a ledger line and three datums" was true only for
        # SystemExit. `take_backup` raises SystemExit for a PARTIAL copy, but `s3.copy` itself
        # raises ClientError / S3UploadFailedError, and that escaped `main` with NO ledger and NO
        # datum -- so a fold that died in its own backup was indistinguishable from a fold that
        # NEVER FIRED, which is precisely the distinction `CorpusFoldRuns` was added to make, and
        # it would have surfaced on the 35-day liveness alarm instead of the next-day failure one.
        # The exception is RECORDED, NOT SWALLOWED: the traceback goes to stdout, the class and
        # message go in the ledger note, rc is nonzero, and `CorpusFoldFailures=1` is emitted below
        # on the same path as every other outcome. A fence CORRECTS; it does not delete.
        import traceback
        rc, outcome = 1, "CORPUS_FOLD_CRASHED"
        note = ("%s: %s" % (type(exc).__name__, exc)).replace("\n", " ").encode(
            "ascii", "backslashreplace").decode("ascii")[:600]
        print("  CRASHED: %s" % note)
        traceback.print_exc()

    manifest, label = newest_manifest_since(s3, args.evidence_s3, stamp=start_stamp)
    n_slices = slices_written(manifest) if manifest else 0
    rows = (sum(int(r.get("after_n") or 0)
                for recs in (manifest.get("slices") or {}).values() for r in recs.values())
            if manifest else None)
    _emit_and_record(
        args, s3,
        fold_ledger_document(outcome=outcome, rc=rc, started=started,
                             finished=datetime.now(timezone.utc), evidence_s3=args.evidence_s3,
                             slices=n_slices, rows=rows, manifest_label=label,
                             manifest_docs_written=((manifest.get("docs") or {}).get("written")
                                                    if manifest else None),
                             baseline=args.census_baseline, note=note),
        fold_metric_datums(slices=n_slices, failed=rc != 0))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
