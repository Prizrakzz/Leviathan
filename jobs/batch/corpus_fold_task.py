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

WHAT THIS FILE DELIBERATELY DOES NOT DO.

* IT NEVER PASSES `--allow-churn`. An add-only lane must never need it, and if the live rebuild
  refuses, THAT REFUSAL IS THE FINDING. There is no flag here to override it.
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
    """
    sm = _guards()
    steps = [list(sm._MANIFEST_LINT_CMD),
             sm.build_command(mode="rebuild-slices"),           # allow_churn deliberately omitted
             list(sm._CENSUS_GATE_CMD) + ["--baseline", args.census_baseline]]
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

    stamp = datetime.now(timezone.utc).strftime(BACKUP_PREFIX_FMT)
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
          "and lost barley_yellow_dwarf_virus and wheat_blast to 'unwritten'.)")

    # ---- STEP 1: the pre-rebuild backup ----------------------------------------------------------
    import boto3
    s3 = boto3.client("s3", region_name=args.aws_region)
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
        print("  DRY RUN: nothing copied, nothing rebuilt, nothing loaded, nothing swapped.")
        print("  NEXT (operator, and NOT this task): pg shadow load -> missing_canonical_indexes "
              "assertion -> free-space check -> pg_evidence_swap --swap -> pg_ann_build recall "
              "re-certification -> timeline rebuild -> delete the PREVIOUS cycle's backup prefix.")
        return 0

    if bp is not None:
        take_backup(s3, bp)
    return run_chain(steps, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
