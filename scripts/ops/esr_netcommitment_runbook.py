#!/usr/bin/env python
"""SILVER-F030 BF-W2 (ESR NET-COMMITMENT) RUNBOOK -- prints every step's exact command.

    python scripts/ops/esr_netcommitment_runbook.py            # print every step
    python scripts/ops/esr_netcommitment_runbook.py --step S5  # print one step
    python scripts/ops/esr_netcommitment_runbook.py --step CHECK     # AWS-FREE local preflight
    python scripts/ops/esr_netcommitment_runbook.py --step ROLLBACK  # the layered rollback

DRY RUN BY CONSTRUCTION.  There is no ``--run``.  No code path here submits a Batch job, writes
S3, registers a job definition, runs terraform or applies an ALTER: every mutating command is
PRINTED for the operator to paste, and ``--step CHECK`` reads local files only.  Commands are
WINDOWS POWERSHELL 5.1: chained with ``;``, never with ``&&`` (a parser error in 5.1).

WHAT THE LANE SHIPS
-------------------
The five FAS net-commitment fields -- accumulatedExports / currentMYNetSales /
currentMYTotalCommitment / nextMYOutstandingSales / nextMYNetSales -- are promoted into the ESR
bronze transform (float64, MT, INV-4 nullable) and emitted by the silver transform as
``*_1000mt``, UNCONDITIONALLY and strictly at the TAIL after ``source``.  They land on
``silver_esr_compact`` only; ``silver_esr`` takes a written REFUSAL.  They stay OUT of
``value_columns`` until measured.

THE FIVE THINGS AN OPERATOR MUST NOT GET WRONG, each with its measurement
------------------------------------------------------------------------
1. THE IMAGE IS BUILT FROM A CLEAN WORKTREE **PLUS THE GITIGNORED OVERLAY** -- never from this
   working tree, and never from a bare worktree either.  The shared tree carries other lanes'
   uncommitted work inside the Dockerfile COPY set (src/, jobs/, configs/, sql/), and
   ``scripts/build_push_worker.ps1`` tars ``$RepoRoot`` while stamping BUILD_GIT_COMMIT from
   ``git rev-parse HEAD`` -- an image whose own manifest asserts a commit it does not contain,
   riding onto the gate 26 scheduled families share.  So S1 builds from a CLEAN worktree at the
   lane's commit through ``scripts/ops/make_worker_context_tar.py --repo <worktree>``, which
   REFUSES a dirty COPY set and tars ``git archive`` rather than the filesystem.

   THAT IS ONLY HALF THE RECIPE.  ``make_worker_context_tar.py`` takes the TRACKED bytes from
   ``git archive <ref>``, but it reads the gitignored ``configs/graphrag`` overlay from the
   ``--repo`` WORKING TREE -- and ``git worktree add`` checks out TRACKED files only.  A BARE
   worktree therefore yields ``overlay_files: 0`` and an image that bakes ZERO gitignored configs,
   onto the very gate whose ``jobs/audit/silver_rebuild_gate.py`` imports
   ``leviathan.graphrag.config_check`` and the numbers modules that read that subtree at runtime.
   That is the estate's recorded "worktree builds bake ZERO gitignored configs" incident, and it
   is WORSE than the dirty bake this step was written to prevent.  MEASURED in the main tree
   2026-09-04: 141 gitignored files, 4,751,532 bytes (69 causal DAGs, 7 under gold/, 7 under
   numbers/, 58 top-level YAMLs), overlay_sha256
   b4855da299efbf502e6ddc168edf0ce1956fefffe81f9fb81d84b54dc0f4f289.  S1 COPIES those files into
   the worktree BEFORE the tar, and the summary's ``overlay_files`` is a GATE: ``> 0`` proceeds,
   ``0`` is a REFUSAL.  The 2026-09-04 pink-vintages flip built its image with exactly this
   recipe (141 overlay files).  ``--step CHECK`` greps S1 for every clause of it.  And since
   2026-09-04 the gate is a NON-ZERO EXIT and not only a sentence: ``make_worker_context_tar
   .py`` REFUSES ``overlay_files: 0`` outright unless ``--allow-empty-overlay`` is passed
   (verify-2 V2-NEW-2 -- before that, nothing in the estate exited non-zero on a zero
   overlay).

2. THE JOBDEF ENVELOPE IS COPIED, NEVER RE-AUTHORED.  MEASURED LIVE 2026-09-04:

       leviathan-dev-esr-bronze-to-silver     rev 8   2 vCPU / 12,288 MiB
       leviathan-dev-silver-publisher-runner  rev 36  2 vCPU / 12,288 MiB
       leviathan-dev-usda-esr-bronze          rev 20  2 vCPU /  4,096 MiB
       leviathan-dev-silver-gate              rev 34  2 vCPU /  8,192 MiB

   The 12,288 MiB on the two silver jobdefs is the post-OOM bump of 2026-09-03 and ANY
   re-registration MUST preserve it.  ``jobs/submit/submit_batch_b2s_esr.py`` hardcodes
   ``MEMORY: "4096"`` and a stale image digest for the first of those two: DO NOT USE IT for S4
   or S7.  Re-register only through ``scripts/ops/repin_jobdef_digest.py``, which copies the live
   revision verbatim, changes one field, and asserts the envelope both before and after.

3. THE FRAME GOT WIDER AND THE ENVELOPE DID NOT.  MEASURED on 80 real bronze objects through
   both transforms: 306.35 -> 346.35 bytes/row deep (+40.00 B/row, exactly five float64,
   +13.1%), 13 -> 18 columns.  Extrapolated over the whole bronze layer (143,332,722 parquet
   bytes at 0.09711 rows/byte) the ``--vintage-mode all`` concat is ~13.92M rows: one copy
   3.97 -> 4.49 GiB, the two-copy concat peak 7.94 -> 8.98 GiB against a 12.0 GiB envelope
   (66.2% -> 74.8%).  It fits at 12,288 MiB and OOMs immediately at 4,096.

4. THE BOUND IS MEASURED, NOT ASSERTED.  Run the raw census FIRST (S0).  MEASURED 2026-09-04 over
   ALL 446 dated raw objects: every one of the 12 as_of vintages, 20260712 through 20260904,
   carries all five keys -- 446/446, no exceptions, no per-commodity tail.  There is NO
   pre-publication vintage in raw, so the earlier plan's ``--as-of-min 20260813`` would have
   excluded six vintages whose raw does carry the fields, and its verdict sentence ("0.0 before
   20260813") could not have failed.  The bound is 20260712 and the verdict is restated in S4.

5. AN UNDATED RAW KEY IS NEVER STAMPED WITH TODAY.  MEASURED: raw holds 1,901 JSON objects, 446
   dated and 1,455 undated, and every one of the 1,901 has a raw_meta sidecar.  Bronze holds
   8,920 objects across 13 as_of vintages of which only 446 (5.0%) derive from a dated raw key:
   8,474 are FABRICATED vintages minted by stamping an undated backfill payload with the run
   date, 1,414 of them at as_of=20260904 alone.  ``jobs/batch/esr_task.py`` now refuses that: an
   undated key is out of scope unless ``--include-backfill`` is passed, and its as_of then comes
   from the sidecar's download_timestamp (measured 2026-05-24 / 2026-08-20), never from the
   clock.  The pre-existing 8,474 are a NAMED RESIDUAL, not this lane's to rewrite -- see
   RESIDUALS at the end of S9.

   THE LAW NOW HOLDS IN ALL FOUR ESR WRITERS, not only the Batch one (re-review NEW-2, plus
   the FOURTH writer that verify-2 V2-NEW-1 found outside the sentence -- this census is a
   grep over jobs/, dags/, src/leviathan/ and scripts/, not a memory):

       jobs/batch/esr_task.py                   resolves as_of: raw key -> an explicit operator
                                                date -> the raw_meta sidecar -> REFUSE
       jobs/glue/raw_to_bronze_usda_esr.py      backfill mode REFUSES by name (it has no route to
                                                a sidecar and used to stamp --ingest_date onto
                                                every undated key); weekly mode is unaffected --
                                                there the as_of IS the raw key's own segment
       jobs/ingest/backfill_bronze_usda_esr.py  the LOCAL TWIN of that Glue backfill, and the
                                                path an operator reaches for FIRST (its own
                                                first line advertised it as the way around Glue
                                                quota limits). --ingest-date DEFAULTED TO TODAY
                                                and every key it read was UNDATED, so a bare
                                                `python jobs/ingest/backfill_bronze_usda_esr.py`
                                                minted a whole vintage with NO flags at all. It
                                                now REFUSES by name and no clock default
                                                survives anywhere in the module
       jobs/ingest/backfill_silver_usda_esr.py  --as-of-date is REQUIRED, the today's-date default
                                                is deleted: that one argument is BOTH the bronze
                                                partition read and the silver partition written

   THE LAW-ABIDING FIFTH, named so the next reader does not re-discover the census:
   dags/airflow/esr_weekly_ingest_dag.py writes bronze INLINE (transform_all_to_bronze) and its
   as_of is the uploaded raw key's OWN as_of segment; today's date reaches ingest_date only.
   Measured by AST over those four roots, the callers of bronze_esr_key / silver_esr_key are
   exactly esr_task.py, the Glue job, backfill_silver_usda_esr.py and that DAG --
   backfill_bronze_usda_esr.py has DROPPED OUT of the census because it can no longer name a
   partition key at all, which is what its refusal means. jobs/ingest/fetch_usda_esr.py names
   the raw keys and writes RAW only; it is not a partition writer.

ASCII-only output.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

REGION = "us-east-1"
ACCOUNT = "668891723125"
BUCKET = "leviathan-dev-shahem-001"
DB = "leviathan_dev"
QUEUE = "leviathan-dev-queue-ondemand"

WORKER_REPO = "leviathan-dev-leviathan-worker"
ECR_URL = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{WORKER_REPO}"
JD_KANIKO = "leviathan-dev-kaniko-build"

# name -> (live revision measured 2026-09-04, vCPU, MiB). The repin helper asserts these BEFORE it
# copies, so a jobdef someone else moved in the meantime stops the rollout instead of riding it.
JOBDEFS = (
    ("leviathan-dev-usda-esr-bronze", 20, "2", "4096"),
    ("leviathan-dev-esr-bronze-to-silver", 8, "2", "12288"),
    ("leviathan-dev-silver-publisher-runner", 36, "2", "12288"),
    ("leviathan-dev-silver-gate", 34, "2", "8192"),
)

TABLE = "silver_esr_compact"
CENSUS_OUT = "data/esr_netcommitment/raw_key_census_20260904.json"
MANIFEST_URI = f"s3://{BUCKET}/silver/esr/_manifests/silver_esr_compact-all.json"
BASELINE_URI = f"s3://{BUCKET}/cascade_census/rolling/esr_weekly/census.json"

# Every number below was measured; the step that reads it says how.
MEASURED = {
    "raw_objects_total": 1901,
    "raw_objects_dated": 446,
    "raw_objects_undated": 1455,
    "raw_sidecars": 1901,
    "raw_vintages": 12,
    "raw_first_vintage": "20260712",
    "raw_last_vintage": "20260904",
    "raw_objects_carrying_all_five": 446,
    "bronze_objects": 8920,
    "bronze_from_dated_raw": 446,
    "bronze_fabricated_vintages": 8474,
    "silver_objects": 428,
    "silver_bytes_per_row_head": 306.35,
    "silver_bytes_per_row_widened": 346.35,
    "silver_bytes_per_row_delta": 40.00,
    "all_vintage_rows_est": 13918971,
    "concat_peak_gib_head": 7.94,
    "concat_peak_gib_widened": 8.98,
    "envelope_gib": 12.0,
}

FIVE_SILVER = ("accumulated_exports_1000mt", "current_my_net_sales_1000mt",
               "current_my_total_commitment_1000mt", "next_my_outstanding_sales_1000mt",
               "next_my_net_sales_1000mt")

REBRONZE_BOUND = MEASURED["raw_first_vintage"]

KMS_ENV = [{"name": "LEVIATHAN_APPROVAL_MODE", "value": "kms"},
           {"name": "LEVIATHAN_KMS_KEY_ID", "value": "alias/leviathan-dev-publish-signer"}]

# THE IMAGE RECIPE, clause by clause. `--step CHECK` greps S1 for every one of these, so a later
# edit cannot quietly drop the overlay copy or the overlay_files gate and leave the step reading
# like a build. MEASURED 2026-09-04 in the main tree: 141 gitignored configs/graphrag files,
# 4,751,532 bytes. A worktree has ZERO of them until step (2) runs, and a zero-overlay image on
# leviathan-dev-silver-gate is the estate's recorded incident, not a hypothetical.
S1_OVERLAY_CLAUSES = (
    "ls-files --others --ignored --exclude-standard -- configs/graphrag",
    "Copy-Item -LiteralPath",
    "make_worker_context_tar.py --repo",
    "overlay_files   MUST be > 0",
    "overlay_files: 0 IS A REFUSAL",
)
OVERLAY_FILES_MEASURED = 141
OVERLAY_BYTES_MEASURED = 4751532


def s1_overlay_missing() -> list[str]:
    """The mandatory image-recipe clauses ABSENT from S1. Empty means the recipe is intact."""
    s1 = "\n".join(next(c for t, c in steps("check") if t.startswith("S1")))
    return [clause for clause in S1_OVERLAY_CLAUSES if clause not in s1]


# Container overrides are written to a FILE and passed as file://, never inlined: PowerShell 5.1
# quoting of nested JSON on an AWS CLI argument is the classic own-goal, and a file has none of it.


def steps(run_id: str) -> list[tuple[str, list[str]]]:
    tar = f"esr_netcommitment_context_{run_id}.tar.gz"
    tag = f"{run_id}-esr-netcommitment"
    worktree = "C:\\Users\\User\\Desktop\\Leviathan_build_esr"
    return [
        ("S0  MEASURE THE RAW BOUND FIRST -- read-only, no build, no write, ~7 MB of ranged GETs.", [
            "# The bound and the verdict sentence are DERIVED from this, never asserted ahead of it.",
            f"python jobs/utils/esr_netcommitment_raw_census.py --out {CENSUS_OUT}",
            "# MEASURED 2026-09-04 (the reading to reproduce):",
            f"#   raw json objects   : {MEASURED['raw_objects_total']} "
            f"(dated {MEASURED['raw_objects_dated']} / undated {MEASURED['raw_objects_undated']})",
            f"#   as_of vintages     : {MEASURED['raw_vintages']} "
            f"[{MEASURED['raw_first_vintage']} .. {MEASURED['raw_last_vintage']}]",
            f"#   objects carrying all five: {MEASURED['raw_objects_carrying_all_five']} of "
            f"{MEASURED['raw_objects_dated']} -- EVERY dated object in EVERY vintage",
            f"#   FIRST as_of carrying all five: {MEASURED['raw_first_vintage']}",
            "# THE CONSEQUENCE: there is no pre-publication vintage in raw. --as-of-min 20260813",
            "# would have skipped 20260712/17/23/24/30 and 20260806, whose raw DOES carry the",
            f"# fields, so the bound is {REBRONZE_BOUND} and it selects every dated key.",
            "# IF THE CENSUS DISAGREES with the numbers above, STOP: the bound in S3 and the",
            "# verdict in S4 are both derived from it and neither is safe to paste unchanged.",
        ]),
        ("S1  BUILD THE IMAGE: CLEAN WORKTREE + THE GITIGNORED OVERLAY -- never from this tree.", [
            "# WHY A WORKTREE: the shared tree carries other lanes' uncommitted work inside the",
            "# Dockerfile COPY set (src/, jobs/, configs/, sql/). scripts/build_push_worker.ps1 tars",
            "# $RepoRoot and stamps BUILD_GIT_COMMIT from `git rev-parse HEAD`, so a dirty build",
            "# produces an image whose IMAGE_MANIFEST asserts a commit it does not contain -- and S2",
            "# puts that image on the gate 26 scheduled families share.",
            "# DO NOT RUN build_push_worker.ps1 HERE.",
            "# WHY THE OVERLAY COPY IS MANDATORY: make_worker_context_tar.py takes the TRACKED bytes",
            "# from `git archive <ref>`, but it reads the gitignored configs/graphrag overlay from",
            "# the --repo WORKING TREE. `git worktree add` checks out TRACKED files ONLY, so a BARE",
            "# worktree makes that overlay EMPTY and the image bakes ZERO gitignored configs -- onto",
            "# the same gate whose jobs/audit/silver_rebuild_gate.py reads that subtree at runtime",
            "# (config_check, numbers.*). MEASURED in the main tree 2026-09-04: 141 files,",
            "# 4,751,532 bytes, 69 causal DAGs. The 2026-09-04 pink flip ran exactly this recipe.",
            "$main = 'C:\\Users\\User\\Desktop\\Leviathan'",
            f"$wt   = '{worktree}'",
            "$sha  = '<the lane commit>'",
            "git -C $main rev-parse HEAD",
            "git -C $main worktree add --detach $wt $sha",
            "# (1) LIST the overlay IN THE MAIN TREE -- it is the only tree that HAS these files:",
            "$skip = '^configs/graphrag/(evidence|eval|pilot)/|__pycache__|\\.pyc$|\\.log$|\\.tmp$'",
            "$overlay = git -C $main ls-files --others --ignored --exclude-standard -- "
            "configs/graphrag | Where-Object { $_ -notmatch $skip }",
            "$overlay.Count      # EXPECT 141 (measured 2026-09-04). A 0 here means STOP.",
            "if ($overlay.Count -lt 1) { throw 'overlay_files 0 -- STOP: step (1) listed "
            "nothing, so step (2) would copy nothing' }",
            "# (2) COPY every listed file into the worktree at the SAME relative path:",
            "foreach ($f in $overlay) { $dst = Join-Path $wt $f; $dir = Split-Path $dst -Parent; "
            "if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | "
            "Out-Null }; Copy-Item -LiteralPath (Join-Path $main $f) -Destination $dst -Force }",
            "# (3) ONLY NOW build the context tar:",
            f"python $wt/scripts/ops/make_worker_context_tar.py --repo $wt --ref HEAD --out {tar}",
            "# (4) THE GATE -- read the summary BEFORE the upload:",
            "#   overlay_files   MUST be > 0 (141 on 2026-09-04), and overlay_sha256 MUST print",
            "#                   (b4855da299efbf50... on 2026-09-04; it moves when a config moves).",
            "#   overlay_files: 0 IS A REFUSAL. It means step (2) did not run, the image would bake",
            "#   ZERO gitignored configs, and it MUST NOT be uploaded, built or deployed. Re-run the",
            "#   copy, re-run the tar, and only then continue -- never 'proceed and see'.",
            "#   THE TOOL ENFORCES THIS ITSELF since 2026-09-04 (V2-NEW-2): it exits non-zero",
            "#   on a zero overlay unless --allow-empty-overlay is passed. The throw above and",
            "#   this note are the SECOND and THIRD fences, not the only ones.",
            "#   tracked_members comes from `git archive`, so no co-tenant dirt can ride; the tool",
            "#   REFUSES on any modified/staged tracked file in the COPY set and on untracked files",
            "#   (--allow-untracked only records that the operator read the list).",
            f"aws s3 cp {tar} s3://{BUCKET}/build_contexts/{tar} --region {REGION}",
            "$body = @{ command = @('--context', "
            f"'s3://{BUCKET}/build_contexts/{tar}', '--dockerfile', "
            "'docker/leviathan_worker/Dockerfile', '--destination', "
            f"'{ECR_URL}:{tag}', '--build-arg', 'BUILD_GIT_COMMIT=<the lane commit sha>') " "}",
            "$body | ConvertTo-Json -Depth 5 | Set-Content -Encoding ascii kaniko_esr.json",
            f"aws batch submit-job --job-name kaniko-esr-netcommitment --job-queue {QUEUE} "
            f"--job-definition {JD_KANIKO} --region {REGION} "
            "--container-overrides file://kaniko_esr.json --query jobId --output text",
            "# ~3 min in-region. READ THE PUSHED DIGEST OFF THE KANIKO LOG -- never infer it:",
            f"aws ecr describe-images --repository-name {WORKER_REPO} --image-ids imageTag={tag} "
            f"--region {REGION} --query 'imageDetails[0].imageDigest' --output text",
            "git -C $main worktree remove --force $wt",
            "# --force because the copied overlay files are untracked in the worktree; that is the",
            "# recipe working, not a surprise.",
        ]),
        ("S2  MOVE FOUR JOBDEFS -- copy the live revision verbatim; the envelope must survive.", [
            "# MEASURED LIVE 2026-09-04 (revision, vCPU, MiB). The repin helper asserts these",
            "# BEFORE copying, so a jobdef someone else moved stops the rollout instead of riding.",
        ] + [f"#   {name:<38s} rev {rev:<3d} {vcpu} vCPU / {mem} MiB"
             for name, rev, vcpu, mem in JOBDEFS] + [
            "# The 12,288 MiB on the two silver jobdefs is the 2026-09-03 post-OOM bump and this",
            "# lane makes the frame 13.1% wider. A re-registration that re-authors the descriptor",
            "# from constants reverts it silently:",
            "#   DO NOT USE jobs/submit/submit_batch_b2s_esr.py for S4 or S7 -- it hardcodes",
            "#   MEMORY 4096 for leviathan-dev-esr-bronze-to-silver and a stale image digest whose",
            "#   own reuse test will fail once this repin lands, registering a 4 GB revision on the",
            "#   PRE-LANE image. That is an immediate OOM and, after S5, the whole-family promote",
            "#   failure the reconcile flag exists to prevent.",
            "$D = '<the digest S1 printed>'",
        ] + [
            f"python scripts/ops/repin_jobdef_digest.py --job-definition {name} "
            f"--image-digest $D --expect-vcpu {vcpu} --expect-memory {mem}"
            for name, _, vcpu, mem in JOBDEFS
        ] + [
            "# The four lines above are DRY RUNS: each prints the live revision, the one changed",
            "# field, and the preserved envelope. Re-run each with --apply once the diff reads",
            "# exactly 'fields changed : 1 (containerProperties.image)'.",
            "# VERIFY BY REVISION NUMBER AND A FRESH BOOT LOG, never by a terraform plan (a",
            "# digest-pinned jobdef makes a push a NO-OP and a clean plan proves nothing):",
        ] + [
            f"aws batch describe-job-definitions --job-definition-name {name} --status ACTIVE "
            f"--region {REGION} --query "
            "'jobDefinitions[-1].[revision,containerProperties.image,"
            "containerProperties.resourceRequirements]' --output text"
            for name, _, _, _ in JOBDEFS
        ] + [
            "# NOTE (C-m4): jobs/glue/raw_to_bronze_usda_esr.py shares the transform but ships its",
            "# own bootstrapped wheel from s3://.../glue-libs/. It has no aws_glue_trigger, is",
            "# manual-only, and stays STALE until that wheel is rebuilt. Do not use it for S3.",
            "# NOTE (NEW-2): that same Glue writer also PREDATED the vintage law -- its backfill",
            "# mode paired every undated raw key with --ingest_date (the run's own date) and wrote",
            "# into the SAME bronze prefix, which is where 8,474 of the 8,920 bronze objects came",
            "# from. Its backfill mode NOW REFUSES BY NAME and points at jobs/batch/esr_task.py",
            "# --include-backfill, so a manual fire cannot re-open the defect while its wheel is",
            "# stale. Its WEEKLY mode was always law-abiding: the as_of is the raw key's own",
            "# segment. The third ESR writer, jobs/ingest/backfill_silver_usda_esr.py (silver_esr,",
            "# residual R3), now REQUIRES an explicit --as-of-date -- its old default stamped",
            "# today's date onto every partition it wrote.",
        ]),
        ("S3  TARGETED RE-BRONZE -- bounded by the MEASURED vintage, backfill keys excluded.", [
            "$body = @{ command = @('jobs/batch/esr_task.py', '--force-overwrite', "
            f"'--as-of-min', '{REBRONZE_BOUND}') " "}",
            "$body | ConvertTo-Json -Depth 5 | Set-Content -Encoding ascii rebronze_esr.json",
            f"aws batch submit-job --job-name esr-rebronze-netcommitment --job-queue {QUEUE} "
            f"--job-definition leviathan-dev-usda-esr-bronze --region {REGION} "
            "--container-overrides file://rebronze_esr.json --query jobId --output text",
            "# READ THREE LINES:",
            f"#   ESR task  bucket=...  raw_keys={MEASURED['raw_objects_total']}  force=True  "
            "include_backfill=False  backfill_as_of=None  as_of_min=" + REBRONZE_BOUND,
            f"#   skipped {MEASURED['raw_objects_undated']} undated raw key(s) ...",
            f"#   as-of-min={REBRONZE_BOUND}  selected={MEASURED['raw_objects_dated']} of "
            f"{MEASURED['raw_objects_dated']} raw key(s)  (dropped=0, of which undated=0)",
            f"#   Done  written={MEASURED['raw_objects_dated']}  skipped=0  refused=0  errors=0",
            "# EXPECTED SCOPE, measured not guessed: 446 dated raw objects, all 12 vintages, all",
            "# carrying the five. written MUST be > 0; written=0 means the filter matched nothing",
            "# and every measurement below is vacuous.",
            "# WHAT THE RUN WILL NOT DO, and this is the C-F1 fix: it will not touch the 1,455",
            "# undated backfill objects. Before the fix the same command admitted all of them,",
            "# stamped them with the run date, and minted a fabricated as_of=<today> silver",
            "# vintage that reads 0.0 on all five -- tripping S4's own STOP on a self-inflicted",
            "# artifact. --force-overwrite now also REFUSES without --as-of-min (exit 2).",
        ]),
        ("S4  SHADOW RUN -- nothing canonical, catalog untouched; then read the manifest.", [
            "$body = @{ command = @('jobs/batch/bronze_to_silver_esr_task.py', '--vintage-mode', "
            "'all', '--publish-mode', 'shadow') " "}",
            "$body | ConvertTo-Json -Depth 5 | Set-Content -Encoding ascii shadow_esr.json",
            f"aws batch submit-job --job-name esr-silver-shadow-netcommitment --job-queue {QUEUE} "
            "--job-definition leviathan-dev-esr-bronze-to-silver "
            f"--region {REGION} --container-overrides file://shadow_esr.json "
            "--query jobId --output text",
            "# stderr lines to read:",
            "#   vintage-mode=all -> selected <N> bronze files",
            "#   Silver combined: <rows> rows across <M> market_years / <V> as_of vintages",
            "#   Staged <K> compact object(s) for vintage-mode=all",
            "#   ESR bronze->silver complete. mode=shadow vintage=all state=PUBLISHED objects=K",
            f"# MEMORY (C-M2): this shadow does the IDENTICAL concat and is the free rehearsal for",
            f"# S7. Expect ~{MEASURED['all_vintage_rows_est']:,} rows x 18 columns, "
            f"{MEASURED['silver_bytes_per_row_widened']} B/row deep",
            f"# ({MEASURED['silver_bytes_per_row_head']} before the widen, "
            f"+{MEASURED['silver_bytes_per_row_delta']} B/row = five float64), a two-copy concat",
            f"# peak of ~{MEASURED['concat_peak_gib_widened']} GiB against the "
            f"{MEASURED['envelope_gib']} GiB envelope ({MEASURED['concat_peak_gib_head']} GiB",
            "# before). Read the job's peak memory off the ECS task metrics BEFORE S7. Exit 137",
            "# is the OOM signature and it means the S2 repin did not preserve 12,288 MiB.",
            f"aws s3 cp {MANIFEST_URI} - --region {REGION} > manifest.json",
            "python scripts/ops/esr_netcommitment_runbook.py --step VERDICT",
            "# THE VERDICT, RESTATED SO IT CAN FAIL (C-M3). The old sentence ('0.0 on every as_of",
            "# < 20260813') was guaranteed by the re-bronze scope, not by the source. The measured",
            "# raw census says every dated vintage carries the five, so the honest reading is:",
            "#   EVERY (commodity, as_of) object whose BRONZE was re-written in S3 must read",
            "#   NON-ZERO on all five, for all 12 vintages -- there is no vintage the source did",
            "#   not publish, so a 0.0 anywhere is a PIPELINE finding, never a source finding.",
            "#   A 0.0 is expected ONLY on the fabricated backfill-derived partitions S3 did not",
            "#   touch (8,474 bronze objects; see RESIDUALS). Write any exception down PER",
            "#   COMMODITY -- frequency floors deny the tail, and one narrating slug keeps a column.",
            "#   NO-REGRESSION: weekly_exports_1000mt unchanged vs the prior run's manifest.",
            "# ValidationHooks(min_nonnull_frac=0.0) means an all-null new column can never block",
            "# the shadow publish, so this measurement cannot fail closed on itself.",
        ]),
        ("S5  THE CATALOG WIDEN -- ONE commit: ALTER, R0 refresh, contract flip, regenerate.", [
            "# PRECONDITION: S2 (b) and (c) MUST already be live. publish_one builds every",
            "# partition's desired StorageDescriptor by copying the TABLE SD, so the moment the",
            "# table goes 12 -> 17 columns EVERY registered partition diffs; without",
            "# reconcile_schema_widen=True on the running image, publish_one fails closed and the",
            "# canonical run exits 1 FOR THE WHOLE FAMILY.",
            "# (1) apply the silver_esr_compact half ONLY of",
            "#     sql/athena/migrations/silver/silver_esr_f030_additive.sql, under lease:",
            f"#     ALTER TABLE {DB}.{TABLE} ADD COLUMNS (",
        ] + [f"#         {c:<34s} double{',' if c != FIVE_SILVER[-1] else ''}"
             for c in FIVE_SILVER] + [
            "#     );",
            "#     DO NOT apply the silver_esr half -- it is a written refusal (no writer on any",
            "#     schedule, 370 registered partitions with nothing to self-heal them, measured",
            "#     all_nan on its census).",
            "# (2) refresh reports/silver_readiness/20260712_p65impl/tables/silver_esr_compact.json",
            "#     from the POST-ALTER live table (glue.nonpartition_columns + "
            "fingerprint.catalog_hash_sha256).",
            "# (3) in scripts/silver/gen_registry_from_baseline.py, CURATION_OVERRIDES"
            "['silver_esr_compact']:",
            "#     rename \"additive_columns_hidden\" to \"additive_columns\" and add",
            "#     \"additive_columns_registered\": True,",
            "# (4) regenerate and prove it in the SAME commit (PowerShell 5.1 chains with ';' "
            "only; the pipeline-chain operator is a 5.1 parser error, so run one line at a time):",
            "python scripts/silver/gen_registry_from_baseline.py",
            "python scripts/silver/gen_registry_from_baseline.py --check",
            "python scripts/silver/generate_ddls_from_registry.py --write",
            "python -m pytest tests/unit/silver/test_ddl_generation.py "
            "tests/unit/silver/test_esr_contract_rebaseline.py -q",
            "# EXPECT after the flip: silver_esr_compact.sql goes 12 -> 17 columns, the five LAST",
            "# as double. test_esr_compact_ddl_renders_the_five_last_once_registered already passes",
            "# today (it simulates the flip on a deepcopy) and keeps passing; the two tests that",
            "# must be flipped to their post-ALTER form carry the instruction in their docstrings.",
        ]),
        ("S6  GATE -- Branch A, on the NEW gate image (it reads the image-baked contract).", [
            "$body = @{ command = @('-m', 'jobs.audit.silver_rebuild_gate', '--tables', "
            "'silver_esr,silver_esr_compact', '--asof', '<YYYY-MM-DD>', '--baseline-uri', "
            f"'{BASELINE_URI}') " "}",
            "$body | ConvertTo-Json -Depth 5 | Set-Content -Encoding ascii gate_esr.json",
            f"aws batch submit-job --job-name esr-gate-netcommitment --job-queue {QUEUE} "
            f"--job-definition leviathan-dev-silver-gate --region {REGION} "
            "--container-overrides file://gate_esr.json --query jobId --output text",
            "# Branch A stages to read:",
            "#   pg_reload:      mirror reloaded <N> rows for silver_esr",
            "#   parity:         clean",
            "#   value_census:   {'ok': True, 'gate_rows': 0, ...}   <- the five are UNGOVERNED, so",
            "#                   the census still measures only the three incumbents.",
            "#   contract_check: vocabulary consistent",
            "#   feature_probe:  <n> file(s), <rows> rows, contract columns present",
            "# exit 0 = PASS. exit 1 is a REFUSAL ABOUT DATA and is never retried to green.",
            "# C-m1: this reload runs BEFORE S7, so the five WILL read all-NULL in pg here. That is",
            "# expected, not a finding. The mirror is only meaningful after the S8 reload.",
        ]),
        ("S7  CANONICAL PROMOTE -- and read partition_actions AGAINST A DENOMINATOR.", [
            "$body = @{ command = @('jobs/batch/bronze_to_silver_esr_task.py', '--vintage-mode', "
            "'all', '--publish-mode', 'canonical'); environment = @(" +
            ", ".join("@{ name = '%s'; value = '%s' }" % (e["name"], e["value"]) for e in KMS_ENV)
            + ") }",
            "$body | ConvertTo-Json -Depth 5 | Set-Content -Encoding ascii promote_esr.json",
            f"aws batch submit-job --job-name esr-promote-netcommitment --job-queue {QUEUE} "
            "--job-definition leviathan-dev-silver-publisher-runner "
            f"--region {REGION} --container-overrides file://promote_esr.json "
            "--query jobId --output text",
            "#   ESR bronze->silver complete. mode=canonical vintage=all state=PUBLISHED "
            "objects=K partition_actions={'repaired': 1}",
            "# C-m6 -- READ THE COUNT, NOT THE OUTCOME SET. PartitionPublisher only walks the",
            "# partitions this run STAGES, and those come from bronze. A registered partition with",
            "# no surviving bronze source is never repaired and keeps its 12-column descriptor, so",
            "# Athena will not expose the five there even after the table widens. Compare the",
            "# repaired+created count against the table's registered-partition count:",
            f"aws glue get-partitions --database-name {DB} --table-name {TABLE} "
            f"--region {REGION} --query 'length(Partitions)' --output text",
            "# Any shortfall is an ORPHAN partition to reconcile deliberately, named per partition.",
            "# EXPECT 'repaired' on every pre-existing partition on this FIRST post-ALTER promote,",
            "# 'created' on the new ones, and 'existing' everywhere on a SECOND promote. Anything",
            "# 'failed' means the widen was not pure -- re-read the migration artifact's",
            "# PRECONDITION block before retrying.",
        ]),
        ("S8  RELOAD THE MIRROR AFTER THE PROMOTE, then verify from the serving side.", [
            "# C-m1: the S6 gate reloaded pg BEFORE the canonical objects existed, so the five read",
            "# all-NULL there. Reload again now -- this is the first reload that can show data.",
            f"aws batch submit-job --job-name esr-gate-netcommitment-post --job-queue {QUEUE} "
            f"--job-definition leviathan-dev-silver-gate --region {REGION} "
            "--container-overrides file://gate_esr.json --query jobId --output text",
            "# Athena, partition-filtered, on a vintage S3 re-bronzed:",
            f"#   SELECT {', '.join(FIVE_SILVER[:3])}",
            f"#   FROM {DB}.{TABLE}",
            "#   WHERE commodity='corn_cbot' AND as_of_date='20260903' LIMIT 10;   -- NON-NULL",
            "#   ...same with as_of_date='20260712'                                -- NON-NULL too:",
            "#   every dated vintage's raw carries the five, so there is no NULL-before boundary.",
            "# NOTE: until the numbers card declares the five as metrics, load_pg_numbers",
            "# ._numeric_cols does not see them, so _pg_type mirrors them as text COLLATE \"C\".",
            "# Harmless while nothing reads them; the card flip and a reload go in the SAME window.",
        ]),
        ("S9  HAND THE CHAIN BACK -- and the residuals this lane names but does not close.", [
            "# NOTHING TO DO for the schedule. esr_weekly (cron(0 14 ? * THU *), next fire",
            "# 2026-09-10 14:00Z) is UNCHANGED -- no scheduler edit, no dag_schedules tfvars change.",
            "# S3-S7 are manual executions of the same thin-contract chain the scheduler drives.",
            "# WHAT THE NEXT SCHEDULED FIRE DOES DIFFERENTLY, and it is a reduction:",
            f"#   before: it admitted all {MEASURED['raw_objects_undated']} undated raw keys and",
            "#           wrote them to bronze at as_of=<the run date>, minting a whole fabricated",
            "#           point-in-time vintage every week (measured: 1,414 such objects at",
            "#           as_of=20260904 alone).",
            f"#   after : it processes only the {MEASURED['raw_objects_dated']}-and-growing dated",
            "#           keys and logs 'skipped 1,455 undated raw key(s)'.",
            "# RESIDUALS, named not closed:",
            f"#   R1 the {MEASURED['bronze_fabricated_vintages']} pre-existing fabricated bronze",
            f"#      objects ({MEASURED['bronze_from_dated_raw']} of {MEASURED['bronze_objects']}",
            "#      bronze objects derive from a dated raw key; the rest are backfill payloads",
            "#      stamped with a run date). They keep the 12-column shape and will read NULL on",
            "#      the five. Cleaning them is a deliberate vintage-repair pass with its own",
            "#      review, not a side effect of this lane. They are also ~95% of the 13.9M-row",
            "#      all-vintage concat, i.e. most of the memory pressure in S4/S7.",
            "#      WHAT STOPS THE GROWTH is every BRONZE writer in the estate, not just the",
            "#      Batch one -- and BRONZE growth is the only growth this residual counts:",
            "#      esr_task.py resolves the vintage (raw key / operator / sidecar / refuse);",
            "#      jobs/glue/raw_to_bronze_usda_esr.py REFUSES backfill mode by name;",
            "#      jobs/ingest/backfill_bronze_usda_esr.py, its LOCAL TWIN, REFUSES the undated",
            "#      re-bronze by name (it needed no flags to fire and stamped today by default);",
            "#      and dags/airflow/esr_weekly_ingest_dag.py writes bronze inline at the raw",
            "#      key's OWN as_of, which was always law-abiding.",
            "#      THE LAW HOLDS IN ALL FOUR ESR writers -- the three bronze ones above plus",
            "#      jobs/ingest/backfill_silver_usda_esr.py, which writes SILVER and therefore",
            "#      cannot add a bronze object at all: it belongs under R3, not here.",
            "#   R2 the numbers-card exposure (configs/graphrag/numbers/tables.yaml#silver_esr).",
            "#      Adding a metric AUTOMATICALLY makes it a value_column on the next generator",
            "#      run, so the card flip IS the governance promotion; it must not land before the",
            "#      value census reads >= 0.5 per commodity.",
            "#   R3 silver_esr full-surface alignment (the written refusal), if ever wanted. If it",
            "#      is ever wanted, jobs/ingest/backfill_silver_usda_esr.py is the writer -- ONCE",
            "#      PER BRONZE VINTAGE, and it REQUIRES an explicit --as-of-date (it refuses",
            "#      without one). It is charged HERE and not under R1 because it writes SILVER:",
            "#      it can never add one of R1's bronze objects.",
            "#   R4 the incumbent four *_1000mt columns are still float32 under a Glue `float`",
            "#      catalog (SILVER-F031). Two widths now live in one table.",
        ]),
    ]


def rollback() -> int:
    print("=" * 100)
    print("ROLLBACK -- layered, and the layer that matters is S5.")
    print("-" * 100)
    for line in [
        "BEFORE S5 (no ALTER applied): re-pin the four jobdefs to their PREVIOUS digests and stop.",
        "  Each previous digest is printed by the S2 dry run as 'live image'. Record them BEFORE",
        "  applying, and roll back with the same helper so the envelope is copied on the way back:",
        "  python scripts/ops/repin_jobdef_digest.py --job-definition <name> --image-digest "
        "<the previous digest> --expect-vcpu <v> --expect-memory <m> --apply",
        "",
        "AFTER S5 (the ALTER applied): ROLL FORWARD, never back. The old image lacks",
        "  reconcile_schema_widen and would meet a widened table SD -- which is exactly the",
        "  whole-family promote failure the flag exists to prevent. The ALTER itself is additive",
        "  (five all-NULL columns on the compact table) and costs nothing to leave in place.",
        "",
        "THE ONE THING THAT IS NOT ROLLED BACK: the bronze objects S3 rewrote. They are the same",
        "  vintages with five more columns; the old silver reads them by name and ignores the",
        "  extras. No rollback is needed and none is offered.",
    ]:
        print("  " + line)
    return 0


def verdict() -> int:
    """Read a downloaded shadow manifest against the raw census. AWS-free: both are local files."""
    manifest_path = Path("manifest.json")
    census_path = _REPO / CENSUS_OUT
    if not manifest_path.exists():
        print("no manifest.json here -- run the `aws s3 cp` line in S4 first")
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    census = json.loads(census_path.read_text(encoding="utf-8")) if census_path.exists() else {}
    first = census.get("first_as_of_with_all_five")
    metrics = manifest.get("row_key_null_metrics") or {}
    print(f"raw census first as_of carrying all five : {first}")
    print(f"staged objects with null metrics         : {len(metrics)}")
    print("commodity   as_of      " + "  ".join(c[:22] for c in FIVE_SILVER))
    bad = 0
    for key in sorted(metrics):
        row = metrics[key]
        commodity = key.split("commodity=")[-1].split("/")[0] if "commodity=" in key else "?"
        as_of = key.split("as_of=")[-1].split("/")[0] if "as_of=" in key else "?"
        values = [row.get(c) for c in FIVE_SILVER]
        flag = ""
        if first and as_of >= first and all((v or 0.0) == 0.0 for v in values):
            flag = "  <- ZERO on a vintage whose RAW carries the five: a PIPELINE finding"
            bad += 1
        print(f"{commodity:<11s} {as_of:<9s} " +
              "  ".join(f"{(v if v is not None else -1):>22.3f}" for v in values) + flag)
    print(f"\nobjects reading zero on a published vintage: {bad}")
    print("A zero here is never a source finding -- the census says every dated vintage publishes.")
    return 0


def check() -> int:
    """AWS-FREE preflight: the local gates, run for real."""
    rc = 0
    print("=" * 100)
    print("CHECK -- local only, nothing is mutated")
    print("-" * 100)
    for label, cmd in (
        ("registry byte-identity",
         [sys.executable, "scripts/silver/gen_registry_from_baseline.py", "--check"]),
        ("lane suites",
         [sys.executable, "-m", "pytest",
          "tests/unit/silver/test_esr_net_commitment_columns.py",
          "tests/unit/silver/test_esr_contract_rebaseline.py",
          "tests/unit/silver/test_esr_compact_producer.py",
          "tests/unit/silver/test_ddl_generation.py",
          "tests/unit/silver/test_silver_registry_gen.py",
          "tests/unit/silver/test_value_census.py",
          "tests/unit/test_batch_esr_task.py",
          "tests/unit/test_transforms_esr_raw.py",
          "-q"]),
    ):
        out = subprocess.run(cmd, cwd=str(_REPO), capture_output=True, text=True)
        tail = [ln for ln in out.stdout.strip().splitlines() if ln.strip()][-1:] or ["(no output)"]
        print(f"  {label:<24s} rc={out.returncode}  {tail[0][:88]}")
        rc = rc or out.returncode
    # THE IMAGE RECIPE, greped out of S1 itself. A runbook that lost the overlay copy or the
    # overlay_files gate would still print a plausible-looking build, and the image it produced
    # would carry ZERO gitignored configs onto a gate 26 families share -- so CHECK reads the
    # step's own text rather than trusting that it was written once.
    missing = s1_overlay_missing()
    print(f"  {'S1 image recipe':<24s} rc={1 if missing else 0}  "
          + ("MISSING CLAUSE(S): " + " | ".join(missing) if missing else
             f"clean worktree + the {OVERLAY_FILES_MEASURED}-file configs/graphrag overlay copy "
             f"+ the overlay_files>0 gate are all present in S1"))
    rc = rc or (1 if missing else 0)
    print(f"  {'dirty COPY set?':<24s} "
          f"(S1 builds from a clean worktree; make_worker_context_tar.py is the oracle)")
    return rc


def print_steps(run_id: str, only: str | None = None) -> None:
    for title, cmds in steps(run_id):
        stem = title.split()[0]
        if only and stem != only:
            continue
        print("=" * 100)
        print(title)
        print("-" * 100)
        for cmd in cmds:
            print("  " + cmd)
        print()


def main(argv=None) -> int:
    stems = [t.split()[0] for t, _ in steps("x")]
    ap = argparse.ArgumentParser(
        description="SILVER-F030 BF-W2 ESR net-commitment runbook -- dry-run by construction")
    ap.add_argument("--step", default="PRINT",
                    choices=["PRINT", "CHECK", "ROLLBACK", "VERDICT"] + stems)
    ap.add_argument("--run-id", default=f"{datetime.now(tz=timezone.utc):%Y%m%dT%H%M}")
    args = ap.parse_args(argv)
    if args.step == "CHECK":
        return check()
    if args.step == "ROLLBACK":
        return rollback()
    if args.step == "VERDICT":
        return verdict()
    print_steps(args.run_id, None if args.step == "PRINT" else args.step)
    return 0


if __name__ == "__main__":
    sys.exit(main())
