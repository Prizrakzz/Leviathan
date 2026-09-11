#!/usr/bin/env python
"""CPC SOIL MOISTURE REPAIR + BACKFILL RUNBOOK -- prints the exact command for every step, and
RUNS the AWS-free checks a human cannot eyeball.  IT NEVER MUTATES ANYTHING.

    python scripts/ops/cpc_soil_repair_runbook.py                 # print every step
    python scripts/ops/cpc_soil_repair_runbook.py --list          # just the step names
    python scripts/ops/cpc_soil_repair_runbook.py --step R3       # print one step
    python scripts/ops/cpc_soil_repair_runbook.py --step CHECK    # RUN the offline preflight

DRY RUN BY CONSTRUCTION.  There is no ``--run``.  No code path here submits a Batch job, writes
S3, registers a job definition, applies terraform or downloads a file: every mutating command is
PRINTED for the operator to paste.  ``--step CHECK`` reads local files and runs local pytest only.

ASCII-only output (the owner's console is cp1252).  Chain commands with ``;`` -- PowerShell 5.1
has no ``&&``.

===============================================================================================
WHAT WAS BROKEN -- TWO DEFECTS, ONE IMAGE
===============================================================================================

DEFECT A -- the visible one: ``leviathan-dev-cpc-soil-to-raw`` exited 1 on EVERY fire.
``_trailing_month_holes`` expected ``today.day - 1`` days of the current month, i.e. a ONE-day
publication lag.  CPC publishes day D at about 17:53Z on D+1 (MEASURED 2026-09-11:
``GeoTIFF/w.20260909.tif`` Last-Modified "Thu, 10 Sep 2026 17:53:44 GMT";
``GeoTIFF/w.20260910.tif`` still 404 at 09:30Z), which lands AFTER the 08:00Z weather_daily fire
-- so the effective lag is TWO days and every run manufactured a phantom one-day hole.  The
2026-08-22 self-heal then reached for ``clim/w.2026.tif.tar.gz`` to close it.  That file does not
exist: ``clim/`` carries CLOSED years only (w.2000..w.2025 plus w.40ym; HEAD of the 2026 tarball =
404, HEAD of the 2025 tarball = 200, 86,244,454 bytes).  HTTPError 404, tenacity exhausted, exit 1,
in about 60 s, every run.  FAILED jobs are visible on 09-05, 09-06, 09-07 (twice), 09-08, 09-09,
09-10 and 09-11; 09-05 is the seven-day Batch retention floor, not the start.

DEFECT A COST NO DATA.  Raw is COMPLETE: 252 day-keys for 2026, Jan 1 .. Sep 9, which is exactly
the 252 ``w`` days the live GeoTIFF index lists.  The 2026-08-22 comment justifying the tarball
fallback -- "the live GeoTIFF directory is a ROLLING window" -- is measurably false; nothing rolls
off within the calendar year, and the daily path already re-attempts every listed day each run.

DEFECT B -- the one that actually lost the fifteen days.  ``cpc_raw_to_bronze_task.
_write_bronze_partition`` skipped an existing month partition on EXISTENCE alone, with no
freshness comparison -- unlike the bronze->silver leg above it, which has used the SILVER-V002
freshness-aware selector (``base_jobs.select_partitions_to_write``) since the CHIRPS stale-silver
fix.  So the current month froze at whatever day count it first had.  MEASURED on
``corn_cbot/us_corn_south_dakota/year=2026``: month=08 held 20 of 31 days written
2026-08-22T11:35:46Z, month=09 held Sep 1..5 written 2026-09-07T08:56:29Z -- while the job
SUCCEEDED on 09-08 and 09-09, read all 252 raw days both times, and declined to rewrite either.
Silver carried the freeze faithfully: max(date) 2026-09-05 over 101,254 rows.

THE WHITE_SUGAR ANOMALY, EXPLAINED.  A table-level ``count(distinct date)`` on silver reads 248 --
a complete Jan 1 .. Sep 5 run -- because white_sugar alone carried 31 August days.  Measured cause:
its five BRAZILIAN region partitions (br_sugar_goias, br_sugar_mato_grosso_do_sul,
br_sugar_minas_gerais, br_sugar_parana, br_sugar_sao_paulo) were ABSENT before 2026-09-07 and so
were written FRESH on 09-07T08:56Z, with every raw day then available.  A partition that does not
exist yet gets a complete month; a partition that already exists stays frozen.  That is the defect
stated twice, and it is why the aggregate hid it.

===============================================================================================
WHAT THE REPAIR IS
===============================================================================================

  jobs/batch/cpc_soil_to_raw_task.py
    - the current month's expectation is the PUBLISHED set (the live GeoTIFF index, read ONCE and
      handed to both the fetch window and the hole report), not the calendar.  A day CPC has not
      published is a STATED DECLINE, never a hole.
    - the tarball fallback is guarded BY YEAR: a current-year hole logs CURRENT-YEAR HOLE and is
      left to the daily path, which is its only possible remedy.  A closed-year hole (the January
      -> previous-December case) still pulls that year's tarball, unchanged.
    - the daily window is BOUNDED: published days minus the days raw already holds, from ONE
      paginated LIST instead of about sixty per-day head_object probes.  Interior gaps stay in the
      window on purpose -- a strict high-water mark would reopen the 0b16421b permanence trap.
    - the calendar fact is not deleted, only moved: UPSTREAM SHORT reports a settled month the
      PUBLISHER is short on, on its own line.  When the live index could not be read that fence has
      no statement to measure against, so it DECLINES OUT LOUD (UPSTREAM SHORT BLIND) rather than
      returning an empty result that reads like "nothing is short".
    - THE OUTAGE FLOOR (added at review).  Turning every per-day failure into a decline left the
      leg exiting 0 when it fetched NOTHING from a non-empty window -- SUCCEEDED on a vanished
      source directory, an egress break or a cert change.  That matters because the exit code is
      the ONLY instrument here: `aws logs describe-metric-filters --log-group-name /aws/batch/job`
      returns nothing, and BOTH weather alarms (leviathan-dev-freshness-sla-breach-weather,
      FreshnessLagDays > 3d, and leviathan-dev-freshness-breach-count-weather) read OK on 09-07 and
      09-08 while silver_cpc_soil was frozen at 2026-09-05 -- the "FreshnessLagDays blind to dead
      legs" hook, confirmed live.  So a window where every day DECLINED now raises
      DailyWindowOutage.  The instruments are all read FIRST (hole report, upstream fence, Done
      line) and the leg then exits nonzero.  A partial outage stays green: days reached are days
      carried forward.  A day S3 turned out to hold is NOT an outage -- only a declined download
      counts, which is why the per-day result is a tri-state and not a bool.
    - THE YEAR-BOUNDARY DAYS (added at review).  Dec 30 publishes on Dec 31 and Dec 31 on Jan 1,
      both AFTER the last 08:00Z fire that asks for that year, so neither ever reaches the daily
      path.  MEASURED: raw date=20251230 and date=20251231 exist but carry LastModified 2026-05-24
      -- five months late, by a hand `--year 2025`, never by the scheduled leg.  The report used to
      look back ONE month, so from February 1 that hole stopped being reported at all, months
      before the archive that could heal it is even published.  The previous December is now
      inspected ALL YEAR (one extra raw LIST per run); the opportunistic archive self-heal keeps
      its SEASON (through March -- w.2025 landed 2026-03-03), and outside it the hole stays
      reported under YEAR-BOUNDARY HOLE with the operator's exact command named.
    - THE PUBLISHER-STALL ALARM (added at review round 2).  Moving the expectation onto CPC's
      PUBLISHED SET is what killed the phantom hole -- and it is also what made a STOPPED publisher
      invisible.  Drive the round-1 code with the index frozen at tip 20260909 and raw complete to
      it: a run on 2026-09-12 exits 0 with zero warnings, and so does one on 2026-09-20, eleven
      days stale.  The hole report finds no deficit (we hold every published day), and the UPSTREAM
      SHORT fence skips September until it is settled past the lag -- MEASURED, its first word
      lands 2026-10-02, 23 days after the tip.  So the calendar is kept where it belongs: the
      published SET is the expectation for what raw must HOLD; the published TIP is measured
      against the CALENDAR for whether the source is still alive.  newest published day vs
      (today - _PUBLICATION_LAG_DAYS): >= 3 days behind is a WARNING, >= 7 is `PublisherStall` and
      a nonzero exit.  Drives: tip 20260909 with today 09-12 quiet, 09-14 WARNING, 09-18 RED, and
      tip = today-2 quiet.  Both thresholds are named constants beside the measured lag.  The DAG's
      fetch Map tolerates a failed cpc job (measured: SUCCEEDED executions 09-08/09/10 with this
      job FAILED inside them), so red is an alarm, never a chain break.
    - THE OUTAGE FLOOR IS NOW MEASURED AGAINST THE WINDOW (review round 2).  The steady-state
      window here is exactly ONE day, so "every day of a non-empty window declined" put the leg's
      exit code on one 875KB GET.  RED needs a window >= _OUTAGE_MIN_WINDOW_DAYS (2); a one-day
      total decline is SINGLE-DAY DECLINE, a stated WARNING.  That is honest because a stopped
      source is now caught against the calendar by the alarm above, and because a break that lasts
      into the next run widens the window past the floor.
    - THE HOLE LINE PRINTS ITS BASIS (review round 2).  It used to end "(expected = days CPC has
      PUBLISHED, not calendar days)" on every branch -- false on both calendar branches, and most
      misleading on a blind run, which is when an operator reads it hardest.  The basis is now a
      computed fact returned beside the figure.
    - the retry/timeout shape of both downloaders is UNCHANGED and pinned by test.
    - THE JANUARY EDGE, found while reasoning about the guard above rather than in production: a
      year CLOSING does not make its tarball exist (clim/w.2025.tif.tar.gz carries Last-Modified
      "Tue, 03 Mar 2026 23:03:20 GMT", about two months after 2025 ended), so from January to
      roughly March a previous-December hole finds no archive.  The un-repaired shape would have
      failed the whole leg there on exactly the September 404, three months later.  A 4xx on the
      OPPORTUNISTIC self-heal is now a stated decline (TARBALL NOT PUBLISHED) and the hole stands
      reported; the EXPLICIT ``--year`` backfill still dies loudly, because there an operator
      asked for that year and must not be told it worked.

  jobs/batch/cpc_raw_to_bronze_task.py
    - ``_bronze_is_stale``: rewrite when the newest RAW object feeding the month is newer than the
      bronze object.  Same rule as SILVER-V002, one layer down.  Absent => write; equal or newer
      => skip, so a benign no-op rerun stays a no-op (AV-12).  The freshness read is free: the
      ``head_object`` already had to happen and its response carries ``LastModified``.
    - THE SHRINK FLOOR (added at review round 2).  That rule is what makes a month partition
      rewritable, and a rewrite REPLACES: the new Parquet is whatever this run collected, so a run
      that read 5 of 30 raw days (throttling, a truncated LIST, a half-deleted raw prefix) would
      have written 5 rows over 30 and logged "Wrote bronze".  ``_rewrite_would_shrink`` declines
      that BY NAME (BRONZE REWRITE DECLINED, with the rule quoted into the line) and leaves the
      partition alone; the prior count comes from the companion ``_meta.json`` this same writer
      emits, and an unknown stands the floor down rather than blocking.  A decline is counted
      separately from a skip -- a skip means already correct, a decline means this run was stopped.
      ``--force_overwrite true`` names the overwrite and steps past the floor, which is what it is
      for.  GROWING is untouched: August's 20 -> 31 rewrite, the whole point of the repair, passes.

===============================================================================================
WHY THE BACKFILL NEEDS NO --force_overwrite -- MEASURED, NOT ASSUMED
===============================================================================================

Newest raw object per month (S3 LIST, 2026-09-11):

    2026-01 .. 2026-07   2026-08-22T08:52:52Z .. 08:53:03Z
    2026-08              2026-09-02T08:48:27Z
    2026-09              2026-09-11T08:47:12Z

Bronze partition mtimes (corn_cbot, representative):

    months 01-07         2026-08-22T11:31Z .. 11:35Z   -- NEWER than their raw: FRESH, skipped
    month 08             2026-08-22T11:35:46Z          -- OLDER than 09-02 raw: STALE, rewritten
    month 09             2026-09-07T08:56:29Z          -- OLDER than 09-11 raw: STALE, rewritten

Counted across all 31 commodities (one paginated LIST of
``bronze/weather/source=cpc_soil/``, 271,014 objects, 2026-09-11):

    2026-08   422 partitions STALE (will rewrite)    5 FRESH (will skip)
    2026-09   427 partitions STALE (will rewrite)    0 FRESH (will skip)

849 rewrites, 5 skips.  The five skips are white_sugar's Brazilian regions above -- already
complete, correctly left alone.  So step R4 is an ORDINARY run with no flag, and the fifteen days
return because the rule, not an operator, noticed.  ``--force_overwrite true`` would also work and
would additionally rewrite the seven settled months for no benefit; prefer the rule.

===============================================================================================
THE BLOCKER YOU CANNOT PASTE PAST -- THE WORKER-FLEET DIGEST
===============================================================================================

All three cpc jobdefs run ``local.worker_fleet_image`` =
``var.worker_fleet_image_digest`` (infra/terraform/envs/dev/variables.tf:371-435), live at
sha256:91104375... (2026-08-27 #4, commit d9af78ce), shared with nine other producer families:
chirps-bronze-to-silver, chirps-to-bronze-backfill, conab-xls-bronze, modis-ndvi-bronze-to-silver,
modis-ndvi-raw-to-bronze, nasa-power-backfill, usda-esr-bronze and the two other cpc legs.

A DIGEST-PINNED JOBDEF MAKES A PUSH A NO-OP.  This repair exists only in the tree until that
digest moves, and that variable's own standing law is "a worker-fleet digest move rides ONE
change, alone".  Three honest routes, R2 below; the choice is the owner's, not this runbook's.

===============================================================================================
NOT THIS LANE, BUT LOUDER THAN THIS ONE -- gold_weather_z IS STALE AT 2026-07
===============================================================================================

``gold_weather_z`` does NOT read silver_cpc_soil at all (jobs/batch/gold_weather_z_task.py reads
nasa_power and chirps; the registry declares consumers=[feature_layer] for silver_cpc_soil), so
none of the above contaminated it.  But it tips at 2026-07 for its own reasons: silver nasa_power
has 22 of 31 August days and silver chirps has NONE (max 2026-07-31), so
``weather_z._complete_months_only`` correctly refuses August.  gold_weather_z is a SERVED table
(numbers registry; state/lint YM_BOARD_CARDS; analogs declares ym_publication_lag_days=7 against a
42-day tip) and the silver_rebuild_gate passed on 09-07, 09-08 and 09-09 anyway.  Fixing cpc will
not move gold_weather_z one day.  Its own docket.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

REGION = "us-east-1"
BUCKET = "leviathan-dev-shahem-001"
ACCOUNT = "668891723125"
QUEUE = "leviathan-dev-queue-ondemand"

JD_TO_RAW = "leviathan-dev-cpc-soil-to-raw"                 # live rev 19, 0.5 vCPU / 1,024 MiB
JD_R2B = "leviathan-dev-cpc-soil-raw-to-bronze"             # live rev 20, 0.5 vCPU / 1,024 MiB
JD_B2S = "leviathan-dev-cpc-soil-bronze-to-silver"          # live rev 19, 2 vCPU / 4,096 MiB
JD_COMPACT = "leviathan-dev-weather-compact"
JD_GATE = "leviathan-dev-silver-gate"
JD_KANIKO = "leviathan-dev-kaniko-build"

WORKER_REPO = "leviathan-dev-leviathan-worker"
ECR_URL = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{WORKER_REPO}"
FLEET_DIGEST = "sha256:91104375a5af569def216da9a7eb0f8aa61dd43e3a121cf230e24e441aa3b7a6"
FLEET_VAR_LINE = "infra/terraform/envs/dev/variables.tf:371-435 (worker_fleet_image_digest)"

LANE_FILES = [
    "jobs/batch/cpc_soil_to_raw_task.py",
    "jobs/batch/cpc_raw_to_bronze_task.py",
    "src/leviathan/ingestion/weather/cpc_soil_moisture.py",
    "tests/unit/test_weather_fetch_trailing_months.py",
    "tests/unit/test_cpc_soil_ingestion.py",
    "tests/unit/test_weather_thin_contract_fetch.py",
    "tests/fixtures/cpc_soil/geotiff_index.sample.html",
    "tests/fixtures/cpc_soil/clim_index.sample.html",
    "tests/fixtures/cpc_soil/capture_notes.md",
    "scripts/ops/cpc_soil_repair_runbook.py",
]

DECKS = [
    "tests/unit/test_weather_fetch_trailing_months.py",
    "tests/unit/test_cpc_soil_ingestion.py",
    "tests/unit/test_weather_thin_contract_fetch.py",
    "tests/unit/test_weather_b2s_staging.py",
    "tests/unit/test_transforms_cpc_soil_silver.py",
    "tests/unit/test_weather_schema_pinned.py",
    "tests/unit/test_storage_paths.py",
    "tests/unit/test_fetch_modis_delta_window.py",
]

# The source pins the CHECK step asserts. Each names the defect a refactor would reopen.
SOURCE_PINS = [
    ("jobs/batch/cpc_soil_to_raw_task.py", "if hy >= current_year:",
     "the closed-year guard: without it a phantom current-month hole 404s the whole leg"),
    ("jobs/batch/cpc_soil_to_raw_task.py", "_PUBLICATION_LAG_DAYS = 2",
     "the MEASURED lag; 1 is what manufactured the phantom hole"),
    ("jobs/batch/cpc_soil_to_raw_task.py", "TRAILING-MONTH HOLE",
     "the loud instrument a silent skip never had"),
    ("jobs/batch/cpc_soil_to_raw_task.py", "CURRENT-YEAR HOLE",
     "the distinct line for the guarded case"),
    ("jobs/batch/cpc_soil_to_raw_task.py", "UPSTREAM SHORT",
     "the calendar fact, corrected onto its own line rather than deleted"),
    ("jobs/batch/cpc_soil_to_raw_task.py", "UPSTREAM SHORT BLIND",
     "that fence's stated decline when the live index is unreadable -- silence there would be "
     "worst exactly when an upstream problem is likeliest"),
    ("jobs/batch/cpc_soil_to_raw_task.py", "raise DailyWindowOutage(",
     "THE OUTAGE FLOOR: reaching NOTHING from a non-empty window is not a decline. Without it the "
     "leg reports SUCCEEDED on a dead source, and the exit code is the ONLY instrument here"),
    ("jobs/batch/cpc_soil_to_raw_task.py", "YEAR-BOUNDARY HOLE",
     "Dec 30/31 reach no path; the hole must stay visible past the archive self-heal season, with "
     "the operator's command named"),
    ("jobs/batch/cpc_soil_to_raw_task.py", "TARBALL NOT PUBLISHED",
     "the January edge: a year closing does not make its archive exist, and an opportunistic "
     "self-heal must never fail a leg whose real work already succeeded"),
    ("jobs/batch/cpc_soil_to_raw_task.py", "raise stall",
     "THE PUBLISHER-STALL ALARM: with the expectation moved onto CPC's published SET, a frozen "
     "index reads as a perfect run. Without this the leg exits 0 eleven days stale, and the only "
     "other fence speaks 23 days after the tip"),
    ("jobs/batch/cpc_soil_to_raw_task.py", "UPSTREAM STALL",
     "that alarm's stated reason, naming the tip, the distance and both thresholds"),
    ("jobs/batch/cpc_soil_to_raw_task.py", "PUBLISHER STALL BLIND",
     "and its decline when the index could not be read -- an instrument with nothing to measure "
     "must never be mistaken for a healthy one"),
    ("jobs/batch/cpc_soil_to_raw_task.py", "if len(targets) >= _OUTAGE_MIN_WINDOW_DAYS:",
     "the outage floor is measured against the WINDOW: the steady state is one day, and one "
     "failed 875KB GET must not be the leg's exit code"),
    ("jobs/batch/cpc_soil_to_raw_task.py", "SINGLE-DAY DECLINE",
     "what that one-day case says instead of going red -- loud today, red tomorrow if it lasts"),
    ("jobs/batch/cpc_soil_to_raw_task.py", "expected basis = %s",
     "the hole line PRINTS which yardstick produced the expectation; it used to assert 'days CPC "
     "has PUBLISHED' even on a blind run, where that is false"),
    ("jobs/batch/cpc_raw_to_bronze_task.py", "_rewrite_would_shrink(prior_rows, len(rows))",
     "THE SHRINK FLOOR: the freshness rule made a partition rewritable, and a rewrite REPLACES -- "
     "a run that read 5 of 30 raw days would otherwise overwrite 30 rows with 5"),
    ("jobs/batch/cpc_raw_to_bronze_task.py", "BRONZE REWRITE DECLINED (shrink floor)",
     "that floor declining BY NAME, with the rule quoted into the line"),
    ("jobs/batch/cpc_raw_to_bronze_task.py", "_bronze_is_stale(bronze_mtime, raw_max_mtime)",
     "the freshness rule; existence-only skip is what froze August at 20/31"),
    ("jobs/batch/cpc_raw_to_bronze_task.py", "list_s3_keys_with_mtime",
     "the mtimes the rule is measured against, from the LIST that was happening anyway"),
    ("jobs/batch/cpc_raw_to_bronze_task.py", "raw_max_mtime=raw_max_mtime_by_month.get((yr, month))",
     "the wiring; the rule is inert without it"),
]


def _submit(name: str, jobdef: str, command: list[str], note: str = "") -> str:
    """One paste-ready Batch submit. The COMMAND OVERRIDE IS MANDATORY -- see THE Ref:: TRAP."""
    cmd = ", ".join(f'\\"{c}\\"' for c in command)
    line = (
        f'MSYS_NO_PATHCONV=1 aws batch submit-job --job-name {name} --job-queue {QUEUE} '
        f'--job-definition {jobdef} '
        f'--container-overrides "{{\\"command\\":[{cmd}]}}" --query jobId --output text'
    )
    return line + (f"\n  # {note}" if note else "")


STEPS: list[tuple[str, str, list[str]]] = [

    ("CHECK", "OFFLINE PREFLIGHT -- runs here, no AWS, no network. Everything below assumes it "
              "is green.", [
        "python scripts/ops/cpc_soil_repair_runbook.py --step CHECK",
        "# runs: the eight decks, ruff on the touched files, an import of both entrypoints, and",
        "# every source pin in SOURCE_PINS (each names the defect a refactor would reopen).",
        "# It asserts; it does not persuade.",
    ]),

    ("R1", "COMMIT AND BUILD. The repair is tree-only until an image carries it.", [
        "# The two other workflows are editing src/leviathan/graphrag/**, scripts/graphrag/**,",
        "# configs/graphrag/**, tests/unit/test_subject_resolver.py, tests/unit/test_state_*.py,",
        "# tests/unit/test_board_coverage.py, jobs/submit/submit_eval.py and .gitignore. COMMIT BY",
        "# EXPLICIT PATH -- this is a SHARED worktree and `git add -A` would sweep their work in.",
        "git add " + " ".join(LANE_FILES),
        "git commit -m \"fix(weather): CPC daily window on the PUBLISHED set + bronze freshness\"",
        "git push          # fast-forward to origin/main",
        "python scripts/ops/make_worker_context_tar.py --out worker_cpc_<sha>.tar.gz --ref HEAD",
        "# it REFUSES on a dirty COPY set (tracked CONTENT, not `git status` -- this autocrlf tree",
        "# prints phantom M's straight after a commit).",
        f"aws s3 cp worker_cpc_<sha>.tar.gz s3://{BUCKET}/build_contexts/worker_cpc_<sha>.tar.gz",
        "cat > kaniko_cpc_overrides.json <<'JSON'",
        '  {"command": ["--context", "s3://' + BUCKET + '/build_contexts/worker_cpc_<sha>.tar.gz",',
        '              "--dockerfile", "docker/leviathan_worker/Dockerfile",',
        f'              "--destination", "{ECR_URL}:<tag>",',
        '              "--build-arg", "BUILD_GIT_COMMIT=<HEAD sha>"]}',
        "JSON",
        f"MSYS_NO_PATHCONV=1 aws batch submit-job --job-name kaniko-cpc-soil-repair "
        f"--job-queue {QUEUE} --job-definition {JD_KANIKO} "
        f"--container-overrides file://kaniko_cpc_overrides.json --query jobId --output text",
        "# ~3 min in-region. READ THE PUSHED DIGEST FROM THE KANIKO LOG -- never infer it from a tag.",
        f"aws ecr describe-images --repository-name {WORKER_REPO} --image-ids imageTag=<tag> "
        f"--query 'imageDetails[0].imageDigest' --output text",
    ]),

    ("R2", "THE REPIN -- AND THE OWNER'S CHOICE. A digest-pinned jobdef makes a push a NO-OP, so "
           "THE REPIN IS THE DEPLOY. All three cpc legs ride the ten-family worker fleet pin.", [
        f"# LIVE NOW: {JD_TO_RAW}:19, {JD_R2B}:20, {JD_B2S}:19",
        f"#          all three on {FLEET_DIGEST[:23]}... ({FLEET_VAR_LINE})",
        "#",
        "# ROUTE A -- RIDE THE ALREADY-QUEUED FLEET REPIN (the silver six, 09-17 hard date).",
        "#   Cheapest: no extra digest move, no extra terraform apply. COST: the fleet variable's",
        "#   standing law is 'one digest move, one attributable content change'. If this repair",
        "#   rides with the ESR streaming work, a green first cpc fire is not solely attributable",
        "#   to this fix and a red one is not solely attributable either. State that in the flip",
        "#   note rather than discovering it during an RCA.",
        "#",
        "# ROUTE B -- A PER-JOBDEF OVERRIDE, the pattern this estate already uses",
        "#   (var.futures_eod_silver_image_digest layered over var.futures_eod_image_digest, and",
        "#   named as the divergence recipe in modules/batch/main.tf:110-125). Add",
        "#   var.cpc_soil_image_digest, default = the fleet digest, and let the three cpc",
        "#   resources prefer it. Moves TWO legs and leaves the other eight families untouched,",
        "#   so the fire is attributable. COST: ~20 lines of terraform and one owner apply.",
        "terraform -chdir=infra/terraform/envs/dev plan "
        "-target=module.batch.aws_batch_job_definition.cpc_soil_to_raw "
        "-target=module.batch.aws_batch_job_definition.cpc_soil_raw_to_bronze",
        "python scripts/ops/check_ecr_pinned_digests.py",
        "terraform -chdir=infra/terraform/envs/dev apply "
        "-target=module.batch.aws_batch_job_definition.cpc_soil_to_raw "
        "-target=module.batch.aws_batch_job_definition.cpc_soil_raw_to_bronze",
        "#",
        "# ROUTE C -- HAND-REPIN THE TWO JOBDEFS OUT OF BAND. NOT RECOMMENDED: these three",
        "#   resources ARE terraform-managed (modules/batch/main.tf:939, :1027, :1113), so a hand",
        "#   registration creates drift that the next apply touching them silently reverts -- the",
        "#   exact class modules/batch/main.tf:110-125 exists to stop. Listed only so the reason",
        "#   it is refused is written down.",
        "#   python scripts/ops/repin_jobdef_digest.py --job-definition " + JD_R2B +
        " --image-digest sha256:<new> --expect-vcpu 0.5 --expect-memory 1024",
        "#",
        "# WHICHEVER ROUTE: CONFIRM THE NEW REVISION NUMBER, read back from AWS.",
        f"aws batch describe-job-definitions --job-definition-name {JD_R2B} --status ACTIVE "
        "--query 'jobDefinitions[-1].[revision,containerProperties.image]' --output json",
    ]),

    ("R3", "RAW LEG -- the 404 must be GONE. Near no-op by design: raw already holds every "
           "published day.", [
        "# THE Ref:: TRAP, read live 2026-09-11 and the reason every submit below overrides the",
        "# command: the jobdef's own command is",
        "#   jobs/batch/cpc_soil_to_raw_task.py --year Ref::year ... with parameters year='2000'.",
        "# A submit with NO container override runs a YEAR-2000 TARBALL BACKFILL. The DAG never",
        "# hits this because it overrides the command with the bare script path (thin contract).",
        _submit("cpc-soil-to-raw-repair", JD_TO_RAW, ["jobs/batch/cpc_soil_to_raw_task.py"],
                "no args: the thin contract self-windows to the current year"),
        "# EXPECT in the log, and read the EXIT CODE not the words:",
        "#   'Found 252 daily files for w 2026 in GeoTIFF dir (publication tip 20260909)'",
        "#   'Raw already holds 252 day-keys for variable=w year=2026'",
        "#   'Daily window  variable=w year=2026  published=252 already_raw=252 to_fetch=0",
        "#    raw_day_keys=252  publication tip=20260909'",
        "#      -- the triple ADDS UP by construction: published = already_raw + to_fetch.",
        "#         raw_day_keys is its own figure and may exceed already_raw when raw holds a day",
        "#         the listing does not.",
        "#   'Nothing to fetch: raw already holds every published day'   <- or 1-2 new days",
        "#   'Publisher tip w.20260909 is 0 days behind the measured 2-day lag' <- the stall alarm",
        "#    reporting QUIET. On the steady-state morning this is the line that proves the source",
        "#    is alive; a run with NO publisher line at all is BLIND, not healthy.",
        "#   NO 'TRAILING-MONTH HOLE', NO 'CURRENT-YEAR HOLE', NO traceback, exit 0.",
        "# THE FALSIFIER: if 'CURRENT-YEAR HOLE 2026' appears, a day CPC published really is",
        "# missing from raw and the daily path could not fetch it. That is a real finding -- read",
        "# the per-day 'declining this day' warnings above it. It must still NOT fail the leg.",
        "# THE OTHER FALSIFIER: 'DAILY WINDOW OUTAGE' + a nonzero exit means the leg reached NOTHING",
        "# from a window at least 2 days wide -- a dead source, not a per-day decline. Read the hole",
        "# report and the 'UPSTREAM SHORT BLIND' line that precede it: both are printed BEFORE the",
        "# leg fails, on purpose. Check egress and the CPC host by hand before re-firing.",
        "# 'SINGLE-DAY DECLINE' is the one-day version and stays GREEN by design: it is red on the",
        "# NEXT run if the break lasts, because the window widens to 2. Do not re-fire to clear it;",
        "# let tomorrow's run decide.",
        "# THE THIRD FALSIFIER -- UPSTREAM, NOT US: 'UPSTREAM STALL: newest published w.YYYYMMDD is",
        "# N days behind the lag'. WARNING at >= 3, and at >= 7 the leg exits nonzero with that",
        "# reason. There is NOTHING to re-fire here: raw already holds every published day and CPC",
        "# has stopped moving. Confirm the tip by hand against the live index (the same URL the leg",
        "# reads; CPC_FTP_BASE in src/leviathan/ingestion/weather/cpc_soil_moisture.py) --",
        "#   curl -s https://ftp.cpc.ncep.noaa.gov/wd51yf/global_daily/GeoTIFF/ | Select-String w.2026",
        "# -- then raise it with the source, and expect the red to persist daily until CPC resumes.",
        "# AND: 'YEAR-BOUNDARY HOLE <prev year> STANDS' means Dec 30/31 (or more) never landed and",
        "# the archive season has closed. The remedy is the command the line itself names:",
        _submit("cpc-soil-year-backfill", JD_TO_RAW,
                ["jobs/batch/cpc_soil_to_raw_task.py", "--year", "<prev year>"],
                "an EXPLICIT --year still dies loudly on a missing archive -- correctly: here an "
                "operator asked for that year and must not be told it worked"),
    ]),

    ("R4", "BRONZE LEG -- THE STEP THAT PUTS THE FIFTEEN DAYS BACK. No flag: the freshness rule "
           "does it.", [
        _submit("cpc-raw-to-bronze-repair", JD_R2B, ["jobs/batch/cpc_raw_to_bronze_task.py"],
                "no --force_overwrite: measured, 849 partitions are already STALE by the rule"),
        "# EXPECT: 'Newest raw object per month: 2026-01=...T08:52:52 ... 2026-08=2026-09-02T08:48:27",
        "#          2026-09=2026-09-11T08:47:12'",
        "#   then 'Refreshing STALE bronze: ...year=2026/month=08...' x 422",
        "#        'Refreshing STALE bronze: ...year=2026/month=09...' x 427",
        "#        'Skipping fresh: ...' for months 01-07 and for white_sugar's five br_sugar",
        "#        August partitions.",
        "#   Final line: written=849 skipped=<the rest> declined=0.",
        "# THE FALSIFIER: declined>0 and a 'BRONZE SHRINK FLOOR HELD' line means a rewrite would",
        "# have REPLACED a partition with FEWER rows than it holds and was stopped. Those partitions",
        "# were left alone -- correctly. Read the 'Raw TIF not found in S3' warnings above it: the",
        "# defect is upstream of the write, and the re-run belongs after raw is whole.",
        "# ENVELOPE WATCH: 0.5 vCPU / 1,024 MiB, 7,200 s timeout, 3 attempts. This run writes 849",
        "# partitions instead of about 10 -- but the write loop is serial and each partition is a",
        "# ~30-row parquet; the expensive half (252 TIF downloads x 31 commodities of pixel reads)",
        "# is UNCHANGED and already succeeded inside this envelope on 09-08 and 09-09. Memory does",
        "# not move: rows_by_partition was always built whole. If it times out, raise the timeout,",
        "# never the concurrency -- do not hammer the write path to save a minute.",
    ]),

    ("R5", "SILVER LEG -- follows on its own. Already freshness-aware; nothing to change.", [
        "# BaseBronzeToSilverJob uses base_jobs.select_partitions_to_write (SILVER-V002): it",
        "# rewrites any silver partition whose bronze is newer. R4 just made 849 of them newer.",
        "python jobs/submit/submit_batch_b2s_cpc_soil.py      # 31 commodity tasks, fan-out",
        "# or, one commodity at a time, the DAG's own shape:",
        _submit("cpc-b2s-corn", JD_B2S,
                ["jobs/batch/cpc_bronze_to_silver_task.py", "--commodity", "corn_cbot"]),
        "# then the compaction that publishes the canonical [commodity, year] object:",
        _submit("cpc-compact", JD_COMPACT,
                ["jobs/batch/compact_weather_silver_task.py", "--source", "cpc_soil",
                 "--commodity", "all", "--reconcile-schema-widen"]),
    ]),

    ("R6", "THE CANONICAL PROMOTE -- or just let the cycle carry it. RECOMMENDED: the cycle.", [
        "# weather_daily is promote_mode=autonomous, auth_mode=kms, publish_class=A. The 08:00Z",
        "# fire runs fetch -> bronze -> [b2s x3 + compact-shadow x3 + gold] -> gate -> promote.",
        "# Once R2 has landed the image, the NEXT ordinary cycle performs R3, R4, R5 and the",
        "# promote by itself -- the freshness rule needs no operator. Hand-submitting R3-R5 buys",
        "# only latency, and it spends a KMS canonical promote outside the gate's own sequence.",
        "# RECOMMENDATION: land R1+R2, then WATCH the next 08:00Z cycle (VERIFY below).",
        "aws stepfunctions list-executions --state-machine-arn "
        f"arn:aws:states:{REGION}:{ACCOUNT}:stateMachine:leviathan-dev-weather-sched "
        "--max-results 5 --query 'executions[].[name,status,startDate]' --output table",
        "# NOTE the DAG TOLERATES a failed cpc job: the 09-08/09-09/09-10 executions all report",
        "# SUCCEEDED with the FAILED to-raw job inside them. 'The execution went green' is NOT",
        "# evidence this fix landed. The per-job exit code is.",
    ]),

    ("VERIFY", "THE MEASUREMENT. Bounded and partition-filtered -- never an unfiltered scan of "
               "silver_cpc_soil.", [
        "# silver_cpc_soil was DEPROJECTED 2026-07-14 (Glue parameter deprojected: 2026-07-14, 837",
        "# registered partitions), so partition projection can no longer turn a query into a LIST",
        "# storm. The yaml at configs/silver/tables/silver_cpc_soil.yaml:23-24 still carries a",
        "# 'NEVER start-query-execution against this weather table' fence written against that",
        "# retired hazard. DISCLOSED, not ignored: two bounded partition-filtered queries were run",
        "# on 2026-09-11 and the second scanned 50,767 bytes. The fence wants CORRECTING to name",
        "# the real rule (partition-filtered only); that edit is NOT this lane's and is flagged.",
        "#",
        "# BEFORE (measured 2026-09-11): max(date) = 2026-09-05 over 101,254 rows; 30 of 31",
        "# commodities at August=20 / September=5; white_sugar at August=31.",
        "# AFTER: max(date) = the newest published day; every commodity August=31, September=9+.",
        "",
        "-- per-month day counts, partition-filtered, one commodity at a time",
        "SELECT month, count(DISTINCT date) AS days, count(*) AS rows",
        "FROM leviathan_dev.silver_cpc_soil",
        "WHERE year = 2026 AND commodity = 'corn_cbot'",
        "GROUP BY month ORDER BY month;",
        "",
        "-- THE AGGREGATE THAT HID IT, kept as a warning: read it PER COMMODITY, never table-wide",
        "SELECT commodity,",
        "       sum(CASE WHEN month = 8 THEN 1 ELSE 0 END) AS aug_rows,",
        "       sum(CASE WHEN month = 9 THEN 1 ELSE 0 END) AS sep_rows",
        "FROM leviathan_dev.silver_cpc_soil WHERE year = 2026 GROUP BY commodity ORDER BY 1;",
        "",
        "# and the raw-side truth, which needs no Athena at all:",
        f"MSYS_NO_PATHCONV=1 aws s3 ls s3://{BUCKET}/raw/weather/source=cpc_soil/variable=w/ "
        "--recursive | grep -c '\\.tif$'   # 252 on 2026-09-11, one per published day",
    ]),

    ("ROLLBACK", "LAYERED, cheapest first.", [
        "# L1 -- the code. Revert the two task files and rebuild; the repair adds no schema, no",
        "#       new object layout and no new S3 path, so a revert is a pure code revert.",
        "# L2 -- the jobdef. Re-register the previous revision by re-applying the OLD digest.",
        f"aws batch describe-job-definitions --job-definition-name {JD_R2B} --status ACTIVE "
        "--query 'jobDefinitions[].[revision,containerProperties.image]' --output table",
        f"#       roll back to {FLEET_DIGEST[:23]}... (the 2026-08-27 #4 fleet pin).",
        "# L3 -- the DATA. There is nothing to roll back and that is the point: R4 only ADDS days",
        "#       to month partitions that were short. No row is deleted, no date is rewritten with",
        "#       a different value (the same raw TIF yields the same pixel), and the silver leg",
        "#       re-derives from bronze. A rollback of the code leaves the recovered days in place,",
        "#       correctly -- reverting would NOT re-freeze them, it would only stop future",
        "#       refreshes. Which is the defect. So L3 is: do nothing, and re-open the docket.",
    ]),
]


# ---------------------------------------------------------------------------
# CHECK -- the only step that RUNS anything, and it runs nothing outside this repo
# ---------------------------------------------------------------------------

def _run_check() -> int:
    failures: list[str] = []

    print(f"[1/4] source pins ({len(SOURCE_PINS)})")
    for rel, needle, why in SOURCE_PINS:
        text = (REPO / rel).read_text(encoding="utf-8")
        ok = needle in text
        print(f"      {'PASS' if ok else 'FAIL'}  {rel}: {needle!r}")
        if not ok:
            failures.append(f"{rel} lost {needle!r} -- {why}")

    print("[2/4] ruff on the touched files")
    files = [str(REPO / f) for f in LANE_FILES if f.endswith(".py")]
    rc = subprocess.run([sys.executable, "-m", "ruff", "check", *files],
                        cwd=REPO).returncode
    print(f"      ruff exit={rc}")
    if rc != 0:
        failures.append(f"ruff exit={rc}")

    print("[3/4] both entrypoints import and parse args")
    for entry in ("jobs/batch/cpc_soil_to_raw_task.py", "jobs/batch/cpc_raw_to_bronze_task.py"):
        rc = subprocess.run([sys.executable, str(REPO / entry), "--help"],
                            cwd=REPO, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL).returncode
        print(f"      {entry} --help exit={rc}")
        if rc != 0:
            failures.append(f"{entry} --help exit={rc}")

    print("[4/4] the decks")
    rc = subprocess.run([sys.executable, "-m", "pytest", *DECKS, "-q"], cwd=REPO).returncode
    print(f"      pytest exit={rc}")
    if rc != 0:
        failures.append(f"pytest exit={rc}")

    print()
    if failures:
        print("PREFLIGHT RED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PREFLIGHT GREEN -- R1 may proceed.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="CPC soil moisture repair + backfill runbook (dry run)")
    ap.add_argument("--step", default=None, help="print one step, or CHECK to run the preflight")
    ap.add_argument("--list", action="store_true", help="just the step names")
    args = ap.parse_args()

    if args.list:
        for name, title, _ in STEPS:
            print(f"{name:9s} {title.splitlines()[0]}")
        return 0

    if args.step and args.step.upper() == "CHECK":
        return _run_check()

    wanted = {s.upper() for s in ([args.step] if args.step else [n for n, _, _ in STEPS])}
    for name, title, lines in STEPS:
        if name.upper() not in wanted:
            continue
        print("=" * 95)
        print(f"{name}  {title}")
        print("=" * 95)
        for line in lines:
            print(f"  {line}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
