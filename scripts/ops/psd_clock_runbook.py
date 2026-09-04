#!/usr/bin/env python
"""PSD HONEST-CLOCK (lane E) RUNBOOK -- prints the exact command for every step, and RUNS
the checks a human cannot eyeball. IT NEVER MUTATES ANYTHING.

    python scripts/ops/psd_clock_runbook.py                  # print every step's commands
    python scripts/ops/psd_clock_runbook.py --step R4        # print one step
    python scripts/ops/psd_clock_runbook.py --step CHECK     # run the AWS-FREE preflight
    python scripts/ops/psd_clock_runbook.py --step ROLLBACK  # print the layered rollback

DRY RUN BY CONSTRUCTION. There is no ``--run`` and no code path that submits a Batch job, writes
S3, registers a job definition, downloads a file or applies terraform: every mutating command is
PRINTED for the operator to paste. ``--step CHECK`` reads local files only. That is deliberate and
it is the difference between a runbook and a deploy script.

WHAT LANE E IS
--------------
``silver_psd``'s ``release_date`` was computed by a MARKETING-YEAR ROTATION: it read the bulk
file's ``Month`` as an MY-relative index and rotated it by the commodity's marketing-year start
month.  MEASURED on three banked bronze snapshots the rotation is EXACT on 3,276 of 1,653,988
stamped rows (0.20%), EARLY on 97.4% and LATE on 2.4%; it emits 809 distinct dates of which 708 are
dates USDA never published, and it never produces 338 real ones under the SHIPPED day rule (E-day-B;
the same count is 186 under E-day-A, a uniform WASDE day -- the 708 is identical under both because it
depends only on the fabricated side).  Lane E replaces it with the row's
OWN ``(Calendar_Year, Month)`` stamp resolved to a day by named, counted conventions.

WHAT THE CHANGE IS AND IS NOT, measured at the physical grain:

    247,036 rows -> 247,294 (+258 older vintages the retired vintage key was DELETING)
    247,036 matched keys / 0 canonical-only / 0 shadow-only / 0 differing on the eight _mt columns
    su_ratio and su_ratio_yoy_delta BYTE-IDENTICAL on all 247,036 joined keys
    809 distinct release_date values -> 439 (E-day-B), 708 fabricated-only dates gone

It is a COVERAGE and VINTAGE-SELECTION correction, not a value correction, and the flip dossier
must say exactly that.  The reason it matters is LEAKAGE: the fabricated clock was early on 97.4%
of stamped rows, so a historical-asof read today sees rows USDA had not published -- 17.96% of a
2010 view, 3.73% of a 2026-01 view.

THE ORDER IS FORCED
-------------------
The WASDE backfill (R3b) precedes the shadow run, because its two days change the fallback counter
every gate reads.  The shadow run precedes every blocking gate.  The owner's word precedes the
canonical promote.  THE PG RELOAD OF BOTH PSD TABLES PRECEDES ANY CLAIM THAT ANYTHING SERVES:
``silver_psd`` is ``P1_TABLES[0]`` with ``consumers: both``, pgnumbers is the serve path and Athena
is off it, so a canonical promote alone changes NOTHING a reader sees.  And G3 follows the promote,
because there is no shadow read path: ``pgnumbers.SCHEMA`` and ``load_pg_numbers.SCHEMA`` are module
constants, ``load_table`` takes its location from Glue, and the CLI accepts only ``--tables`` and
``--dry-run``.

THE DIGEST-PINNED-JOBDEF LAW
----------------------------
``leviathan-dev-psd-silver`` is pinned BY DIGEST (``var.psd_silver_image_digest``), so a git push is
a NO-OP and THE REPIN IS THE DEPLOY.  Order: kaniko context tar (git archive) -> S3 -> IN-REGION
kaniko build -> read the pushed digest from the log, never infer it -> terraform digest bump ->
jobdef re-register -> CONFIRM the new revision number -> submit -> verify by NEW job id, startedAt
strictly after the push, and the digest exact in the container description.
NOTHING ELSE RIDES THAT DIGEST MOVE.  The variable's own comment states the law: one digest move,
one attributable content change, or a green first fire is not citable and a red one is not
attributable.

THE SAME-CRON RACE WITH wasde_monthly, AND ITS BOUNDED WAIT
-----------------------------------------------------------
NAMED HERE because a fail-closed raise that fires on a self-resolving condition is an
outage, not a fence.  ``psd_monthly`` and ``wasde_monthly`` BOTH fire ``cron(0 18 8-13 * ? *)``
with NO ordering dependency between them (read from the rendered
``infra/terraform/envs/dev/dag_schedules.auto.tfvars.json``; the preflight asserts it), and the
clock RAISES when a PSD stamp month is newer than the newest REGISTERED ``silver_wasde``
partition.  The estate's own ETag measurement shows the vendor's PSD object flipping content ON
the WASDE day -- 2026-08-08/09/10/11 share one ETag, 08-12/13 share the next, and 2026-08-12 is
the registered WASDE day -- and ``b_20260813`` carries 31,610 in-scope rows stamped 2026-08.  So
once a month the new PSD file can be in the bucket before the sibling chain has registered its
partition.

THE ANSWER IS A BOUNDED WAIT, NOT A WEAKER RAISE.  ``jobs/batch/psd_silver_task.py``
(``wait_for_wasde_calendar``) re-reads the registered partitions every FIVE MINUTES for up to
NINETY MINUTES -- at most 18 get-partitions reads, no other call -- and then fails closed with
the stamp month and the newest registered month named.  Ninety minutes is measured against the
sibling chain's own shape (fetch -> bronze -> silver -> register is minutes of work starting in
the same cron minute), not chosen as a round number.  Past the bound the WASDE chain has
genuinely failed and psd_monthly SHOULD red: publishing PSD rows dated by a convention nobody
measured is the worse outcome.  A WASDE gate failure therefore still reds psd_monthly, by
design; sequencing the two DAGs is a scheduler change with its own blast radius and it is
NOT this lane's.

WHAT IS *NOT* HERE, AND WHY
---------------------------
No tfvars ``env`` block for the psd_monthly gate entry.  An earlier draft called that a required
edit on the belief that the gate ran without ``GRAPHRAG_NUMBERS_BACKEND=pg``.  MEASURED and
REFUTED: ``infra/terraform/modules/step_functions/main.tf:245-248`` hard-codes
``ContainerOverrides.Environment = [{GRAPHRAG_NUMBERS_BACKEND = "pg"}]`` on EVERY Gate task, and
``infra/terraform/modules/batch/silver_gate.tf:124-127`` supplies ``EVIDENCE_PG_DSN`` from Secrets
Manager on the gate job definition itself.  The Gate task reads only ``$.gate.jobdef`` /
``.queue`` / ``.command`` -- there is no ``env`` key in that schema, and no gate entry in any family
carries one -- so the block would have been read by NOTHING while consuming the one-change
terraform batch.  G13 is therefore a LIVE READ of the gate job's container description (R2), not a
tfvars edit.

ASCII-only output.
"""
from __future__ import annotations

import argparse
import ast
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

WIDE = "silver_psd"
LONG = "silver_psd_attributes"
CALENDAR_TABLE = "silver_wasde"

QUEUE = "leviathan-dev-queue-ondemand"
JD_PSD_SILVER = "leviathan-dev-psd-silver"
JD_GATE = "leviathan-dev-silver-gate"
JD_PUBLISHER = "leviathan-dev-silver-publisher-runner"
JD_KANIKO = "leviathan-dev-kaniko-build"
JD_WASDE_BRONZE = "leviathan-dev-wasde-bronze-modern"
JD_WASDE_SILVER = "leviathan-dev-wasde-silver"
JD_FLAT_SILVER = "leviathan-dev-b3-flat-silver"

WORKER_REPO = "leviathan-dev-leviathan-worker"
ECR_URL = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{WORKER_REPO}"

WIDE_KEY = "silver/psd/part-000.parquet"
LONG_KEY = "silver/psd_attributes/part-000.parquet"
PSD_BASELINE = f"s3://{BUCKET}/cascade_census/rolling/psd_monthly/census.json"
WASDE_BASELINE = f"s3://{BUCKET}/cascade_census/rolling/wasde_monthly/census.json"

OLD_DIGEST = "sha256:5d25d886d7621cc1e6f199f656e75c8a7d10fc563a791394339a8bddce25df43"

KMS_ENV = [{"name": "LEVIATHAN_APPROVAL_MODE", "value": "kms"},
           {"name": "LEVIATHAN_KMS_KEY_ID", "value": "alias/leviathan-dev-publish-signer"}]

# --------------------------------------------------------------------------
# THE MEASUREMENTS THE GATES ASSERT AGAINST.
# Every one of these was reproduced LOCALLY through the SHIPPED transform over
# three of the nine live bronze partitions (scratchpad e_repro_wide.json /
# e_repro_long_*.json). That is stronger than an analytic projection and weaker
# than a shadow object: the shadow run consumes nine partitions and RE-DERIVES
# its own numbers. The gates assert the IDENTITIES and the SHAPES; the figures
# below are the expected READING, and a deviation is a question, not a red --
# except where marked RED.
# --------------------------------------------------------------------------
MEASURED = {
    "wide_rows_before": 247036,
    "wide_rows_after": 247294,
    "n_reprints_under_shipped_key": 258,
    "n_clamped": 0,
    "matched_keys": 247036,
    "canonical_only_keys": 0,
    "shadow_only_keys": 0,
    "value_differing_on_the_eight_mt_cols": 0,
    "su_ratio_differing": 0,
    "su_ratio_yoy_delta_differing": 0,
    "su_ratio_yoy_delta_nonnull": 211890,
    "su_ratio_yoy_delta_nonnull_frac": 0.8568,
    "mc_zero_rows_identical": 30715,
    "distinct_release_dates_before": 809,
    "distinct_release_dates_after": 439,
    "fabricated_only_dates": 708,
    # KEYED ON THE DISPOSITION THE ROW SHIPPED WITH, never on its release month:
    # 39 wide rows inside 2006-07/2008-10 (5 and 34) are World Markets and Trade
    # sheets on month_end_wmt, and a month-keyed counter absorbed them and read
    # 51,454 / 20.81%.
    "n_month_end_fallback_wide": 51415,
    "n_month_end_fallback_pct": 20.79,
    "n_month_end_fallback_wide_2006_07": 51259,
    "n_month_end_fallback_wide_2008_10": 156,
    "long_physical_before": 3397958,
    "long_physical_after": 3401565,
    "long_served_before": 1079487,
    "long_served_after": 1080307,
    "wasde_partitions_before": 472,
    "wasde_partitions_after": 474,
}

# G2's RED CEILING on the long table (L5). The measured growth is +0.076% served
# and +0.106% physical, and growth is strictly UPWARD by construction because a
# key gaining a column cannot merge rows. The mirror sits on an RDS instance with
# storage autoscaling OFF, so an unbounded growth is a SERVING OUTAGE, not a
# reading -- the ceiling exists to make that a stop rather than a surprise. It is
# set at 5.0%, roughly 65x the measured value: generous enough that nine
# partitions instead of three cannot trip it, tight enough that a broken vintage
# key (which multiplies rows, not fractions of a percent) always does.
LONG_GROWTH_CEILING_PCT = 5.0
LONG_SERVED_ROW_CEILING = int(MEASURED["long_served_before"] * (1 + LONG_GROWTH_CEILING_PCT / 100))

# G4's coverage ladder, cell-counted on (leviathan_slug, country, market_year).
# COUNTED ON THE NATURAL KEY INSTEAD -- which carries release_date -- a re-dated
# row reads as one loss plus one gain and the same ladder reports 216,461 gains at
# an asof where the true answer is 0. The instrument is the CELL.
G4_LADDER = [
    {"asof": "2010-01-01", "rows_before": 169490, "rows_after": 139052,
     "rows_pct": -17.96, "cells_gained": 23, "cells_lost": 30461},
    {"asof": "2015-01-01", "rows_before": 188779, "rows_after": 161084,
     "rows_pct": -14.67, "cells_gained": 47, "cells_lost": 27742},
    {"asof": "2020-01-01", "rows_before": 208206, "rows_after": 186707,
     "rows_pct": -10.33, "cells_gained": 150, "cells_lost": 21636},
    {"asof": "2024-01-01", "rows_before": 224047, "rows_after": 207723,
     "rows_pct": -7.29, "cells_gained": 158, "cells_lost": 16110},
    {"asof": "2026-01-01", "rows_before": 233407, "rows_after": 224692,
     "rows_pct": -3.73, "cells_gained": 672, "cells_lost": 7758},
    {"asof": "2026-09-01", "rows_before": 247036, "rows_after": 247294,
     "rows_pct": 0.10, "cells_gained": 0, "cells_lost": 0},
]

# The two months USDA published and silver_wasde has not ingested, with the days
# the manifest already records for them. This is a REPLAY of two named URLs, not a
# discovery scrape.
BACKFILL = {
    "2006-07": {"day": 12, "url_tail": "wasde-07-12-2006_China_rice_revision.pdf",
                "filename": "wasde0706.pdf", "wide_rows": 51259,
                "moves": "month-end 2006-07-31 -> 2006-07-12, 19 days EARLIER"},
    "2008-10": {"day": 28, "url_tail": "wasde-10-28-2008.pdf",
                "filename": "wasde1008.pdf", "wide_rows": 156,
                "moves": "month-end 2008-10-31 -> 2008-10-28, 3 days EARLIER"},
}
# G6's day-range assertion carries a DECLARED exception set, declared HERE and
# never discovered by the gate. 2008-10-28 is the ONLY day outside 8..14 in all
# 244 manifest months 2006+, and the manifest's own dedup keeps the LATEST release
# per month ("handles v2/v3 corrections", fetch_usda_wasde.py:24-27), so it may be
# a CORRECTION that displaced the primary October 2008 release. A correct backfill
# would therefore RED a bare 8..14 assertion -- the same defect class that made the
# first draft of G4 red a correct build.
DAY_RANGE_2006_PLUS = [8, 9, 10, 11, 12, 13, 14]
DECLARED_DAY_EXCEPTIONS_AFTER_BACKFILL = {"2008-10": 28}
SHUTDOWN_MONTHS = ["2013-10", "2019-01", "2025-10"]


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


def steps(run_id: str) -> list[tuple[str, list[str]]]:
    tar = f"psd_clock_context_{run_id}.tar.gz"
    tag = f"{run_id}-psd-clock"
    return [
        ("R0  RATIFY THE OWNER DECISIONS -- $0, no AWS. Nothing below is startable without them.", [
            "OD1  THE DAY RULE. E-day-B ships: the eight NAMED World Markets and Trade sheet codes",
            "     (111000, 114200, 223000, 240000, 571120, 585100, 612000, 711100) take month-END;",
            "     the other 39 mapped codes take the registered WASDE day. MEASURED: 439 distinct",
            "     release dates against 287 under one uniform day; 8.40% of rows carry a different",
            "     date under B than under A; the clamp fires ZERO times under BOTH, and the WM&T-8",
            "     minimum headroom is 13 days over 333,744 stamped rows.",
            "     THE SET IS A LITERAL. A cadence threshold captures FIFTEEN codes, fires the clamp",
            "     160 times (64/40/56 per snapshot) and produces a minimum gap of -18 days. Three of",
            "     the seven extra codes (224200 butter, 224400 NFDM, 230000 WMP) are dairy siblings",
            "     of set members with the IDENTICAL {7,12} cadence, so NO threshold can separate them.",
            "OD6  THE TWO WASDE PARTITIONS (R3b). Downloading two files is an explicit-permission",
            f"     action even though both URLs are already in configs/sources/usda_wasde_manifest.yaml:",
            f"     {json.dumps(BACKFILL, indent=6)}",
            "     It removes 51,415 of 247,294 served rows (20.79%) from the month-end FALLBACK.",
            "     The 39 rows in those months that stay on month-end are WM&T sheets, which never",
            "     rode the WASDE day in the first place -- the backfill cannot and must not move them.",
            "     IF DECLINED: E still ships, both cards carry the 20.79% figure in figures, the",
            "     counter and the month SET are gate readings, and the two partitions are docketed",
            "     with a date. R3b and G15 are then SKIPPED and G6 keeps two uncovered months.",
            "OD8  THE BYTE-IDENTITY SPLIT, and it must be ratified BEFORE the arm, because there is",
            "     no flag under which E both lands and prints the old date.",
            "     PINNED (flag-off identical): the eight _mt value columns; su_ratio;",
            "     su_ratio_yoy_delta; the 63-slug roster; the 30,715 month_code-0 rows; and the",
            "     FOUR-COUNT JOIN on (slug, country, market_year, wasde_release_month) --",
            "     247,036 matched / 0 canonical-only / 0 shadow-only / 0 value-differing.",
            "     DECLARED (the intended delta): every release_date string on a post-2006 row; the",
            "     freshest psd knowledge date; the 809 -> 439 date collapse with 708 fabricated-only",
            "     dates disappearing; the coverage ladder at six asofs with its cell gains and",
            "     losses; the '[known ...]' text on EVERY psd citation; the staleness-clause flips;",
            "     and the long table's row count.",
            "OD15 STEP 13's COMPARATOR -- RATIFIED AS THE LATEST-VINTAGE REDUCTION.",
            "     Each (slug, country, calendar-month, market_year) group reduces to its LATEST",
            "     release_date; the diff is taken across adjacent MARKETING YEARS there; a",
            "     superseded vintage carries NULL. MEASURED: BYTE-IDENTICAL to the live canonical --",
            "     0 differing of 247,036 joined keys, non-null unchanged at 211,890.",
            "     THE ALTERNATIVE WAS MEASURED AND REFUSED. The strict same-cycle rule (MY(n) at",
            "     calendar year cy against MY(n-1) at cy-1) is the honest reading of the card's old",
            "     'apples-to-apples vintages' sentence, but on a BULK-UNION table it finds a partner",
            "     for only 14.2% of live-su rows: non-null falls 211,890 -> 33,583 (-84.2%), 178,370",
            "     rows go NULL -- and 13.58% non-null is BELOW the 0.6 min_nonnull_frac_overrides",
            "     floor that configs/silver/tables/silver_psd.yaml declares and that",
            "     jobs/audit/silver_rebuild_gate.py's value-census stage measures on EVERY gate run.",
            "     It would RED THE PROMOTE. The card text is re-authored instead, and the dense",
            "     same-cycle series is a property of a per-release archive table, not of this one.",
        ]),

        ("R1  BUILD E LOCALLY, SUITE GREEN -- $0, no AWS. `--step CHECK` RUNS these.", [
            "python -m pytest tests/unit/test_psd_clock.py tests/unit/test_transforms_psd_silver.py "
            "tests/unit/test_psd_attributes_long.py tests/unit/test_batch_psd_silver_task.py "
            "tests/unit/test_batch_psd_attributes_silver_task.py "
            "tests/unit/test_psd_slug_map_widening.py tests/unit/test_complex_map.py "
            "tests/unit/test_numbers_parity_prereq.py tests/unit/test_psd_vintage_features.py -q",
            "python -m leviathan.graphrag.config_check          # must exit 0",
            "python scripts/silver/gen_registry_from_baseline.py --check   "
            "# must print 'registry check OK'",
            "python scripts/silver/gen_wasde_release_calendar.py --check   "
            "# the BANKED fixture is self-consistent",
            "python -m pytest tests/unit -q                     # the FULL suite, exact counts",
            "python scripts/ops/psd_clock_runbook.py --step CHECK",
            "# THE LOCAL REPRODUCTION, on three banked bronze snapshots, through the SHIPPED code:",
            f"#   {json.dumps(MEASURED)}",
            "",
            "A DELIVERY CONDITION, NOT A SURPRISE: tests/unit/silver/test_f091_source_universe_lint.py",
            "is RED on the working tree until this lane commits. Its census pins are the POST-COMMIT",
            "values by the file's own rule (the census is re-derived over the COMMITTED producer",
            "files, and a new producer 'enters this pin in the commit that adds it'), and",
            "src/leviathan/transforms/bronze_to_silver/psd_clock.py is on disk and not yet in",
            "`git ls-files`. A CONCURRENT LANE (pink sheet vintages) folded its own delta onto the",
            "SAME constants mid-build, so the pins now only reconcile when BOTH lanes commit -- that",
            "is a COMMIT-ORDER DEPENDENCY and it belongs on the flip checklist. VERIFY, do not",
            "assume: after the commit re-run that module and expect 0 failed; if the other lane has",
            "not landed, its refusal-registry assertion is the one still short and it is NOT this",
            "lane's to fix.",
        ]),

        ("R2  IMAGE AND REPIN -- the DIGEST-PINNED-JOBDEF LAW. psd_clock.py exists in NO image, and "
         "leviathan-dev-psd-silver is pinned BY DIGEST, so every submit below is a missing-module "
         "failure until this lands.", [
            "git commit on main, fast-forward push.",
            f"python scripts/ops/make_worker_context_tar.py --out {tar} --ref HEAD",
            "# it REFUSES on a dirty COPY set (tracked content, not `git status` -- this tree prints "
            "phantom M's after a commit) and overlays the gitignored configs/graphrag subtree.",
            "# configs/graphrag IS GITIGNORED: the numbers-card curation rides the config mirror / "
            "image tar, never a commit. configs/silver and configs/features are NOT gitignored.",
            f"aws s3 cp {tar} s3://{BUCKET}/build_contexts/{tar}",
            f"cat > kaniko_psd_overrides.json <<'JSON'\n  " + json.dumps({"command": [
                "--context", f"s3://{BUCKET}/build_contexts/{tar}",
                "--dockerfile", "docker/leviathan_worker/Dockerfile",
                "--destination", f"{ECR_URL}:{tag}",
                "--build-arg", "BUILD_GIT_COMMIT=<HEAD sha>"]}) + "\n  JSON",
            f"MSYS_NO_PATHCONV=1 aws batch submit-job --job-name kaniko-psd-clock "
            f"--job-queue {QUEUE} --job-definition {JD_KANIKO} "
            f"--container-overrides file://kaniko_psd_overrides.json --query jobId --output text",
            "# ~3 min in-region. READ THE KANIKO LOG FOR THE PUSHED DIGEST -- never infer it.",
            f"aws ecr describe-images --repository-name {WORKER_REPO} "
            f"--image-ids imageTag={tag} --query 'imageDetails[0].imageDigest' --output text",
            "# THE SMOKE, before anything trusts the image: import the new module and read BOTH the "
            "exit code AND the clock counters.",
            _submit("psd-clock-smoke", JD_PSD_SILVER, [
                "-c",
                "import importlib;"
                "m=importlib.import_module('leviathan.transforms.bronze_to_silver.psd_clock');"
                "print('MONTH_END_CODES', sorted(m._PSD_MONTH_END_CODES));"
                "import jobs.batch.psd_silver_task as t;"
                "cal=t.wasde_release_calendar('us-east-1');"
                "print('CAL_MONTHS', len(cal), 'MAX', max(cal))"]),
            "# THEN the dry-run smoke on the real bronze, reading the counters:",
            _submit("psd-clock-dryrun", JD_PSD_SILVER,
                    ["-m", "jobs.batch.psd_silver_task", "--publish-mode", "dry-run"]),
            "# grep the log for the ONE machine-readable line: PSD_CLOCK_COUNTERS {...}",
            f"# BUMP psd_silver_image_digest in infra/terraform/envs/dev/variables.tf:322-345 from",
            f"#   {OLD_DIGEST}",
            "#   to the digest kaniko printed. NOTHING ELSE RIDES THIS TERRAFORM BATCH.",
            "python scripts/ops/check_ecr_pinned_digests.py",
            "terraform -chdir=infra/terraform/envs/dev apply "
            "-target=module.batch.aws_batch_job_definition.psd_silver",
            f"aws batch describe-job-definitions --job-definition-name {JD_PSD_SILVER} "
            "--status ACTIVE --query 'jobDefinitions[-1].[revision,containerProperties.image]' "
            "--output json",
            "# CONFIRM the NEW revision number. A digest-pinned jobdef makes a push a NO-OP, so the "
            "repin IS the deploy.",
            "# G13 -- THE GATE CAN ACTUALLY RUN, read LIVE rather than assumed:",
            f"aws batch describe-job-definitions --job-definition-name {JD_GATE} --status ACTIVE "
            "--query 'jobDefinitions[-1].containerProperties.[environment,secrets]' --output json",
            "# EXPECT: secrets carries EVIDENCE_PG_DSN (silver_gate.tf:124-127). And the Gate STATE "
            "hard-codes GRAPHRAG_NUMBERS_BACKEND=pg in ContainerOverrides.Environment "
            "(step_functions/main.tf:245-248), so BOTH Branch-A preconditions are already supplied "
            "and NO tfvars env block is needed or possible -- the Gate task schema has no env key.",
        ]),

        ("R3  PRE-REBUILD CANONICAL COPY -- the ONLY way back. write_mode is overwrite with NO "
         "per-partition rollback: each table is one object.", [
            f"aws s3 cp s3://{BUCKET}/{WIDE_KEY} "
            f"s3://{BUCKET}/rollback/psd_clock_{run_id}/psd_part-000.parquet",
            f"aws s3 cp s3://{BUCKET}/{LONG_KEY} "
            f"s3://{BUCKET}/rollback/psd_clock_{run_id}/psd_attributes_part-000.parquet",
            _head(WIDE_KEY),
            _head(LONG_KEY),
            "# RECORD BOTH sha256s in the dossier, and dump the pg mirror row counts for both "
            "tables BEFORE anything moves:",
            "psql \"$EVIDENCE_PG_DSN\" -c \"select 'silver_psd' t, count(*) from "
            "leviathan_dev.silver_psd union all select 'silver_psd_attributes', count(*) from "
            "leviathan_dev.silver_psd_attributes;\"",
        ]),

        ("R3b THE WASDE BACKFILL (OD6) -- STRICTLY BEFORE R4. It is a two-URL MANIFEST REPLAY, not "
         "a discovery scrape: configs/sources/usda_wasde_manifest.yaml already holds both months, "
         "and over the 242 shared months 2006+ its release_date day and the registered partition "
         "day disagree on ZERO.", [
            "# --dry-run FIRST, and READ THE PRINTED KEYS. The CLI has --year-from/--year-to/--fmt/"
            "--limit/--skip-existing-s3/--dry-run and NO MONTH FILTER, so a year filter reaches up "
            "to twelve entries and --skip-existing-s3 (keyed on the source_url in the raw_meta "
            "sidecar) is what reduces it to the missing ones.",
            "python jobs/ingest/fetch_usda_wasde.py --year-from 2006 --year-to 2006 --fmt pdf "
            "--skip-existing-s3 --dry-run",
            "python jobs/ingest/fetch_usda_wasde.py --year-from 2008 --year-to 2008 --fmt pdf "
            "--skip-existing-s3 --dry-run",
            "# IF ANY MONTH OTHER THAN 2006-07 / 2008-10 APPEARS AS A FETCH RATHER THAN A SKIP: "
            "STOP. Something else is missing and this step's scope has changed.",
            "# DO NOT pass --discover (it re-scrapes 70 esmis pages and REWRITES the manifest) and "
            "DO NOT pass --save-manifest (operator-only; the scheduled container's filesystem is "
            "ephemeral). The manifest is already correct.",
            "python jobs/ingest/fetch_usda_wasde.py --year-from 2006 --year-to 2006 --fmt pdf "
            "--skip-existing-s3",
            "python jobs/ingest/fetch_usda_wasde.py --year-from 2008 --year-to 2008 --fmt pdf "
            "--skip-existing-s3",
            "# VERIFY THE PRIMARY BEFORE REGISTERING. 2008-10-28 is the ONLY day outside 8..14 in "
            "244 manifest months 2006+, and the manifest keeps the LATEST release per calendar "
            "month, so a v2/v3 correction can DISPLACE a primary. Read the fetched document's own "
            "header date and compare it with the manifest entry; if they disagree the registered "
            "day is a DECLARED choice recorded here, never a silent one.",
            _submit("wasde-bronze-backfill", JD_WASDE_BRONZE,
                    ["jobs/batch/wasde_bronze_modern_task.py"]),
            _submit("wasde-silver-backfill", JD_WASDE_SILVER,
                    ["jobs/batch/wasde_silver_task.py"]),
            "# G15 -- THE BACKFILL LANDED AND CHANGED NOTHING ELSE:",
            f"#   (a) registered partition count {MEASURED['wasde_partitions_before']} -> "
            f"{MEASURED['wasde_partitions_after']}, and the two new release_date values are exactly "
            "the VERIFIED primary days.",
            f"#   (b) the three shutdown months {SHUTDOWN_MONTHS} are STILL absent.",
            "#   (c) sha256 unchanged on EVERY pre-existing silver_wasde part file.",
            f"#   (d) the registered day set over 2006+ is {DAY_RANGE_2006_PLUS} plus the DECLARED "
            f"exception set {DECLARED_DAY_EXCEPTIONS_AFTER_BACKFILL}.",
            "#   (e) a get-partitions reconcile returns clean.",
            "python scripts/silver/reconcile_registered_partitions.py",
            "# (f) THE MIRROR. silver_wasde is P1_TABLES too, and wasde_monthly gates it on the SAME "
            "cron window as psd_monthly against its OWN rolling baseline. Two partitions land -> the "
            "next wasde_monthly fire would red on the row-count move against a stale baseline, and "
            "the wasde card would serve a mirror that does not hold the backfilled months. So the "
            "re-sync and the re-mint happen HERE, inside this step, not at R7:",
            _submit("wasde-pg-reload", JD_GATE,
                    ["-m", "jobs.utils.load_pg_numbers", "--tables", CALENDAR_TABLE]),
            _submit("wasde-census-advance", JD_GATE,
                    ["-m", "jobs.audit.advance_rolling_census", "--asof", "<asof>",
                     "--dest-uri", WASDE_BASELINE]),
            "psql \"$EVIDENCE_PG_DSN\" -c \"select count(*) from leviathan_dev.silver_wasde where "
            "release_date in ('2006-07-12','2008-10-28');\"   # EXPECT > 0",
            "# ROLLBACK for this step alone: de-register the two partitions, delete their objects, "
            "reload the mirror and re-mint the baseline. silver_wasde is partitioned and registered, "
            "so this is additive and reversible -- unlike E.",
        ]),

        ("R4  SHADOW RUN, BOTH TABLES -- on the SHIPPED jobdef (Fargate 2 vCPU / 16,384 MB; "
         "timeout 3,600 s; NO retry -- infra/terraform/modules/batch/main.tf:3967-3970 and "
         ":3990-3995).", [
            _submit("psd-silver-shadow", JD_PSD_SILVER,
                    ["-m", "jobs.batch.psd_silver_task", "--publish-mode", "shadow",
                     "--force-overwrite"]),
            _submit("psd-attributes-shadow", JD_PSD_SILVER,
                    ["-m", "jobs.batch.psd_attributes_silver_task", "--publish-mode", "shadow",
                     "--force-overwrite"]),
            "# READ the peak RSS and EVERY counter on the PSD_CLOCK_COUNTERS line:",
            "#   n_stamp_constancy_violations (EXPECT 0, per INPUT snapshot -- it is asserted "
            "per frame and never on the concat: 0 per banked snapshot but 3,290 of 142,015 "
            "sheet-cells across three concatenated, and this task feeds every distinct-ETag "
            "partition from a bucket that holds nine)",
            "#   n_month_end_fallback / n_month_end_fallback_wide / month_end_fallback_months",
            "#   day_dispositions (the four named conventions, counted)",
            "#   n_clamped / n_clamped_to_wasde_day / n_clamped_to_ingest / "
            "n_clamped_cross_month_declined (EXPECT 0 / 0 / 0 / 0). The last one is the clamp "
            "REFUSING to move a date out of its own stamp month, which would break P21.",
            "#   day_dispositions is POST-CLAMP: if the clamp fired, its three names appear here "
            "and the pre-clamp convention does not.",
            "#   n_step10_collapsed, n_reprints_under_shipped_key (G1's number),",
            "#   n_step13_declined_absent_comparator, n_distinct_release_dates,",
            "#   n_calendar_months, max_calendar_month",
        ]),

        ("R5  THE BLOCKING GATES on the SHADOW objects: G1, G2, G4, G5, G6, G13, G15. "
         "G3 is NOT here -- see R7c.", [
            "G1  FLAG-OFF VALUE IDENTITY, re-derived in the run. Join the shadow object against the "
            "live canonical on (leviathan_slug, country, market_year, wasde_release_month) -- NEVER "
            "release_date, which E moves on 87.5% of rows and on which the join matches 12.47% of "
            "which 30,715 of 30,833 are the month_code-0 mass. REPORT FOUR COUNTS, never a bare "
            "pass: matched keys, canonical-only, shadow-only, and matched keys differing on the "
            "eight _mt columns.",
            "    REDUCE THE SHADOW SIDE TO EACH KEY'S LATEST release_date BEFORE THE JOIN. This is "
            "not a convenience, it is what makes the comparison well-defined: E's whole point is "
            "that 258 keys now carry TWO shadow rows (an older vintage the retired latest-only key "
            "was deleting), so on this four-column key the join is 1:MANY and 'the' shadow value "
            "does not exist. The canonical side was produced by that latest-only key, so the "
            "comparable shadow row is the LATEST-release_date one; the older vintage is the "
            "DECLARED delta and is counted by the row-delta identity below, never by this join. "
            "MEASURED on three banked snapshots: WITHOUT the reduction the literal join reports 224 "
            "matched keys differing on at least one _mt column (beginning 13 / production 98 / "
            "imports 127 / exports 71 / ending 33 / consumption 215; su_ratio 216; "
            "su_ratio_yoy_delta 257) -- every one of them an older vintage compared against a newer "
            "one, i.e. the instrument reading its own subject as a defect. WITH the reduction: 0, "
            "on all ten columns. A G1 that reds on a correct build is not a gate.",
            f"    EXPECTED (measured on three snapshots; the shadow run re-derives its own): "
            f"{MEASURED['matched_keys']} / {MEASURED['canonical_only_keys']} / "
            f"{MEASURED['shadow_only_keys']} / "
            f"{MEASURED['value_differing_on_the_eight_mt_cols']}",
            "    THE IDENTITY: row_count_after == row_count_before + n_reprints_under_shipped_key, "
            "BOTH from THIS run's counters. n_reprints is minted at step 11.5 BEFORE the new "
            "assertion runs and it is the ONLY number a post-E run can produce for this: the "
            "rotation that made the 247,036 baseline is deleted, and step 10's collapse count is "
            "three orders of magnitude away (3,291,515 against 258).",
            "    RED: a canonical-only key (the producer LOST a fact -- a roster or filter "
            "regression); a shadow-only key (it INVENTED one); a matched key differing on any _mt "
            "column (a pivot, unit factor or remap moved); row_count delta != n_reprints (something "
            "other than the re-key moved rows). A key carrying MORE THAN TWO shadow rows is a third "
            "vintage of one calendar month -- not impossible on nine partitions, but COUNTED and "
            "NAMED, never absorbed.",
            "",
            "G2  THE DECLARED DATE DELTA, both tables. Before/after: the freshest psd knowledge "
            "date; the distinct release_date count; the histogram of how far each date moved; the "
            "month_code-0 mass proven identical; su_ratio_yoy_delta's non-null count and its "
            "differing-row count; and the LONG table's served AND physical row counts.",
            f"    EXPECTED: dates {MEASURED['distinct_release_dates_before']} -> "
            f"{MEASURED['distinct_release_dates_after']} of which "
            f"{MEASURED['fabricated_only_dates']} fabricated-only dates disappear; clamp 78,738 -> "
            f"{MEASURED['n_clamped']}; {MEASURED['mc_zero_rows_identical']} month_code-0 rows "
            f"identical; su_ratio_yoy_delta non-null UNCHANGED at "
            f"{MEASURED['su_ratio_yoy_delta_nonnull']} "
            f"({MEASURED['su_ratio_yoy_delta_nonnull_frac']:.4f} of rows, above the 0.6 floor); "
            f"long served {MEASURED['long_served_before']} -> {MEASURED['long_served_after']} "
            f"(+{MEASURED['long_served_after'] - MEASURED['long_served_before']}, +0.076%), long "
            f"physical {MEASURED['long_physical_before']} -> {MEASURED['long_physical_after']} "
            f"(+{MEASURED['long_physical_after'] - MEASURED['long_physical_before']}, +0.106%).",
            f"    RED CEILING ON THE LONG TABLE (L5): served row growth above "
            f"{LONG_GROWTH_CEILING_PCT}% -- i.e. more than {LONG_SERVED_ROW_CEILING} served rows -- "
            f"STOPS THE PROMOTE. WHY A CEILING AT ALL: the mirror sits on an RDS instance with "
            f"storage autoscaling OFF (jobs/utils/load_pg_numbers.py:65-77), so unbounded growth is "
            f"a SERVING OUTAGE, not a reading. WHY 5%: it is ~65x the measured +0.076%, so nine "
            f"partitions instead of three cannot trip it, while a broken vintage key multiplies "
            f"rows and always does.",
            "    INVARIANTS: every moved date EXISTS in the registered WASDE calendar or is a "
            "month-end day in one of the COUNTED fallback months; no date moves LATER than its "
            "row's bronze ingest date; the long table's row count moves in ONE direction only, UP "
            "(a key gaining a column cannot merge rows).",
            "    NOT AN INVARIANT, A MEASURED EXPECTATION: distinct_release_dates_after <= before. "
            "That is arithmetic about THIS substrate (439 against 809, bounded by covered "
            "stamp-months times day conventions), not a law about the two clocks.",
            "",
            "G4  THE COVERAGE LADDER. Rows AND distinct SERVING CELLS visible at a FIXED asof set, "
            "before and after, on BOTH tables, using the shipped as-of guard (release_date <= asof; "
            "src/leviathan/graphrag/numbers/query.py:484 is the FLAT branch these tables take, :483 "
            "is the vintage-partition branch).",
            "    THE INSTRUMENT IS THE CELL: gained and lost are counted on "
            "(leviathan_slug, country, market_year). Counted on the natural key -- which CARRIES "
            "release_date -- a re-dated row reads as one loss plus one gain and the instrument "
            "reports 216,461 gains at an asof where the true answer is 0.",
            f"    EXPECTED, and IDENTICAL with or without the OD6 backfill at these six asofs: "
            f"{json.dumps(G4_LADDER, indent=6)}",
            "    A GAIN IS EXPECTED, NOT AN ALARM: the rotation was LATE on 2.4% of stamped rows, "
            "so those cells legitimately arrive. A gained cell had EVERY fabricated date strictly "
            "after asof and some honest date on or before it -- provable by construction from the "
            "visibility definition.",
            "    RED: a NET gain (rows_delta > 0) at any of these six asofs before the newest real "
            "release. DECLARED EXCEPTIONS, and the only two: an asof INSIDE 2006-07 on or after the "
            "12th (+51,259 rows) or inside 2008-10 on or after the 28th (+156), once the OD6 "
            "backfill lands -- both correct, both EARLIER by construction, and neither reachable "
            "from the chartered asof set.",
            "",
            "G5  THE STEP-13 AND STEP-14 CORRECTNESS PINS, on the shadow object.",
            "    (a) su_ratio_yoy_delta is NULL on every NON-LATEST vintage of a "
            "(slug, country, calendar-month, market_year) group, and elsewhere equals a "
            "re-computation over the one-vintage-per-year reduction. Measured expectation against "
            "the live canonical: 0 differing rows -- ON THE SAME LATEST-release_date REDUCTION G1 "
            "uses, and for the same reason. Compared row-for-row without it, 257 of the 258 "
            "two-vintage keys differ, because a NON-LATEST vintage carries NULL BY CONSTRUCTION "
            "while the canonical row it collides with carries the year-over-year move. That is the "
            "rule working, not a mismatch; reducing to the latest vintage is what asks the question "
            "the gate means to ask.",
            "    (b) n_step13_declined_absent_comparator is reported with the live-su row count as "
            "its denominator.",
            "    (c) the three *_revision columns are ordered by RELEASE DATE: verify on a "
            "calendar-wrapping marketing year (corn MY2024 -- calendar months 5..12 of 2024 then "
            "1..4 of 2025) that revision[k] = value(release k) - value(release k-1) in RELEASE "
            "order. A month-ordered sort inverts the sign for 38 of the 47 mapped codes and is "
            "invisible at the ~2.5% column density the contract's own 0.025 floors record.",
            "    (d) the count of (slug, country, calendar-month, market_year) groups holding TWO "
            "distinct honest release_dates is reported. MEASURED: 258 groups / 516 rows / 514 with "
            "a live su_ratio / 216 with DIFFERING su_ratios.",
            "",
            "G6  THE CALENDAR RECONCILE, against the LIVE registered silver_wasde partitions.",
            "    Report: n_calendar_months; n_psd_stamp_months; the stamp-months NOT covered and "
            "their row counts at bronze AND wide grain; n_month_end_fallback at both grains; the "
            "registered day set over 2006+; and the assertion that the three shutdown months "
            f"{SHUTDOWN_MONTHS} appear in NEITHER the calendar NOR the PSD stamp set.",
            f"    WITHOUT the backfill: {MEASURED['wasde_partitions_before']} partitions, day set "
            f"over 2006+ exactly {DAY_RANGE_2006_PLUS}, exactly two uncovered stamp-months "
            f"(2006-07 and 2008-10), {MEASURED['n_month_end_fallback_wide']} of "
            f"{MEASURED['wide_rows_after']} wide rows on the fallback "
            f"({MEASURED['n_month_end_fallback_pct']}%), split "
            f"{MEASURED['n_month_end_fallback_wide_2006_07']} / "
            f"{MEASURED['n_month_end_fallback_wide_2008_10']}. THE COUNTER IS DISPOSITION-KEYED: 39 "
            f"further wide rows in those two months are WM&T sheets on month_end_wmt and are NOT "
            f"fallback rows, which is why this is 51,415 and not the 51,454 a month-keyed count gives.",
            f"    WITH the backfill: {MEASURED['wasde_partitions_after']} partitions, ZERO "
            f"uncovered stamp-months, ZERO fallback rows, and the day set over 2006+ is "
            f"{DAY_RANGE_2006_PLUS} PLUS the DECLARED exception set "
            f"{DECLARED_DAY_EXCEPTIONS_AFTER_BACKFILL}.",
            "    THE EXCEPTION SET IS DECLARED IN THIS RUNBOOK BEFORE THE GATE RUNS, never "
            "discovered by it. A bare 8..14 assertion would RED a CORRECT backfill.",
            "    max(psd stamp month) <= max(calendar month), or the transform RAISED and the run "
            "is red by construction -- that raise is the ordering alarm and it is the ONLY raise "
            "the clock keeps.",
            "",
            "G13 THE GATE CAN ACTUALLY RUN -- read LIVE at R2, not asserted from tfvars.",
            "G15 THE WASDE BACKFILL LANDED AND CHANGED NOTHING ELSE -- see R3b (skipped if OD6 is "
            "declined).",
        ]),

        ("R6  OWNER WORD, THEN THE CANONICAL PROMOTE.", [
            "PRESENT, in figures and words: the G1 four-count table; the before/after date deltas; "
            "the ladder with its cell gains and losses; su_ratio_yoy_delta's coverage (unchanged); "
            "and the long table's measured growth against its declared ceiling.",
            "SAY THE HONEST HEADLINE: at the physical grain the eight value columns DO NOT MOVE. "
            "E re-dates 247,036 facts and recovers 258 vintages. It is a coverage and "
            "vintage-selection correction, not a value correction.",
            "ON --yes, and only then:",
            _submit("psd-silver-canonical", JD_PUBLISHER,
                    ["-m", "jobs.batch.psd_silver_task", "--publish-mode", "canonical",
                     "--force-overwrite"], KMS_ENV),
            _submit("psd-attributes-canonical", JD_PUBLISHER,
                    ["-m", "jobs.batch.psd_attributes_silver_task", "--publish-mode", "canonical",
                     "--force-overwrite"], KMS_ENV),
            "# shadow -> validate -> promote -> catalog, on the publisher-runner with the KMS "
            "self-mint. The wide table FIRST.",
        ]),

        ("R7  POST-PROMOTE RECONCILIATION -- THE SERVING HALF. Until this runs, the canonical "
         "objects hold honest dates and every answer still prints fabricated ones.", [
            "# WHY: silver_psd is jobs/utils/load_pg_numbers.py:56 P1_TABLES[0] and "
            "configs/silver/tables/silver_psd.yaml:175 consumers: both, so "
            "jobs/audit/silver_rebuild_gate.py:216-227 select_branch returns BRANCH_A; "
            "src/leviathan/graphrag/numbers/pgnumbers.py is the SERVE path and Athena is off it. "
            "A canonical promote alone changes NOTHING that serves.",
            _submit("psd-pg-reload", JD_GATE,
                    ["-m", "jobs.utils.load_pg_numbers", "--tables",
                     f"{WIDE},{LONG}"]),
            "# ORDER: silver_psd FIRST, then silver_psd_attributes. The wide table is what cascade "
            "reads; the long one is what the parity vintage cell reads. If the second fails the "
            "first is already serving honest dates and the failure is attributable.",
            "# load_table DROPs, CREATEs and COPYs inside ONE transaction (pg DDL is "
            "transactional), so readers keep the old rows until commit; ignore_prefixes=['_','.'] "
            "keeps the _shadow/ twin out of the count.",
            _submit("psd-census-advance", JD_GATE,
                    ["-m", "jobs.audit.advance_rolling_census", "--asof", "<asof>",
                     "--dest-uri", PSD_BASELINE]),
            "# Re-mint the psd_monthly rolling baseline from the POST-E canonical object. Until it "
            "is re-minted every monthly gate run reds on the row-count move.",
            "python scripts/silver/gen_registry_from_baseline.py       "
            "# regenerate both F010 contracts from a FRESH readiness baseline",
            "python scripts/silver/generate_ddls_from_registry.py",
            "# THEN, and only then, refresh the numbers cards (APPLY-THEN-REFRESH -- the card moves "
            "WITH the table and never ahead of it). Re-measure on the FIRST CANONICAL OBJECT:",
            "#   configs/graphrag/numbers/tables.yaml silver_psd.row_count (247,036 -> the measured "
            "value; locally projected 247,294)",
            "#   silver_psd_attributes.row_count (1,079,487 -> measured; locally projected "
            "1,080,307) and the '810 releases' figure, which is a count of FABRICATED dates",
            "# configs/graphrag is GITIGNORED: this curation rides the config mirror / image tar.",
        ]),

        ("R7a VERIFY BY A CARD-PATH READ, NEVER BY THE SYNC TOOL'S EXIT CODE. The pink-sheet "
         "ritual: an exit code proves the tool ran, not that the answer changed.", [
            _submit("psd-cardpath-verify", JD_GATE, [
                "-c",
                "import json;"
                "from leviathan.graphrag.numbers import cascade as C;"
                "r=C._world_su_ratio('corn_cbot', asof='<asof>');"
                "print('WORLD_SU', json.dumps(r, default=str))"]),
            "# ASSERT the returned freshness stamp is a date that EXISTS in the registered WASDE "
            "calendar (or is a declared month-end fallback day).",
            "# ASSERT a NumberQuery against each psd card returns an HONEST knowledge_date and that "
            "the printed citation carries the new '[known ...]' string "
            "(src/leviathan/graphrag/citations.py:1306-1311 prints it verbatim).",
            "# THE SHARPEST SINGLE CHECK -- the NEGATIVE one: assert that NO returned "
            "knowledge_date is a member of the 708 fabricated-only date set. That set is computable "
            "from this run's own before/after date lists, and a fabricated-only date coming back "
            "means the mirror did not reload.",
        ]),

        ("R7b RE-DERIVE THE BRANCH-A PARITY CELL -- BLOCKING, and it cannot be left to the gate.", [
            "# jobs/utils/numbers_parity.py:148-153 PSD_ATTR_VINTAGE_CELLS pins a "
            "silver_psd_attributes VINTAGE-FAN cell -- soybeans_cbot / United States / Crush at "
            "(MY1998, 2001-06-30), (MY2010, 2011-01-15) and (MY2010, 2026-07-01) -- and "
            "jobs/audit/silver_rebuild_gate.py:563-582 stage_parity runs it as a BRANCH-A GATE "
            "STAGE that E's own promote passes through.",
            "# ITS PREMISE IS THE RETIRED ROTATION'S ARITHMETIC, written out at :305-345 in the "
            "rotation's own words. MEASURED on the WIDE table over three banked snapshots -- a "
            "DIRECTION with a named limit, since the leg reads the LONG table -- the honest stamp "
            "for that MY2010 cell is 2014-11-10, so the mid-fan as-of has nothing to select.",
            "# AN EMPTY LEG IS A MATCH ON BOTH BACKENDS. It PASSES while proving nothing, and the "
            "file's own NON-VACUITY PRECONDITION note says the check is the report's per-leg lines, "
            "read once. So E can silently HOLLOW OUT a gate stage.",
            _submit("psd-parity-cell", JD_GATE,
                    ["-m", "jobs.utils.numbers_parity", "--tables", LONG]),
            "# RUN THE THREE LEGS AGAINST THE SHADOW OBJECT AT R5 IF POSSIBLE, re-confirm after the "
            "promote, and READ THE PER-LEG LINES. Re-derive the as-ofs so that (a) EVERY leg "
            "returns rows and (b) the two modern legs still select DIFFERENT vintages.",
            "# IF NO SUCH PAIR EXISTS on the honest axis for this cell, RE-CHOOSE THE CELL and "
            "RECORD WHY: 'the vintage fan collapsed' is a finding about the table, not about the "
            "test.",
            "# The comment block at :305-345 has already been re-authored in honest-clock words; "
            "the CELL ITSELF is what this step re-derives.",
        ]),

        ("R7c G3 -- THE RENDER-SURFACE SIZING DIFF. NOT blocking, and it runs AFTER the promote "
         "with the R3 rollback objects in hand.", [
            "# WHY IT CANNOT RUN EARLIER: there is no shadow read path. "
            "jobs/utils/load_pg_numbers.py:472 SCHEMA and "
            "src/leviathan/graphrag/numbers/pgnumbers.py:24 SCHEMA are MODULE CONSTANTS; load_table "
            "takes its S3 location from the Glue catalog, not from an argument; and the CLI accepts "
            "only --tables and --dry-run. A scratch-schema shadow load would need THREE new "
            "parameters on the loader that serves production, for a reading that can wait one step.",
            "# Run the fixed deck against the promoted table and diff the ANSWER TEXT against the "
            "pre-promote transcripts. COUNT: turns carrying at least one psd citation; psd "
            "citations whose printed '[known ...]' string changed; psd citations that gained or "
            "lost the 30-day staleness clause (citations.py:555-560 -- E moves the freshest psd "
            "stamp ~14 days EARLIER, so rows in the 17-to-30-day band cross into it); and any prose "
            "sentence that names a psd date.",
            "# EXPECT a NON-ZERO text diff, LARGER than the value diff. This gate produces the "
            "number the judged arm is SIZED from. It does not block the promote -- G1, G2, G4, G5, "
            "G6, G13 and G15 do.",
        ]),

        ("R8  RE-CUT THE FEATURE AND EDA LANES -- not blocking, and not optional either.", [
            "# src/leviathan/features/computations/psd_vintages.py is a RE-BASELINE, not a diff: "
            "every feature in that lane is DEFINED on the vintage axis and that axis was fabricated "
            "(809 invented dates against 439 real, 708 of them dates USDA never published; 97.4% of "
            "stamped rows early). Any model artefact or evaluation anchored to those features is "
            "anchored to a fiction and must be RE-CUT, never reconciled. Same for "
            "src/leviathan/model_datasets/psd_model_ready.py and psd_target_builder.py.",
            "# The EDA silver_psd battery: four charts are declared at "
            "src/leviathan/eda/reader_metadata.py:1545-1552 and ALL FOUR are keyed on release_date "
            "-- vintage_trajectory, stored_revisions (which reads a column whose SORT KEY changed), "
            "release_depth (whose expected depth moves 809 -> 439) and first_latest. The table "
            "descriptor at :208-211 ('one row is one PSD balance-sheet release vintage') becomes "
            "TRUE rather than aspirational. Re-anchor WITH the rebuild rather than discovering the "
            "reds afterwards.",
            "# configs/features/feature_sets.yaml:310 ('Current silver/psd does not retain true "
            "monthly PSD release history') stays TRUE after E and is re-authored only when a "
            "per-release archive lands. It is NOT an E edit.",
        ]),
    ]


# ---------------------------------------------------------------------------
# CHECK -- AWS-FREE preflight. Reads local files; runs the local test lanes.
# ---------------------------------------------------------------------------

_failures = 0


def _say(ok: bool, what: str, detail: str = "") -> None:
    global _failures
    if not ok:
        _failures += 1
    print(f"  [{'OK ' if ok else 'FAIL'}] {what}" + (f"  ({detail})" if detail else ""))


def _psd_wasde_crons() -> str:
    """The two schedule expressions, read from the RENDERED tfvars -- never quoted."""
    sched = json.loads((_REPO / "infra" / "terraform" / "envs" / "dev"
                        / "dag_schedules.auto.tfvars.json").read_text(encoding="utf-8"))
    dags = sched["dag_schedules"]
    return "psd_monthly %s / wasde_monthly %s" % (
        dags.get("psd_monthly", {}).get("cron", "ABSENT"),
        dags.get("wasde_monthly", {}).get("cron", "ABSENT"),
    )


def both_crons_are_the_same() -> bool:
    sched = json.loads((_REPO / "infra" / "terraform" / "envs" / "dev"
                        / "dag_schedules.auto.tfvars.json").read_text(encoding="utf-8"))
    dags = sched["dag_schedules"]
    a = dags.get("psd_monthly", {}).get("cron")
    b = dags.get("wasde_monthly", {}).get("cron")
    return bool(a) and a == b


def check() -> int:
    global _failures
    _failures = 0
    print("PSD HONEST-CLOCK PREFLIGHT -- local files only, no AWS, nothing mutated.\n")

    # 1. The clock module exists, is PURE, and its month-end set is the eight-member literal.
    from leviathan.transforms.bronze_to_silver import psd_clock as K
    _say(K._PSD_MONTH_END_CODES == frozenset(
        {111000, 114200, 223000, 240000, 571120, 585100, 612000, 711100}),
        "the month-end set is the EIGHT-member literal",
        ", ".join(str(c) for c in sorted(K._PSD_MONTH_END_CODES)))
    clock_src = (_REPO / "src" / "leviathan" / "transforms" / "bronze_to_silver"
                 / "psd_clock.py").read_text(encoding="utf-8")
    _say("boto3" not in clock_src and "s3" not in clock_src.split("\n")[0],
         "the clock is PURE -- no AWS, no S3, no module-level calendar")

    # 2. The four signature edits are keyword-only with NO DEFAULT.
    import inspect

    from leviathan.transforms.bronze_to_silver.usda_psd import (
        _compute_psd_release_dates,
        prepare_psd_combined_frame,
        transform_psd_bronze_to_silver,
    )
    from leviathan.transforms.bronze_to_silver.usda_psd_attributes import (
        transform_psd_attributes_bronze_to_silver,
    )
    for fn in (_compute_psd_release_dates, prepare_psd_combined_frame,
               transform_psd_bronze_to_silver, transform_psd_attributes_bronze_to_silver):
        p = inspect.signature(fn).parameters.get("calendar")
        _say(p is not None and p.kind is inspect.Parameter.KEYWORD_ONLY
             and p.default is inspect.Parameter.empty,
             f"{fn.__name__} takes a keyword-only `calendar` with NO DEFAULT",
             "missing" if p is None else str(p.default))

    # 3. calendar_year is REQUIRED, and the roster fence is EXPLICIT.
    from leviathan.transforms.bronze_to_silver.usda_psd import (
        _CLOCK_COUNTER_KEYS,
        _PSD_COMMODITY_TO_MYS,
        _PSD_COMMODITY_TO_SLUGS,
        _REQUIRED_COLS,
    )
    _say("calendar_year" in _REQUIRED_COLS, "calendar_year is a REQUIRED bronze column")
    _say(set(_PSD_COMMODITY_TO_SLUGS) == set(_PSD_COMMODITY_TO_MYS),
         "rule R1 holds: the slug map and the marketing-year map are ONE universe",
         f"{len(_PSD_COMMODITY_TO_SLUGS)} codes")
    wide_src = (_REPO / "src" / "leviathan" / "transforms" / "bronze_to_silver"
                / "usda_psd.py").read_text(encoding="utf-8-sig")
    _say("_assert_every_in_scope_code_has_a_marketing_year(combined)" in wide_src,
         "rule R1's fence is EXPLICIT -- the retired rotation used to enforce it by accident")
    # CODE, not prose: the module header quotes the retired mechanism on purpose, so
    # this is checked on the parse tree. Exactly ONE function may read the map.
    mys_readers = {
        node.name
        for node in ast.walk(ast.parse(wide_src))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for inner in ast.walk(node)
        if isinstance(inner, ast.Name) and inner.id == "_PSD_COMMODITY_TO_MYS"
    }
    _say(mys_readers == {"_assert_every_in_scope_code_has_a_marketing_year"},
         "the marketing-year map is a ROSTER fence, not a clock -- exactly one reader",
         ", ".join(sorted(mys_readers)) or "none")

    # 4. The long table's grain and the label-dupe fence.
    from leviathan.transforms.bronze_to_silver.usda_psd_attributes import _GRAIN_COLS
    _say("release_date" in _GRAIN_COLS,
         "the long companion's declared grain carries release_date", str(_GRAIN_COLS))
    long_src = (_REPO / "src" / "leviathan" / "transforms" / "bronze_to_silver"
                / "usda_psd_attributes.py").read_text(encoding="utf-8")
    _say("out.duplicated(subset=_GRAIN_COLS)" in long_src,
         "the label-dupe fence reads _GRAIN_COLS BY REFERENCE, so its key widened with the grain")

    # 5. The F010 contract agrees with the producer.
    import yaml
    contract = yaml.safe_load((_REPO / "configs" / "silver" / "tables"
                               / f"{LONG}.yaml").read_text(encoding="utf-8"))
    _say(contract["natural_key"] == list(_GRAIN_COLS),
         "the F010 natural_key equals the producer's declared grain",
         str(contract["natural_key"]))
    wide_contract = yaml.safe_load((_REPO / "configs" / "silver" / "tables"
                                    / f"{WIDE}.yaml").read_text(encoding="utf-8"))
    floor = wide_contract["min_nonnull_frac_overrides"]["su_ratio_yoy_delta"]
    _say(MEASURED["su_ratio_yoy_delta_nonnull_frac"] > floor,
         "su_ratio_yoy_delta clears its own contract floor under the ratified step-13 rule",
         f"{MEASURED['su_ratio_yoy_delta_nonnull_frac']:.4f} > {floor}")

    # 6. The banked calendar fixture, and the fence that keeps it a FIXTURE.
    banked = json.loads((_REPO / "tests" / "fixtures" / "wasde"
                         / "release_calendar.json").read_text(encoding="ascii"))
    _say(banked["n_partitions"] == MEASURED["wasde_partitions_before"],
         "the banked calendar carries the live registered partition count",
         str(banked["n_partitions"]))
    _say(set(banked["missing_months_2006_plus"])
         == set(SHUTDOWN_MONTHS) | set(BACKFILL),
         "the fixture declares BOTH gap classes and keeps them distinct",
         str(banked["missing_months_2006_plus"]))
    _say(banked["registered_days_2006_plus"] == DAY_RANGE_2006_PLUS,
         "every registered day over 2006+ is inside 8..14 -- the exception set is EMPTY today",
         str(banked["registered_days_2006_plus"]))
    offenders = [str(p.relative_to(_REPO)) for area in ("src", "jobs")
                 for p in (_REPO / area).rglob("*.py")
                 if "release_calendar.json" in p.read_text(encoding="utf-8", errors="ignore")]
    _say(not offenders,
         "NO runtime module reads the banked calendar -- a baked calendar red-stops psd_monthly "
         "every month", ", ".join(offenders) or "none")

    # 7. The counters the gate reads, and the task that emits them.
    from jobs.batch import psd_silver_task as T
    task_src = inspect.getsource(T)
    # The needle is the SQL, not the word: the reader's own docstring says "never
    # MSCK" on purpose, and a bare-word scan would call that a violation.
    _say("get_partitions" in task_src and "MSCK REPAIR" not in task_src.upper(),
         "the calendar is read via Glue get-partitions, never MSCK REPAIR "
         "(configs/silver/tables/silver_wasde.yaml:20-21 recovery_strategy)")
    for key in ("n_stamp_constancy_violations", "n_clamped", "n_reprints_under_shipped_key",
                "n_month_end_fallback_wide", "n_step13_declined_absent_comparator",
                "n_clamped_cross_month_declined"):
        _say(key in _CLOCK_COUNTER_KEYS, f"the gate can read {key}")

    # 7b. THE SAME-CRON RACE AND ITS BOUNDED WAIT. psd_monthly and wasde_monthly share
    #     cron(0 18 8-13) with no ordering dependency, and the clock fails closed on a
    #     stamp month newer than the newest REGISTERED silver_wasde partition. The wait
    #     is what keeps a self-resolving race off the fail-closed path; the BOUND is what
    #     keeps a genuinely broken sibling chain on it.
    _say(T._WASDE_WAIT_MAX_SECONDS == 90 * 60 and T._WASDE_WAIT_POLL_SECONDS == 5 * 60,
         "the WASDE-partition race has a BOUNDED wait -- 90 minutes, polled every 5",
         f"{T._WASDE_WAIT_MAX_SECONDS}s / {T._WASDE_WAIT_POLL_SECONDS}s")
    _say("wait_for_wasde_calendar(dfs, calendar, aws_region)" in task_src,
         "the wait is WIRED into main(), between the calendar read and the transform")
    _say(both_crons_are_the_same(),
         "the exposure is real and read from the rendered tfvars -- psd_monthly and "
         "wasde_monthly fire the SAME cron", _psd_wasde_crons())

    # 7c. THE CLAMP'S CROSS-MONTH REFUSAL. A clamp that moves release_date out of its own
    #     stamp month breaks P21 (release_date determines wasde_release_month), on which
    #     step 10's dedup key and the card's refusal to declare a vintage_tiebreak both
    #     rest. The refusal is a NAMED, COUNTED disposition, not a silent substitution.
    from leviathan.transforms.bronze_to_silver.psd_clock import (
        DISPOSITION_CLAMPED_CROSS_MONTH_DECLINED,
        DISPOSITION_CLAMPED_TO_INGEST,
        DISPOSITION_CLAMPED_TO_WASDE_DAY,
    )
    _say(len({DISPOSITION_CLAMPED_TO_WASDE_DAY, DISPOSITION_CLAMPED_TO_INGEST,
              DISPOSITION_CLAMPED_CROSS_MONTH_DECLINED}) == 3
         and "ingest_in_stamp_month" in wide_src,
         "the clamp takes the ingest date ONLY inside the stamp month, and DECLINES by name "
         "otherwise", DISPOSITION_CLAMPED_CROSS_MONTH_DECLINED)
    _say("disposition = disposition.mask(" in wide_src,
         "the clamp UPDATES the disposition, so day_dispositions is a POST-CLAMP reading")
    _say('.eq(DISPOSITION_MONTH_END_FALLBACK).sum()' in wide_src,
         "n_month_end_fallback_wide is DISPOSITION-keyed, not month-keyed "
         f"({MEASURED['n_month_end_fallback_wide']}, not 51454)")

    # 7d. G1 AND G5(a) NAME THE LATEST-VINTAGE REDUCTION. 258 keys carry two shadow rows,
    #     so the four-count join is 1:MANY without it and reds on a correct build (224
    #     differing, measured).
    g1_text = " ".join(c for title, cmds in steps("x") if title.startswith("R5")
                       for c in cmds)
    _say("REDUCE THE SHADOW SIDE TO EACH KEY'S LATEST release_date BEFORE THE JOIN" in g1_text,
         "G1 states the latest-release_date reduction before its four-count join")
    _say("ON THE SAME LATEST-release_date REDUCTION G1 uses" in g1_text,
         "G5(a) states the same reduction")

    # 8. The two backfill months are already in the manifest -- this is a REPLAY.
    manifest = yaml.safe_load((_REPO / "configs" / "sources"
                               / "usda_wasde_manifest.yaml").read_text(encoding="utf-8"))
    rows = [r for report in manifest["reports"].values() if isinstance(report, list)
            for r in report] if isinstance(manifest.get("reports"), dict) else []
    if not rows:
        rows = [r for v in manifest.values() if isinstance(v, list) for r in v
                if isinstance(r, dict)]
    by_month = {r.get("calendar_month"): r for r in rows if isinstance(r, dict)}
    for month, spec in BACKFILL.items():
        entry = by_month.get(month)
        _say(entry is not None and entry.get("release_date", "").endswith("%02d" % spec["day"]),
             f"the manifest already holds {month} at day {spec['day']} -- a REPLAY, not a scrape",
             (entry or {}).get("release_date", "ABSENT"))

    # 9. THE TERRAFORM FACTS G13 RESTS ON -- read, not assumed.
    sfn = (_REPO / "infra" / "terraform" / "modules" / "step_functions"
           / "main.tf").read_text(encoding="utf-8")
    _say('Name = "GRAPHRAG_NUMBERS_BACKEND", Value = "pg"' in sfn,
         "every Gate task already gets GRAPHRAG_NUMBERS_BACKEND=pg from the state machine")
    gate_tf = (_REPO / "infra" / "terraform" / "modules" / "batch"
               / "silver_gate.tf").read_text(encoding="utf-8")
    _say("EVIDENCE_PG_DSN" in gate_tf,
         "the gate job definition already supplies EVIDENCE_PG_DSN from Secrets Manager")
    tfvars = json.loads((_REPO / "infra" / "terraform" / "envs" / "dev"
                         / "dag_schedules.auto.tfvars.json").read_text(encoding="utf-8"))
    body = tfvars["dag_schedules"]["psd_monthly"]["input_json"]
    _say('\\\\\"env\\\\\"' not in body.split('gate\\\\\":{')[-1][:400],
         "the psd_monthly gate entry carries no env key -- the Gate task schema has none to read")
    variables = (_REPO / "infra" / "terraform" / "envs" / "dev"
                 / "variables.tf").read_text(encoding="utf-8")
    _say(OLD_DIGEST in variables,
         "the digest this runbook bumps FROM is still the pinned one", OLD_DIGEST[:19] + "...")

    # 10. THE RUNBOOK'S OWN DRY-RUN PROPERTY, asserted about itself on the PARSE TREE.
    #     A substring scan would flag the boto3 that appears inside the python -c strings this
    #     module PRINTS for the operator, so what is checked is what this module IMPORTS and
    #     what it SHELLS OUT to.
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    shelled: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in ("run", "check_output", "call", "Popen", "system"):
                shelled.add(name)
    _say(not (imported & {"boto3", "botocore"}),
         "this runbook imports NO AWS SDK -- every mutating command is printed, never called")
    _say(shelled <= {"run"},
         "the only subprocess entrypoint is the local-check runner",
         ", ".join(sorted(shelled)) or "none")

    print(f"\n{'CHECK OK' if not _failures else 'CHECK FAILED'}: {_failures} failure(s)")
    return 0 if not _failures else 1


# ---------------------------------------------------------------------------
# ROLLBACK -- printed, never executed.
# ---------------------------------------------------------------------------

def rollback() -> int:
    print("ROLLBACK -- FOUR LAYERS, AND THE ORDER MATTERS BECAUSE THE MIRROR IS WHAT SERVES.")
    print("Nothing below is executed by this script.\n")

    print("(i) CODE -- the digest is the deploy, so the digest is the rollback.")
    print(f"    psd_silver_image_digest back to {OLD_DIGEST}")
    print("    terraform apply, then RE-REGISTER the job definition and CONFIRM the revision.")
    print("    A push alone changes nothing: the jobdef is digest-pinned.\n")

    print("(ii) DATA (lane E) -- restore the R3 copies THROUGH THE SAME PUBLISHER.")
    print(f"    restore s3://{BUCKET}/rollback/psd_clock_<run_id>/psd_part-000.parquet "
          f"-> {WIDE_KEY}")
    print(f"    restore .../psd_attributes_part-000.parquet -> {LONG_KEY}")
    print("    THERE IS NO PARTIAL ROLLBACK: each table is ONE object and write_mode is overwrite.")
    print("    Verify both sha256s against the ones recorded at R3.\n")

    print("(iii) THE MIRROR -- and it comes AFTER the data, never before.")
    print(f"    load_pg_numbers --tables {WIDE},{LONG}")
    print("    Restoring the objects without reloading the mirror leaves the SERVE path on honest")
    print("    dates while the tables hold fabricated ones -- a worse state than either end.\n")

    print("(iv) THE BASELINES -- last, because they describe the state the first three restore.")
    print(f"    re-mint {PSD_BASELINE} from the restored canonical object.")
    print(f"    if R3b ran: de-register the two silver_wasde partitions, delete their objects,")
    print(f"    reload the silver_wasde mirror and re-mint {WASDE_BASELINE}.")
    print("    The WASDE backfill is ADDITIVE and REVERSIBLE (partitioned + registered), unlike E.")
    print("    THE RAW WASDE OBJECTS ARE NOT DELETED on a code problem: raw is immutable by")
    print("    contract and both files are real USDA releases the manifest already named.\n")

    print("    THE CARDS AND THE CONTRACTS: configs/graphrag rides the config mirror / image tar,")
    print("    so it rolls back with the image. configs/silver and configs/features ride the")
    print("    commit -- `git revert`, then re-run gen_registry_from_baseline.py and")
    print("    generate_ddls_from_registry.py.\n")

    print("    DO NOT re-run the monthly psd task out of band as part of any rollback: the next")
    print("    scheduled fire rebuilds from bronze with whatever image is pinned, which is exactly")
    print("    what step (i) decides.")
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
    ap = argparse.ArgumentParser(
        description="PSD honest-clock (lane E) runbook -- dry-run by construction; "
                    "nothing is mutated")
    ap.add_argument("--step", default="PRINT", choices=["PRINT", "CHECK", "ROLLBACK"] + stems)
    ap.add_argument("--run-id", default=f"{datetime.now(tz=timezone.utc):%Y%m%dT%H%M}")
    args = ap.parse_args(argv)
    if args.step == "CHECK":
        return check()
    if args.step == "ROLLBACK":
        return rollback()
    print_steps(args.run_id, None if args.step == "PRINT" else args.step)
    return 0


if __name__ == "__main__":
    sys.exit(main())
