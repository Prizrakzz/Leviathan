#!/usr/bin/env python
"""PINK SHEET VINTAGES lanes (a)+(b) RUNBOOK -- prints the exact command for every step, and RUNS
the checks a human cannot eyeball. IT NEVER MUTATES ANYTHING.

    python scripts/ops/pink_vintages_runbook.py                  # print every step's commands
    python scripts/ops/pink_vintages_runbook.py --step D3        # print one step
    python scripts/ops/pink_vintages_runbook.py --step CHECK     # run the AWS-FREE preflight
    python scripts/ops/pink_vintages_runbook.py --step ROLLBACK  # print the layered rollback

DRY RUN BY CONSTRUCTION. There is no ``--run`` and no code path that submits a Batch job, writes
S3, registers a job definition or applies terraform: every mutating command is PRINTED for the
operator to paste. ``--step CHECK`` reads local files only. That is deliberate and it is the
difference between a runbook and a deploy script.

THE DIGEST-PINNED-JOBDEF LAW -- WHY D2 EXISTS AND WHY IT IS BEFORE D3
---------------------------------------------------------------------
Three files this wave adds exist in NO image:

    jobs/batch/pink_sheet_vintages_task.py
    jobs/batch/pink_sheet_archive_task.py
    jobs/ingest/backfill_pink_sheet_vintages.py

and ``infra/terraform/modules/batch/main.tf`` pins ``leviathan-dev-world-bank-pink-sheet-bronze``
BY DIGEST (``local.pink_sheet_image`` / ``var.pink_sheet_image_digest``, which refuses a TAG by
validation because a tag is exactly the mutability the pin removes).  So a submit before the build
is either a no-op against a stale image or a missing-file failure, and any "$0, ~20 min" costing
that skips the build is wrong.  The order is:

    kaniko context tar (git archive) -> S3 -> IN-REGION kaniko build -> jobdef re-register
      -> terraform digest pin bump -> check_ecr_pinned_digests -> targeted apply
      -> submit -> VERIFY the revision and the counts against a prediction.

``shadow_canonical`` IS NOT A CLI CHOICE
----------------------------------------
``pink_sheet_vintages_task.py`` declares ``--publish-mode {dry-run,shadow,canonical}``.
``shadow_canonical`` is a DAG-LEVEL descriptor: ``gen_dag_schedules_tfvars`` expands it into a
``shadow`` silver task PLUS a separate ``canonical`` promote task on
``leviathan-dev-silver-publisher-runner`` carrying BOTH KMS env entries.  D5 runs the canonical leg
in exactly that shape; passing ``--publish-mode shadow_canonical`` to the task exits 2.

THE GATE NEEDS ``GRAPHRAG_NUMBERS_BACKEND=pg``
-----------------------------------------------
``silver_pink_sheet`` is a BRANCH-A table and Branch A asserts that env
(``silver_rebuild_gate.py`` -- 'Branch-A tables require GRAPHRAG_NUMBERS_BACKEND=pg').  A gate run
over the pair without it crashes -- the same gap that crashed the 2026-08 pink-sheet gate r1.  The
new table itself is BRANCH B (feature_layer consumers, absent from PG_MIRROR_TABLES), whose three
stages are feature_probe / value_census / config_check: no census stage, so NO rolling-census
baseline is needed and ``advance_rolling_census.py`` is invoked NOWHERE in this runbook.

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
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

REGION = "us-east-1"
BUCKET = "leviathan-dev-shahem-001"
ACCOUNT = "668891723125"
DB = "leviathan_dev"

TABLE = "silver_pink_sheet_vintages"
SIBLING = "silver_pink_sheet"

QUEUE = "leviathan-dev-queue-ondemand"
JD_FLAT_SILVER = "leviathan-dev-b3-flat-silver"
JD_BRONZE = "leviathan-dev-world-bank-pink-sheet-bronze"
JD_GATE = "leviathan-dev-silver-gate"
JD_PUBLISHER = "leviathan-dev-silver-publisher-runner"
JD_KANIKO = "leviathan-dev-kaniko-build"

WORKER_REPO = "leviathan-dev-leviathan-worker"
ECR_URL = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{WORKER_REPO}"

SERVED_SILVER_KEY = "silver/pink_sheet/part-000.parquet"
VINTAGE_SILVER_KEY = "silver/pink_sheet_vintages/part-000.parquet"
RAW_PREFIX = "raw/production/source=world_bank_pink_sheet/"
BRONZE_PREFIX = "bronze/production/source=world_bank_pink_sheet/"
ARCHIVE_RAW_PREFIX = "raw/production/source=world_bank_pink_sheet_archive/"
ARCHIVE_BRONZE_PREFIX = "bronze/production/source=world_bank_pink_sheet_archive/"
BASELINE = f"s3://{BUCKET}/cascade_census/rolling/pink_sheet_monthly/census.json"

KMS_ENV = [{"name": "LEVIATHAN_APPROVAL_MODE", "value": "kms"},
           {"name": "LEVIATHAN_KMS_KEY_ID", "value": "alias/leviathan-dev-publish-signer"}]

# The four already-banked raw releases, and the row count each must derive.
BANKED = {"2026M05": 796, "2026M07": 798, "2026M08": 799, "2026M09": 800}
# 2026M06 is a PERMANENT HOLE -- the schedule's own miss, not a capture this runbook can recover.
KNOWN_HOLE = "2026M06"
PHASE0_EXPECTED = {"2025M01": 780, "2026M01": 792}


def _submit(name: str, jobdef: str, command: list[str], env: list[dict] | None = None) -> str:
    overrides: dict = {"command": command}
    if env:
        overrides["environment"] = [{"name": e["name"], "value": e["value"]} for e in env]
    return (f"aws batch submit-job --job-name {name} --job-queue {QUEUE} "
            f"--job-definition {jobdef} "
            f"--container-overrides '{json.dumps(overrides)}' --query jobId --output text")


def _head(key: str) -> str:
    return (f"aws s3api head-object --bucket {BUCKET} --key {key} "
            f"--query '[ETag,ContentLength,LastModified]' --output json")


# THE ESTATE'S REVISION-VERIFY IDIOM, spelled once.
# `jobDefinitions[-1]` is NOT the highest revision -- the API's order is not a contract -- and
# `revisionentry` is not a field at all, so a query naming it prints a reassuring `null` in the one
# step whose entire purpose is proving the revision moved. The max is SELECTED, explicitly.
_JD_MAX_REV = "reverse(sort_by(jobDefinitions,&revision))[0]"


def _verify_jobdef(name: str) -> str:
    return (f"aws batch describe-job-definitions --job-definition-name {name} --status ACTIVE "
            f"--query '{_JD_MAX_REV}.[revision,containerProperties.image]' --output json")


# The helper D2 writes out. It is PRINTED for the operator to paste, never executed here: this
# module registers nothing (see the CHECK's own dry-run assertion).
_REGISTER_HELPER = '''\
"""Re-register ONE Batch job definition on a NEW image digest, changing nothing else.

    python register_jobdef_on_digest.py <job-definition-name> <repo>@sha256:<digest>

Reads the highest ACTIVE revision, copies it verbatim, replaces ONLY containerProperties.image,
registers, and then RE-READS to verify the revision moved and the image is byte-identical to the
one asked for. Exits non-zero on any of those, because a jobdef step that prints a green line
without checking is the 2026-08-27 rev-110 vacuous gate.
"""
import json
import subprocess
import sys

Q = "reverse(sort_by(jobDefinitions,&revision))[0]"


def read(name):
    out = subprocess.check_output(
        ["aws", "batch", "describe-job-definitions", "--job-definition-name", name,
         "--status", "ACTIVE", "--query", Q, "--output", "json"])
    return json.loads(out)


name, image = sys.argv[1], sys.argv[2]
if "@sha256:" not in image:
    raise SystemExit("refusing a TAG: a digest-pinned jobdef must be re-registered by DIGEST")
cur = read(name)
print("OLD", cur["revision"], cur["containerProperties"]["image"])

# ONLY the image moves. Every other key is carried across verbatim; a key this list does not know
# about is a REFUSAL, not a silent drop -- dropping a retryStrategy or a timeout would change the
# job's behaviour under cover of an image bump.
CARRY = ("type", "parameters", "containerProperties", "nodeProperties", "retryStrategy",
         "timeout", "propagateTags", "platformCapabilities", "schedulingPriority",
         "tags", "eksProperties", "ecsProperties", "consumableResourceProperties")
SKIP = ("jobDefinitionName", "jobDefinitionArn", "revision", "status",
        "containerOrchestrationType")
unknown = [k for k in cur if k not in CARRY and k not in SKIP]
if unknown:
    raise SystemExit("unhandled job-definition key(s) %r -- add them to CARRY deliberately "
                     "rather than dropping them" % unknown)

body = {k: cur[k] for k in CARRY if k in cur}
body["jobDefinitionName"] = name
body["containerProperties"] = dict(cur["containerProperties"], image=image)
new = json.loads(subprocess.check_output(
    ["aws", "batch", "register-job-definition", "--cli-input-json", json.dumps(body)]))
print("NEW", new["revision"], name)

chk = read(name)
assert chk["revision"] == new["revision"], (chk["revision"], new["revision"])
assert chk["revision"] > cur["revision"], "the revision did NOT move"
assert chk["containerProperties"]["image"] == image, chk["containerProperties"]["image"]
print("VERIFIED", name, "rev", chk["revision"], chk["containerProperties"]["image"])
'''


def steps(run_id: str) -> list[tuple[str, list[str]]]:
    tar = f"pink_vintages_context_{run_id}.tar.gz"
    tag = f"{run_id}-pink-vintages"
    return [
        ("D0  LOCAL PREFLIGHT -- $0, NO AWS. Everything here is a file read; nothing may be "
         "submitted until it is all green. `--step CHECK` RUNS these.", [
            "python -m pytest tests/unit/test_pink_sheet_release.py "
            "tests/unit/test_pink_sheet_vintages.py tests/unit/test_pink_sheet_breaks.py "
            "tests/unit/test_pink_sheet_prefix_fence.py "
            "tests/unit/test_fetch_pink_sheet_order.py tests/unit/test_wayback_pink_sheet.py "
            "tests/unit/test_numbers_query.py tests/unit/silver/test_silver_registry_gen.py "
            "tests/unit/silver/test_ddl_generation.py -q",
            "python -m leviathan.graphrag.config_check      "
            "# includes the NEW vintage_grain clause",
            "python scripts/silver/gen_registry_from_baseline.py --check   "
            "# must print 'registry check OK'",
            "python scripts/silver/generate_ddls_from_registry.py           "
            "# must print no DDL drift",
            "python scripts/ops/pink_vintages_runbook.py --step CHECK",
            "# THE ORDER IS LOAD-BEARING: the F010 contract "
            "configs/silver/tables/silver_pink_sheet_vintages.yaml must be COMMITTED before any",
            "# gate run -- select_branch returns BRANCH_UNKNOWN for an unregistered table and the "
            "gate reports it RED BY CONSTRUCTION, which is not a bug to debug.",
        ]),

        ("D1  G-A0 CONTENT-KEY AUDIT on the banked raw objects -- $0, READ-ONLY S3, in-VPC. "
         "Re-arms on every future object; PASS 3/3 is already banked for M05/M07/M08.", [
            f"aws s3 ls s3://{BUCKET}/{RAW_PREFIX} --recursive",
            f"aws s3 ls s3://{BUCKET}/{BRONZE_PREFIX} --recursive",
            "# EXPECT release=2026M09/ present in BOTH, and the three prior raw objects "
            "byte-untouched.",
            f"# EXPECT the derived month of every object to EQUAL its release= segment: "
            f"{json.dumps(BANKED)}",
            f"# {KNOWN_HOLE} is a PERMANENT HOLE (the schedule's own miss) -- it is DECLARED, not "
            f"recovered here.",
            "# DO NOT run jobs/batch/pink_sheet_silver_task.py out of band: the served table "
            "advances at the scheduled fire or through a normal shadow->gate->promote chain.",
            _submit("pink-content-key-audit", JD_FLAT_SILVER, [
                "-c",
                "import boto3,json;"
                "from leviathan.common.pink_sheet_release import derived_release_ym,"
                "expected_month_count,monthly_rows,is_full_restatement;"
                "s3=boto3.client('s3');"
                f"ks=[o['Key'] for p in s3.get_paginator('list_objects_v2').paginate("
                f"Bucket='{BUCKET}',Prefix='{RAW_PREFIX}') for o in p.get('Contents',[]) "
                "if o['Key'].endswith('.xlsx')];"
                "out=[];\n"
                "for k in ks:\n"
                f"    b=s3.get_object(Bucket='{BUCKET}',Key=k)['Body'].read();"
                "    R=derived_release_ym(b); m=monthly_rows(b);"
                "    out.append({'key':k,'derived':R,'n':len(m),"
                "'expected':expected_month_count(R),'full':is_full_restatement(m)})\n"
                "print(json.dumps(out,indent=1))"]),
            "# A MISMATCH REFUSES THE OBJECT: it is deleted with its raw_meta sibling, the failure "
            "is written down, and the capture is re-planned before anything downstream runs.",
        ]),

        ("D2  THE IMAGE + THE JOBDEFS -- the DIGEST-PINNED-JOBDEF LAW. Three new job files exist "
         "in no image and leviathan-dev-world-bank-pink-sheet-bronze is pinned BY DIGEST, so "
         "EVERY submit below D2 is a no-op or a missing-file failure until this step lands.", [
            f"python scripts/ops/make_worker_context_tar.py --out {tar} --ref HEAD",
            "# it REFUSES on a dirty COPY set (tracked content, not `git status` -- this tree "
            "prints phantom M's after a commit) and overlays the gitignored configs/graphrag "
            "subtree, fingerprinted.",
            f"aws s3 cp {tar} s3://{BUCKET}/build_contexts/{tar}",
            f"cat > kaniko_pink_overrides.json <<'JSON'\n  " + json.dumps({"command": [
                "--context", f"s3://{BUCKET}/build_contexts/{tar}",
                "--dockerfile", "docker/leviathan_worker/Dockerfile",
                "--destination", f"{ECR_URL}:{tag}",
                "--build-arg", "BUILD_GIT_COMMIT=<HEAD sha>"]}) + "\n  JSON",
            f"MSYS_NO_PATHCONV=1 aws batch submit-job --job-name kaniko-pink-vintages "
            f"--job-queue {QUEUE} --job-definition {JD_KANIKO} "
            f"--container-overrides file://kaniko_pink_overrides.json --query jobId --output text",
            "# ~9 min in-region. The laptop uplink is 0.06 MB/s -- this is why the tar goes to S3 "
            "and the build happens in-region, never `docker push` from here.",
            f"aws ecr describe-images --repository-name {WORKER_REPO} "
            f"--image-ids imageTag={tag} --query 'imageDetails[0].imageDigest' --output text",
            "# THE SMOKE, before anything trusts the image: a throwaway jobdef on the NEW digest "
            "that only imports the three new modules.",
            "cat > smoke_overrides.json <<'JSON'\n  " + json.dumps({"command": [
                "-c", "import importlib;"
                      "[importlib.import_module(m) for m in ("
                      "'leviathan.common.pink_sheet_release',"
                      "'leviathan.transforms.bronze_to_silver.pink_sheet',"
                      "'leviathan.transforms.raw_to_bronze.pink_sheet_breaks')];"
                      "from leviathan.storage.paths import silver_pink_sheet_vintages_key as k;"
                      "print('smoke ok', k())"]}) + "\n  JSON",
            "# NOTE ON pink_sheet_breaks: the smoke IMPORTS it and nothing else does. The series-"
            "replacement break log is MEASUREMENT-ONLY today -- no producer calls parse_breaks and "
            "no break-log object lands, so the seven same-name/different-series replacements are "
            "DOCUMENTED (KNOWN_BREAKS) but NOT guarded at run time. Wiring it means adding an S3 "
            "write to jobs/batch/pink_sheet_task.py, a LIVE scheduled producer this wave "
            "deliberately does not touch; it is a docket with its own gate, prefix classification "
            "and rollback. Do not read the import as a shipped tripwire.",
            "# THEN: terraform digest pin bump + jobdef re-register.",
            "#   infra/terraform/envs/dev/<tfvars>: pink_sheet_image_digest = "
            "\"sha256:<the digest above>\"   (a TAG is refused by the variable's own validation)",
            "python scripts/ops/check_ecr_pinned_digests.py",
            "terraform -chdir=infra/terraform/envs/dev plan "
            "-target=module.batch.aws_batch_job_definition.world_bank_pink_sheet_bronze",
            "terraform -chdir=infra/terraform/envs/dev apply "
            "-target=module.batch.aws_batch_job_definition.world_bank_pink_sheet_bronze",
            _verify_jobdef(JD_BRONZE),
            "# VERIFY THE REVISION MOVED and the image is the digest you just built. A push "
            "without a re-register is a NO-OP -- that is the measured 2026-08-27 rev-110 vacuous "
            "gate.",
            "",
            "# ---- THE OTHER THREE JOBDEFS. THIS IS THE STEP'S REAL SCOPE. -------------------",
            "# Terraform re-registers exactly ONE of the four jobdefs this runbook submits to, and "
            "it is the one used by the FEWEST steps (D8). Everything else -- D1, D3, D4, D5, D7, "
            "D9 -- runs on " + JD_FLAT_SILVER + " or " + JD_PUBLISHER + ", and D6 on " + JD_GATE
            + ". All three are digest-pinned (infra/terraform/envs/dev/variables.tf), none is a "
            "terraform aws_batch_job_definition resource in this stack, and a push to ECR does not "
            "move a digest-pinned jobdef. Without the three registrations below, every one of "
            "those steps runs an image that has never seen jobs/batch/pink_sheet_vintages_task.py, "
            "jobs/batch/pink_sheet_archive_task.py, jobs/ingest/backfill_pink_sheet_vintages.py or "
            "the new F010 contract -- a missing-file failure at best and a silent no-op at worst.",
            "# READ THE CURRENT DEFINITION, CHANGE ONLY THE IMAGE, VERIFY THE NEW REVISION AND THE "
            "DIGEST EXACT. Write the helper once (a FILE, not a `python -c`: this tree's shell "
            "eats backslashes in one-liners), then run it three times.",
            "cat > register_jobdef_on_digest.py <<'PY'\n  "
            + _REGISTER_HELPER.replace("\n", "\n  ") + "\n  PY",
            *[line
              for jd in (JD_FLAT_SILVER, JD_GATE, JD_PUBLISHER)
              for line in (
                  f"python register_jobdef_on_digest.py {jd} {ECR_URL}@sha256:<the digest above>",
                  _verify_jobdef(jd))],
            "# EXPECT for each: OLD <rev> <old image>, NEW <rev+n>, VERIFIED <name> rev <rev+n> "
            "<the digest above>. The helper ASSERTS the revision moved and the image matches "
            "byte-for-byte; it exits non-zero rather than printing a reassuring line.",
            "# ALL THREE MUST BE DONE BEFORE D3. D3 is the first step that submits to "
            + JD_FLAT_SILVER + " with a new file in the command.",
        ]),

        ("D2b G-A3 / K4 'BEFORE' -- the served-object identity, taken BEFORE the first run of "
         "this wave. The ETag bracket is around the RUNS, not the commit: a git commit cannot "
         "move an S3 ETag, so bracketing the commit would be vacuous and K4 could never fire.", [
            _head(SERVED_SILVER_KEY),
            "# BANK this triple. D10 re-reads it. THRESHOLD: exact ETag equality across D3..D9.",
        ]),

        ("D3  LANE (a) SHADOW -- the bitemporal build, nothing canonical. Its own sibling root, "
         "no live surface, so it may run out of band.", [
            _submit("pink-sheet-vintages-shadow", JD_FLAT_SILVER,
                    ["jobs/batch/pink_sheet_vintages_task.py", "--publish-mode", "shadow"]),
            "# READ the log line `object_count=%d vintage_count=%d releases=%s`. TWO NUMBERS, and "
            "the second is the answer to 'how many vintages does bronze hold': object_count is the "
            "S3 listing's own tally, vintage_count is the distinct release_ym across the ROWS. They "
            "diverge exactly when both bronze prefixes hold one release -- which is the case the "
            "dedup exists for, so a single number under a vintage-count name would hide it.",
            f"# PREDICTION: object_count 4, vintage_count 4 {sorted(BANKED)} and "
            f"{sum(BANKED.values())} rows ({'+'.join(str(v) for v in BANKED.values())}).",
            "# A COUNT THAT DISAGREES WITH THE PREDICTION IS THE FINDING -- do not proceed to D5 "
            "on an unexplained number.",
            "# ALSO READ the two machine lines, which are printed whether or not anything fired "
            "(absent is never zero):",
            "#   VINTAGE_COUNTERS {releases_seen, releases_built, releases_quarantined, "
            "duplicate_rows_dropped, duplicate_rows_dropped_value_conflict, "
            "releases_in_both_prefixes, clock_rung_1, clock_rung_2}",
            "#   VINTAGE_QUARANTINE {release_ym: reason}  -- reason in "
            "(not_full_restatement | duplicate_restatement | pivot_duplicate_columns)",
            "# A QUARANTINED RELEASE IS NOT A FAILED RUN: the table builds without it, by design, "
            "because this task is a publishes:true leg of the live chain and one bad release must "
            "not red the served chain. It IS a finding -- investigate before D5.",
            "# clock_rung_1 counts releases whose raw_meta sidecar carried an origin Last-Modified. "
            "On the four banked objects EXPECT 0: none was captured with the header recorded, so "
            "all four take derived_month_first. That zero is measured, not assumed.",
        ]),

        ("D4  SHADOW GATES G-A1 / G-A2 / G-A2b / G-A6 -- read the SHADOW object, $0.", [
            f"aws s3 ls s3://{BUCKET}/shadow/ --recursive | grep pink_sheet_vintages",
            "# G-A1 FULL RESTATEMENT: every release's month set is the complete hole-free "
            "1960-01..R-1 run and n == 12*(year-1960)+month-1.",
            "# G-A2 ONE CLOCK: groupby(release_ym).release_date.nunique() == 1 and "
            ".release_date_source.nunique() == 1; NO release_date is the last day of its own month.",
            "# G-A2b PHYSICAL TYPE: release_date is a STRING matching ^\\d{4}-\\d{2}-\\d{2}$, it "
            "IS in the parquet FOOTER columns, and the contract's partition_keys is EMPTY.",
            "# G-A6 GENERATOR OWNERSHIP: already discharged locally at D0 "
            "(gen_registry_from_baseline.py --check prints 'registry check OK').",
            _submit("pink-vintages-shadow-gates", JD_FLAT_SILVER, [
                "-c",
                "import boto3,io,json,calendar,pandas as pd;"
                "from leviathan.common.pink_sheet_release import expected_month_count,"
                "is_full_restatement;"
                f"b=boto3.client('s3').get_object(Bucket='{BUCKET}',"
                "Key='<the shadow key from the listing above>')['Body'].read();"
                "d=pd.read_parquet(io.BytesIO(b));"
                "g={};\n"
                "for r,sub in d.groupby('release_ym'):\n"
                "    ms=['%04dM%02d'%(x.year,x.month) for x in sub['date']];"
                "    y,m=int(r[:4]),int(r[5:7]);"
                "    g[r]={'n':len(ms),'expected':expected_month_count(r),"
                "'full':is_full_restatement(ms),"
                "'release_date':sorted(set(sub['release_date'])),"
                "'source':sorted(set(sub['release_date_source'])),"
                "'month_end':'%04d-%02d-%02d'%(y,m,calendar.monthrange(y,m)[1])}\n"
                "print(json.dumps({'gates':g,'dtype':str(d['release_date'].dtype),"
                "'shape_ok':bool(d['release_date'].str.match(r'^\\\\d{4}-\\\\d{2}-\\\\d{2}$')"
                ".all()),'cols':list(d.columns)[:6]+['...'],'rows':len(d)},indent=1))"]),
        ]),

        ("D5  LANE (a) CANONICAL -- on the PUBLISHER RUNNER, with BOTH KMS env entries. "
         "`shadow_canonical` is a DAG descriptor and NOT a CLI choice: the task declares "
         "--publish-mode {dry-run,shadow,canonical} and exits 2 on anything else.", [
            _submit("pink-sheet-vintages-canonical", JD_PUBLISHER,
                    ["jobs/batch/pink_sheet_vintages_task.py", "--publish-mode", "canonical"],
                    env=KMS_ENV),
            _head(VINTAGE_SILVER_KEY),
            "# THERE IS NO CENSUS STEP. jobs/audit/advance_rolling_census.py declares only --asof "
            "and --dest-uri, and reconcile() re-seeds the WHOLE family's census.json -- so there "
            "is no way to ADD one table's entry, and Branch B has no census stage that would want "
            "one. silver_pink_sheet's baseline entry stays untouched BY OMISSION.",
        ]),

        ("D6  THE GATE -- BRANCH B for the new table, BRANCH A for the sibling, so "
         "GRAPHRAG_NUMBERS_BACKEND=pg is MANDATORY on the ask.", [
            _submit("pink-sheet-gate", JD_GATE,
                    ["-m", "jobs.audit.silver_rebuild_gate", "--tables",
                     f"{SIBLING},{TABLE}", "--asof", "<UTC ISO now>",
                     "--baseline-uri", BASELINE],
                    env=[{"name": "GRAPHRAG_NUMBERS_BACKEND", "value": "pg"}]),
            f"# EXPECT {TABLE} -> BRANCH_B, three stages: stage_feature_probe GREEN "
            f"(pk is EMPTY because the table is flat, and every required column is in the "
            f"footer), stage_value_census GREEN (min_nonnull_frac 0.5 plus the single_vintage row, "
            f"which passes on 4 distinct vintages), stage_config_check INHERITING the estate-wide "
            f"disposition {SIBLING} already carries today.",
            "# A gate run BEFORE the F010 contract is committed is RED BY CONSTRUCTION "
            "(select_branch -> BRANCH_UNKNOWN, 'fail-closed: the gate reports it red').",
            "# If a future rebuild ever holds ONE vintage, the honest answer is a declared "
            "`vintage_waiver` with its reason -- never a loosened floor. That is an OWNER call.",
        ]),

        ("D7  LANE (b) PHASE 0 -- the ORIGIN-EPOCH harvest. $0, no archive traffic, ~30 min. "
         "Run it BEFORE Phase 1: free, faster, no politeness budget, and a retired epoch folder "
         "that still serves is an OBSERVED behaviour the World Bank never promised.", [
            _submit("pink-origin-harvest-dry", JD_FLAT_SILVER,
                    ["jobs/ingest/backfill_pink_sheet_vintages.py", "--phase", "origin",
                     "--dry-run"]),
            "# READ THE PLAN, then re-run without --dry-run:",
            _submit("pink-origin-harvest", JD_FLAT_SILVER,
                    ["jobs/ingest/backfill_pink_sheet_vintages.py", "--phase", "origin"]),
            f"# PREDICTION: yield is TWO, not six-to-nine -- {json.dumps(PHASE0_EXPECTED)} "
            f"(row counts). Three sighted epochs are MEASURED 404; the 2016 epoch's unhyphenated "
            f"URL 200s with 100,826 bytes of HTML and declines body_not_workbook.",
            f"aws s3 ls s3://{BUCKET}/{ARCHIVE_RAW_PREFIX} --recursive",
            "# FIRST CAPTURE WINS: it must never overwrite an existing raw key. Objects land under "
            "the ARCHIVE prefix, which the scheduled chain never relists.",
        ]),

        ("D8  LANE (b) ARCHIVE BRONZE + THE SERVED-SET CENSUS -- writes ONLY under the archive "
         "bronze prefix.", [
            _submit("pink-archive-bronze", JD_BRONZE,
                    ["jobs/batch/pink_sheet_archive_task.py"]),
            f"aws s3 ls s3://{BUCKET}/{ARCHIVE_BRONZE_PREFIX} --recursive",
            f"aws s3 cp s3://{BUCKET}/{ARCHIVE_BRONZE_PREFIX}_served_set_census.json -",
            "# EXPECT total_extra_keys == 0 for both new vintages -- that is the field the JSON "
            "actually carries (served_set_census writes `total_extra_keys` / "
            "`extra_governed_keys`; only the log line spells it the long way, and grepping the "
            "JSON for the long name finds nothing, which reads as absence rather than zero). "
            "Already measured locally (0/28,860 and 0/29,304). A DISAGREEMENT between the local "
            "measurement and the cloud extract IS ITSELF THE FINDING.",
            "# A release with no strictly-newer scheduled release DECLARES 'UNMEASURED' rather "
            "than reporting zero: absent is never zero.",
            "# THEN re-run the vintage build (D3 then D5) -> 6 releases, ~4,765 rows.",
        ]),

        ("D9  LANE (b) PHASE 1 -- the PAGED worldbank.org DOMAIN census, then BOUNDED harvests. "
         "In-VPC only. Budget in PAGES, never one call.", [
            _submit("pink-cdx-census", JD_FLAT_SILVER,
                    ["jobs/ingest/backfill_pink_sheet_vintages.py", "--phase", "wayback",
                     "--census-only"]),
            "# This run fetches NO bodies. Its output -- distinct captures, distinct digests, "
            "earliest capture, page count, the PER-HOST histogram and the per-year histogram "
            "across BOTH filename spellings -- IS the sizing measurement for the whole lane.",
            "# NO downstream sitting may quote a capture count from the design: there is none.",
            "# A `truncated: true` report means the census hit the page ceiling with a resume key "
            "still present -- every count in it is a FLOOR, not a total.",
            _submit("pink-wayback-harvest", JD_FLAT_SILVER,
                    ["jobs/ingest/backfill_pink_sheet_vintages.py", "--phase", "wayback",
                     "--max-captures", "40"]),
            "# BOUNDED BATCHES: 2.5 s per body, so ~5 min per 100 captures plus retries. A run "
            "that lands 40 vintages is recoverable where a 300-capture run that dies at 280 with "
            "no manifest is not.",
            "# THE IDENTITY MUST HOLD EXACTLY, AND IT IS COUNTED OVER ATTEMPTS: "
            "n_landed_captures + n_declines == attempted, and `identity_holds` says so in the "
            "report. Read n_landed_captures, NOT n_releases_landed -- two captures can land one "
            "release, and a release-keyed tally makes a normal harvest look unaccounted.",
            "# EVERY DECLINE FROM THE CLOSED VOCABULARY (capture_drift | unpinnable_timestamp | "
            "content_key_mismatch | not_full_restatement | extract_narrow | duplicate_values | "
            "non_200 | body_not_workbook | format_unsupported | already_held). `already_held` is a "
            "capture that found its key taken -- first capture wins, nothing was written, and it "
            "is a DECLINE rather than a landing.",
            "# THERE IS NO WIDENING GUARD AT HARVEST TIME, and there cannot be: the question needs "
            "the SCHEDULED frames a harvest does not hold. Widening is measured at D8 by "
            "served_set_census, about an object that has already landed -- the object stays in raw, "
            "un-bronzed if the owner says so, and counted. The report names that seam in its own "
            "`widening_measured_in` field.",
            "# G-B0b (the pre-2021 probe) runs only AFTER the census names a pre-2021 capture, "
            "with --max-captures 1 pinned to that timestamp. Relaxing _REQUIRED_SERIES is NOT on "
            "the menu in any branch -- a narrow era is an OWNER decision or a counted refusal.",
        ]),

        ("D10 G-A3 / K4 'AFTER' + G-A3b NORMAL-ADVANCE -- the closing half of the ETag bracket, "
         "read AFTER D9 rather than after the commit.", [
            _head(SERVED_SILVER_KEY),
            "# G-A3 THRESHOLD: the ETag and ContentLength must be IDENTICAL to the D2b reading. "
            "Lanes (a) and (b) move no served byte; a moved byte falsifies the whole safety "
            "argument and the vintage table waits until the leak is found.",
            "# G-A3b, AT THE SCHEDULED FIRE (not here): the served object's date set grew by "
            "exactly the new month(s); every changed cell belongs to a month the new release "
            "restated; and ZERO cells moved from NULL to a value on a date the previous served "
            "object already covered.",
            "# Under the archive-prefix fence that third clause is structurally impossible. It is "
            "MEASURED anyway -- that is what turns 'structurally impossible' into an observation.",
        ]),

        ("D11 THE DAG ARM -- the descriptor is committed; the tfvars render and the apply are "
         "THIS step. A SECOND publishes:true task renders TWO entries, not one.", [
            "python scripts/silver/gen_dag_schedules_tfvars.py --diff",
            "# READ-ONLY, AND IT IS THE ONLY INVOCATION OF THAT GENERATOR IN THIS RUNBOOK. As of "
            "this wave the incumbent tfvars is ALSO behind on `psd_monthly` (the 2026-08-26 Lane-3 "
            "psd_attributes legs landed in the descriptor and were never folded in), and "
            "psd_monthly is ENABLED -- so a BARE run, which writes the whole assembled tfvars, "
            "ARMS A LIVE SCHEDULE BELONGING TO ANOTHER LANE. This step used to warn about exactly "
            "that and then print the bare command as the next line; it no longer does.",
            "# THERE IS NOTHING TO WRITE HERE. infra/terraform/envs/dev/dag_schedules.auto.tfvars"
            ".json ALREADY carries the re-rendered pink_sheet_monthly entry: it was SPLICED during "
            "the build at STEM granularity by a ONE-OFF splice script that lives outside the repo (it is "
            "not a standing tool and is not needed again: `--diff` is the standing check) -- the "
            "generator's own assembly was taken for `dag_schedules.pink_sheet_monthly` alone and "
            "every other stem, psd_monthly included, kept its incumbent bytes (one changed line in "
            "the file). `--diff` above should therefore show pink_sheet_monthly CLEAN and "
            "psd_monthly still drifting; psd_monthly's drift is that lane's to fold, with its own "
            "review.",
            "# (The same fact from the other side: tests/unit/test_dag_descriptor_publish_modes.py"
            "::test_descriptor_matches_rendered_tfvars fails today with drifting={'psd_monthly'} "
            "and PENDING_HAND_MERGE empty. That red pre-dates this wave and is not resolved by "
            "arming the schedule.)",
            "# THE TWO RENDERED ENTRIES, enumerated so neither is a surprise at apply time:",
            "#   phases.silver.tasks[1] = jobs/batch/pink_sheet_vintages_task.py "
            "--publish-mode shadow   on " + JD_FLAT_SILVER,
            "#   promote.tasks[1]       = jobs/batch/pink_sheet_vintages_task.py "
            "--publish-mode canonical on " + JD_PUBLISHER
            + " with LEVIATHAN_APPROVAL_MODE=kms + LEVIATHAN_KMS_KEY_ID",
            "#   gate.command --tables  = " + f"{SIBLING},{TABLE}",
            "# THE PUBLISHER RUNNER'S OWN IMAGE must carry jobs/batch/pink_sheet_vintages_task.py "
            "or the promote leg dies on a missing file -- check it against the D2 digest before "
            "the apply.",
            "terraform -chdir=infra/terraform/envs/dev plan "
            "-target='module.eventbridge.aws_scheduler_schedule.family[\"pink_sheet_monthly\"]'",
            "# MEASURED 2026-09-04: there is NO module.scheduler in this stack (the schedules are "
            "module.eventbridge's aws_scheduler_schedule.family[<stem>]); a -target on a name that "
            "resolves to nothing plans ZERO changes and reads as 'already armed' while the live "
            "schedule still lacks the vintage tasks. Single-resource address, gated on its shape.",
            "terraform -chdir=infra/terraform/envs/dev apply "
            "-target='module.eventbridge.aws_scheduler_schedule.family[\"pink_sheet_monthly\"]'",
            "# MEASURED 2026-09-04: there is NO module.scheduler in this stack (the schedules are "
            "module.eventbridge's aws_scheduler_schedule.family[<stem>]); a -target on a name that "
            "resolves to nothing plans ZERO changes and reads as 'already armed' while the live "
            "schedule still lacks the vintage tasks. Single-resource address, gated on its shape.",
            "# The next scheduled fire (cron(0 16 8 * ? *)) then carries the vintage build under "
            "the same gate. VERIFY the job EXISTS after fire time -- scheduler roles are "
            "RESOURCE-SCOPED per jobdef and a borrowed role is AccessDenied at fire.",
        ]),
    ]


# ---------------------------------------------------------------------------
# CHECK -- the AWS-free preflight. Reads local files; runs nothing that mutates.
# ---------------------------------------------------------------------------

def _cmd(argv: list[str]) -> tuple[int, str]:
    proc = subprocess.run(argv, cwd=str(_REPO), capture_output=True, text=True)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def check() -> int:
    """Every property this wave can prove without AWS. Prints PASS/FAIL per line."""
    failures = 0

    def _say(ok: bool, label: str, detail: str = "") -> None:
        nonlocal failures
        if not ok:
            failures += 1
        print(f"{'PASS' if ok else 'FAIL'} {label}" + (f" -- {detail}" if detail else ""))

    # 1. the F010 contract exists and says what the gate will read.
    import yaml
    path = _REPO / "configs" / "silver" / "tables" / f"{TABLE}.yaml"
    if not path.exists():
        _say(False, "F010 contract present", f"{path} is missing -- the gate would return "
                                             f"BRANCH_UNKNOWN and report the table RED")
        contract = {}
    else:
        contract = yaml.safe_load(path.read_text(encoding="utf-8"))
        _say(True, "F010 contract present", str(path.relative_to(_REPO)))
        _say(contract.get("natural_key") == ["release_date", "date"],
             "natural_key is [release_date, date] (vintage axis FIRST)",
             str(contract.get("natural_key")))
        _say(contract.get("partition_keys") == [],
             "partition_keys is EMPTY (flat; release_date is an IN-FILE column)",
             str(contract.get("partition_keys")))
        _say(contract.get("knowledge_date_col") == "release_date"
             and contract.get("knowledge_semantics") == "vintage"
             and contract.get("publication_lag_days") == 0,
             "PIT trio is (release_date, vintage, 0)",
             f"{contract.get('knowledge_date_col')}/{contract.get('knowledge_semantics')}/"
             f"{contract.get('publication_lag_days')}")
        _say(contract.get("numbers_ref") is None,
             "NO numbers card is referenced (nothing model-facing moves in this commit)",
             str(contract.get("numbers_ref")))
        _say(set(contract.get("required_nonnull") or []) ==
             {"date", "release_ym", "release_date", "release_date_source"},
             "required_nonnull names the four columns that can never be null",
             str(contract.get("required_nonnull")))
        _say(len(contract.get("value_columns") or []) >= 70,
             "value_columns is the GOVERNED set, not the two the source contract names",
             f"{len(contract.get('value_columns') or [])} columns")

    # 2. the source contract is its OWN, not a copy of the sibling's.
    sc = yaml.safe_load((_REPO / "configs" / "datasets" / "source_contracts.yaml")
                        .read_text(encoding="utf-8"))
    blocks = {b["source_key"]: b for b in (sc.get("sources") or sc.get("contracts") or sc)
              if isinstance(b, dict) and "source_key" in b} if not isinstance(sc, dict) else \
        {b["source_key"]: b for v in sc.values() if isinstance(v, list) for b in v
         if isinstance(b, dict) and "source_key" in b}
    block = blocks.get("pink_sheet_vintages", {})
    _say(bool(block), "source contract block pink_sheet_vintages exists")
    if block:
        _say(block.get("natural_key") == ["release_date", "date"],
             "source-contract natural_key is the vintage key",
             str(block.get("natural_key")))
        _say(block.get("expected_min_rows") == 1500,
             "expected_min_rows is its OWN 1500, not the sibling's 100",
             str(block.get("expected_min_rows")))
        _say(blocks.get("pink_sheet", {}).get("natural_key") == ["date"],
             "the EXISTING pink_sheet block is untouched",
             str(blocks.get("pink_sheet", {}).get("natural_key")))

    # 3. the gate branch, resolved for real.
    try:
        from leviathan.silver.registry import load_registry as silver_registry

        from jobs.audit import silver_rebuild_gate as gate
        reg = silver_registry()
        branch = gate.select_branch(TABLE, silver_reg=reg)
        _say(branch == gate.BRANCH_B, "gate routes the vintage table to BRANCH_B", branch)
        _say(TABLE not in gate.PG_MIRROR_TABLES,
             "the vintage table is ABSENT from PG_MIRROR_TABLES (no pg reload, no parity)")
        stage_names = [s.__name__ for s in gate._BRANCH_B_STAGES]
        _say("stage_cascade_census_diff" not in stage_names,
             "Branch B has NO census stage -- so no rolling-census baseline is needed",
             ", ".join(stage_names))
    except Exception as exc:  # noqa: BLE001
        _say(False, "gate branch resolution", str(exc)[:160])

    # 4. the prefix fence, as a property rather than a promise.
    try:
        from leviathan.storage import paths

        import jobs.batch.pink_sheet_silver_task as ss
        import jobs.batch.pink_sheet_task as st
        raw_key = paths.raw_pink_sheet_archive_key("2025M01", "x.xlsx")
        bronze_key = paths.bronze_pink_sheet_archive_key("2025M01")
        _say(not raw_key.startswith(st._RAW_PREFIX),
             "archive RAW key is not under the scheduled raw prefix")
        _say(not bronze_key.startswith(ss._BRONZE_PREFIX),
             "archive BRONZE key is not under the scheduled bronze prefix")
        for job in ("pink_sheet_task.py", "pink_sheet_silver_task.py"):
            text = (_REPO / "jobs" / "batch" / job).read_text(encoding="utf-8")
            _say("world_bank_pink_sheet_archive" not in text,
                 f"{job} carries NO archive symbol")
        _say(not paths.silver_pink_sheet_vintages_key().startswith("silver/pink_sheet/"),
             "the vintage silver object is a SIBLING of silver/pink_sheet, never nested")
    except Exception as exc:  # noqa: BLE001
        _say(False, "prefix fence", str(exc)[:160])

    # 5. the DAG descriptor, and the promote leg it creates.
    dag = json.loads((_REPO / "configs" / "silver" / "dags" / "pink_sheet_monthly.json")
                     .read_text(encoding="utf-8"))
    silver_tasks = [t for p in dag["phases"] if p["name"] == "silver" for t in p["tasks"]]
    ids = [t["id"] for t in silver_tasks]
    _say("pink_sheet_vintages" in ids, "the DAG's silver phase carries the vintages task",
         ", ".join(ids))
    _say(TABLE in dag.get("gate_tables", []), "gate_tables carries the vintage table",
         ", ".join(dag.get("gate_tables", [])))
    publishing = [t for t in silver_tasks if t.get("publishes")]
    _say(len(publishing) == 2,
         "TWO publishes:true silver tasks -> gen_dag_schedules_tfvars renders TWO promote tasks",
         f"{len(publishing)} publishing task(s)")
    _say(all(t.get("publish_mode") == "shadow_canonical" for t in publishing),
         "both publish_mode values are shadow_canonical (a DAG descriptor, never a CLI choice)")

    # 6. the tfvars, and the drift that is NOT this wave's.
    tf = json.loads((_REPO / "infra" / "terraform" / "envs" / "dev"
                     / "dag_schedules.auto.tfvars.json").read_text(encoding="utf-8"))
    entry = tf["dag_schedules"].get("pink_sheet_monthly", {})
    body = entry.get("input_json", "")
    _say("pink_sheet_vintages_task.py" in body,
         "the rendered pink_sheet_monthly entry carries the vintages task")
    _say(body.count("pink_sheet_vintages_task.py") >= 2,
         "it carries BOTH legs (silver shadow + promote canonical)",
         f"{body.count('pink_sheet_vintages_task.py')} occurrences")
    _say(TABLE in body, "the rendered gate ask names the vintage table")

    # 6b. THE STEP TEXT ITSELF, asserted rather than trusted. Two of this wave's adjudicated
    #     findings live entirely in the printed commands, so they are checkable here and nowhere
    #     else: a runbook is only as good as the exact strings an operator pastes.
    printed = [cmd for _title, cmds in steps("CHECK") for cmd in cmds]
    blob = "\n".join(printed)

    d2 = next((cmds for title, cmds in steps("CHECK") if title.startswith("D2 ")), [])
    d2_blob = "\n".join(d2)
    for jd in (JD_BRONZE, JD_FLAT_SILVER, JD_GATE, JD_PUBLISHER):
        _say(jd in d2_blob, f"D2 re-registers {jd}",
             "a submit to a jobdef D2 never re-registers runs an image without this wave's files")
    _say("register_jobdef_on_digest.py" in d2_blob,
         "D2 carries the explicit register-job-definition helper for the three non-terraform "
         "jobdefs")
    _say(all(f"python register_jobdef_on_digest.py {jd}" in d2_blob
             for jd in (JD_FLAT_SILVER, JD_GATE, JD_PUBLISHER)),
         "each of the three is registered by name, not described in prose")

    # every describe-job-definitions verify query selects the MAX revision explicitly
    _say("revisionentry" not in blob,
         "no step queries `revisionentry` (not a field; JMESPath returns null, and the step whose "
         "point is proving the revision moved would print a reassuring null)")
    describes = [c for c in printed if "describe-job-definitions" in c]
    _say(bool(describes) and all(_JD_MAX_REV in c for c in describes),
         "every describe-job-definitions query selects the max revision explicitly",
         f"{len(describes)} query line(s)")
    _say(not any("jobDefinitions[-1]" in c for c in printed),
         "no step relies on jobDefinitions[-1] being the newest revision")

    # D11: the generator appears ONLY as the read-only --diff
    gen_lines = [c for c in printed if "gen_dag_schedules_tfvars.py" in c and not
                 c.lstrip().startswith("#")]
    _say(gen_lines and all("--diff" in c for c in gen_lines),
         "gen_dag_schedules_tfvars.py is printed ONLY as the read-only --diff",
         "; ".join(gen_lines) or "not printed at all")
    _say(any("SPLICED" in c for c in printed),
         "D11 states that the pink_sheet_monthly tfvars entry is already spliced")

    # 6c. THE MEASUREMENT-ONLY DECLARATION, in the module and in the runbook, together.
    breaks_src = (_REPO / "src" / "leviathan" / "transforms" / "raw_to_bronze"
                  / "pink_sheet_breaks.py").read_text(encoding="utf-8")
    _say("MEASUREMENT-ONLY TODAY" in breaks_src,
         "pink_sheet_breaks declares itself measurement-only (no producer calls it, no object "
         "lands, so the tripwire the design names is unshipped)")
    _say("MEASUREMENT-ONLY today" in blob or "MEASUREMENT-ONLY" in blob,
         "the runbook says the same thing where the operator meets the module (D2's smoke)")

    # 7. THE RUNBOOK'S OWN DRY-RUN PROPERTY, asserted about itself rather than promised in prose.
    #    It is checked on the PARSE TREE, not on the text: `boto3.client(` appears inside the
    #    python -c string D1 PRINTS for the operator, and a substring scan would call that a
    #    violation. What matters is that this module never IMPORTS an AWS SDK and never SHELLS OUT
    #    to anything but the local checks -- so those are the two things checked.
    import ast
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    shelled: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name in ("run", "check_output", "call", "Popen", "system"):
                shelled.add(name)
    _say("boto3" not in imported and "botocore" not in imported,
         "this runbook imports NO AWS SDK -- every mutating command is printed, never called",
         ", ".join(sorted(imported & {"boto3", "botocore"})) or "none")
    _say(shelled <= {"run"},
         "the only subprocess entrypoint is the local-check runner",
         ", ".join(sorted(shelled)) or "none")

    print(f"\n{'CHECK OK' if not failures else 'CHECK FAILED'}: {failures} failure(s)")
    return 0 if not failures else 1


# ---------------------------------------------------------------------------
# ROLLBACK -- printed, never executed.
# ---------------------------------------------------------------------------

def rollback() -> int:
    print("ROLLBACK -- THREE LAYERS, OUTERMOST FIRST. Nothing below is executed by this script.\n")
    print("(i) SERVING -- NOTHING TO ROLL BACK.")
    print("    No numbers card, no pg-mirror entry, no system-prompt change: "
          "agent.system_prompt(load_registry()) is byte-identical across this commit (G-A4),")
    print("    and it holds only BECAUSE no card is registered -- _table_card renders for every "
          "visible table, so a card would be a model-facing change on every turn.\n")

    print("(ii) DATA -- the DERIVED layer only.")
    print(f"    aws s3 rm --recursive s3://{BUCKET}/silver/pink_sheet_vintages/")
    print("    # The root is a SIBLING, so this removes the whole table and cannot touch "
          "silver/pink_sheet.")
    print(f"    aws s3 rm --recursive s3://{BUCKET}/{ARCHIVE_BRONZE_PREFIX}")
    print("    # The archive BRONZE is derived and re-derivable. THE LANDED RAW OBJECTS ARE NOT "
          "ROLLED BACK on a code problem --")
    print("    # they are the asset, and raw is immutable by contract. TWO cases DO require "
          "deleting a raw object, both content failures:")
    print("    #   (a) a vintage landed under the WRONG month (a content-key or capture-drift "
          "escape);")
    print("    #   (b) a body that turns out not to be a workbook at all.")
    print("    # Delete the object AND its raw_meta sibling, write the failure down, and re-plan "
          "the capture. First capture wins, so a re-run after a delete lands the correct object.")
    print("    # A WIDENING CENSUS FINDING IS NOT ONE OF THEM: the object stays in raw, un-bronzed "
          "if the owner says so, and counted.\n")

    print("(iii) CODE / CONFIG -- git revert.")
    print("    git revert <commit>    # also removes the synthetic R0 record; then re-run")
    print("    python scripts/silver/gen_registry_from_baseline.py       "
          "# drops the contract")
    print("    python scripts/silver/generate_ddls_from_registry.py --write")
    print(f"    {_head(SERVED_SILVER_KEY)}   # re-assert G-A3\n")

    print("    THE FETCH RE-ORDER ROLLS BACK ON ITS OWN -- it is the one lane-(a) edit that "
          "touches a LIVE SCHEDULE's behaviour.")
    print("    `git revert` that commit restores the pre-download label-key skip exactly. The only "
          "state it leaves behind is raw objects keyed by DERIVED month, which are correct under "
          "BOTH orders and are NEVER re-keyed:")
    print("    re-keying a correctly-keyed object would be the mislabelling this wave exists to "
          "prevent, applied backwards.\n")

    print("    IF THE DAG ENTRY ALREADY SHIPPED: remove the vintages task and the gate_tables "
          "entry from configs/silver/dags/pink_sheet_monthly.json, re-render")
    print("    infra/terraform/envs/dev/dag_schedules.auto.tfvars.json and re-apply. There is NO "
          "census entry to delete, because none was ever created.\n")

    print("    DO NOT re-run jobs/batch/pink_sheet_silver_task.py as part of any rollback: the "
          "served table was never touched, and running it out of band is exactly what the F1 law "
          "forbids.")
    return 0


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
    ap = argparse.ArgumentParser(description="PINK SHEET VINTAGES lanes (a)+(b) runbook "
                                             "(dry-run by construction; nothing is mutated)")
    ap.add_argument("--step", default="PRINT", choices=["PRINT", "CHECK", "ROLLBACK"] + stems)
    ap.add_argument("--run-id",
                    default=f"{datetime.now(tz=timezone.utc):%Y%m%dT%H%M}")
    args = ap.parse_args(argv)
    if args.step == "CHECK":
        return check()
    if args.step == "ROLLBACK":
        return rollback()
    print_steps(args.run_id, None if args.step == "PRINT" else args.step)
    return 0


if __name__ == "__main__":
    sys.exit(main())
