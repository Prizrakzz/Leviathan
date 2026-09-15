#!/usr/bin/env python
"""GOLD_WEATHER_Z FRESHNESS RUNBOOK -- the $0 per-layer census, and the exact command for every
repair step.  IT NEVER MUTATES ANYTHING.

    python scripts/ops/weather_z_freshness_runbook.py                 # print every step
    python scripts/ops/weather_z_freshness_runbook.py --list          # just the step names
    python scripts/ops/weather_z_freshness_runbook.py --step W2       # print one step
    python scripts/ops/weather_z_freshness_runbook.py --step CHECK    # RUN the offline preflight
    python scripts/ops/weather_z_freshness_runbook.py --step CENSUS   # RUN the $0 read-only census

DRY RUN BY CONSTRUCTION.  There is no ``--run``.  No code path here submits a Batch job, starts a
Glue run, writes S3, registers a job definition or applies terraform: every mutating command is
PRINTED for the operator to paste.  ``--step CHECK`` reads local files and runs local pytest only;
``--step CENSUS`` does S3 LIST/HEAD/GET and HTTP HEAD, and nothing else.

ASCII-only output (the owner's console is cp1252).  Chain commands with ``;`` -- PowerShell 5.1
has no ``&&``.

===============================================================================================
WHAT WAS BROKEN -- ONE SERVED CARD, TWO INDEPENDENT FREEZES, NEITHER OF THEM THE cpc ONE
===============================================================================================

THE SYMPTOM.  ``gold/weather_z/corn_cbot.parquet`` was rewritten on 2026-09-11 at 09:19:50Z --
45,002 rows -- and MAX(year*100+month) read 202607 for every one of its five metrics.  42 days
behind, on a table the numbers registry SERVES (registry.py:591), the state board reads
(state/lint.py:83 YM_BOARD_CARDS) and whose own card declares ``ym_publication_lag_days: 7``.

FREEZE 1 -- NASA POWER, raw->bronze.  Raw is COMPLETE and CURRENT: the August payload was refetched
2026-09-11T08:04:59Z and carries 31 of 31 real T2M_MAX and T2M_MIN days.  Bronze month=08 still held
the 22 rows it was given on 2026-08-22T11:30:14Z, because ``BaseRawToBronzeJob._process_one``
(storage/base_jobs.py:348-350) returns "skipped" on MERE EXISTENCE -- no mtime comparison anywhere,
unlike the bronze->silver seam one layer down, which has had SILVER-V002 since the CHIRPS
stale-silver fix.  Twenty green daily runs read fresh raw and rewrote nothing.

FREEZE 2 -- CHIRPS, fetch->bronze.  ``fetch_chirps_daily_values`` returns ``{region: None}`` on a
404 (chirps.py:59-63) -- a TRUTHY dict -- so on 2026-08-22 the daily task wrote a 31-row ALL-NULL
August bronze, and the existence-only write skip preserved it ever since.  The F044 null-drop at
silver then turned that skeleton into NO August partition at all.

AND A THIRD, LATENT: ``_months_to_process`` refetched an older current-year month only when a
sentinel object was ABSENT.  MEASURED: CHIRPS v2.0 finals publish in MONTH BLOCKS (the 2026 index
ends at ``chirps-v2.0.2026.07.31.tif.gz``; every August day and the 2026-09 days HEAD 404 on
2026-09-11), so August lands AFTER it becomes M-2 on 2026-10-01 -- and the 2026-08-22 skeleton would
have outlived the publication meant to replace it.

WHAT MOVES TODAY AND WHAT DOES NOT.  The NASA half moves NOW, with no code and no image (step W1):
tmax_anomaly / gdd_z / heat_stress_z / frost_event_flag advance 202607 -> 202608 for under a dollar.
drought_z CANNOT move today -- the source has published nothing after 2026-07-31.  What the CHIRPS
fix buys is that the August block is PICKED UP when it lands instead of being refused by a skeleton.

===============================================================================================
THE GATE SAW NONE OF IT, AND NEITHER DID THE POLLER
===============================================================================================

``jobs/audit/silver_rebuild_gate.py`` has seven Branch-A stages and three Branch-B stages and NOT
ONE OF THEM READS A DATE.  feature_probe asserts bytes exist; value_census asserts a non-null
FRACTION (0.5, provisional); parity compares pg against Athena, which are identically stale, and its
own docstring concedes that identically-wrong on both backends is a clean PASS.  The gate passed on
09-07, 09-08, 09-09 and 09-11 with the table 42 days stale.

``jobs/observability/freshness_poller_task.py`` + ``silver/freshness.py:136 newest_last_modified``
measure the newest S3 object's LastModified.  The producers rewrite the object every day (gold
corn_cbot.parquet 09:19:50Z, silver chirps canonical 09:49:08Z), so FreshnessLagDays read 0,
FreshnessLagRatio 0.00, FreshnessBreachCount 0 -- green, on a dead leg.

Even a CORRECT data-date read against the EXISTING denominator would have been silent today:
``declared_ceiling_days(gold_weather_z)`` resolves to CADENCE_DEFAULT_LAG_DAYS['monthly'] = 45 and
the data lag was 42; it first breaches 2026-09-15.  So the dark stage's denominator is the CARD'S
OWN PROMISE -- ``_ym_lagged_asof_ym(asof, ym_publication_lag_days)``, the same arithmetic the as-of
guard uses to ADMIT a month.  On 2026-09-11 that admits 202608 while the bytes hold 202607:
months_behind = 1, measurable now, with no new constant invented anywhere.

===============================================================================================
WHAT IS OUT OF THIS LANE AND NEEDS THE OWNER'S WORD
===============================================================================================

  * ``configs/graphrag/numbers/tables.yaml`` gold_weather_z ``ym_publication_lag_days: 7`` is
    REFUTED by measurement and the card itself asked for the check ("UNVERIFIED ... S4's census
    measures it").  The SLOWEST feeder governs and that is CHIRPS at a ~45-day month block, not 7.
    The field is not cosmetic: ``state/analogs.py::_lag_days_of`` builds the knowledge axis of
    state_history from it, so every historical analog crossing a weather-z driver is currently
    ranked against a point-in-time window ~35 days too generous.  FENCES CORRECT OR COMPUTE, NEVER
    DELETE -- the declaration should be corrected to the measured governing number, not removed.
  * ``configs/datasets/source_contracts.yaml`` declares NO source publication lag for either weather
    source, and ``freshness_sla.max_lag_days`` is null on gold_weather_z, silver_chirps AND
    silver_nasa_power.  MEASURED values to declare: nasa_power = 3 days (a 2026-09-11 window request
    returned 11 day keys, 8 real, last real day 2026-09-08); chirps = a whole-month block, observed
    complete for July by 2026-08-22 (<= 22 d) and absent for August at 2026-09-11 (>= 11 d).
    Until they exist the dark stage reports a date-grain table's AGE as a fact and refuses to call
    it "behind" -- a metric named DaysBehind with no declared denominator would be a threshold
    invented in telemetry.
  * ``_DATA_FRESHNESS_BLOCKING`` in jobs/audit/silver_rebuild_gate.py stays False until the owner
    flips it, and the CloudWatch ALARM stays UNBUILT: the threshold is set from a week of measured
    data, not guessed the day the metric is born.
  * THE GATE STILL DOES NOT MEASURE THE TWO FEEDERS THAT FROZE.  ``stage_data_freshness`` reads the
    PG MIRROR only, and silver_chirps + silver_nasa_power are the Branch-B projection/INV-3 class:
    they report SKIPPED "not in the pg mirror" even after the promotion flip.  Only gold_weather_z --
    the served card, which is what the board prints -- is actually judged.  Measuring a Branch-B
    feeder needs an S3 FOOTER read (Athena is barred for that class) at ~1.4K GETs per gate run,
    which is not a cost a dark stage may impose; it is the stated follow-up, deliberately unbuilt
    rather than half-built.  So a chirps freeze is still caught DOWNSTREAM (at gold) and not at the
    feeder, and this line exists so that is never read as covered.
"""
from __future__ import annotations

import argparse
import calendar
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUCKET = "leviathan-dev-shahem-001"
REGION = "us-east-1"

TOUCHED = [
    "jobs/batch/chirps_to_bronze_task.py",
    "jobs/batch/chirps_year_to_bronze_task.py",
    "jobs/glue/raw_to_bronze_nasa_power.py",
    "jobs/batch/gold_weather_z_task.py",
    "src/leviathan/transforms/gold/weather_z.py",
    "jobs/audit/silver_rebuild_gate.py",
    # the CHIRPS PRELIM lane (2026-09-15)
    "src/leviathan/ingestion/weather/chirps.py",
    "src/leviathan/transforms/bronze_to_silver/chirps_weather.py",
    "src/leviathan/transforms/bronze_to_silver/_weather_schema.py",
    "src/leviathan/transforms/bronze_to_silver/weather_compaction.py",
    # this runbook lints ITSELF: the commands it prints are part of the deliverable, and a preflight
    # that exempts its own file is the same blind spot the wave was opened to close.
    "scripts/ops/weather_z_freshness_runbook.py",
]

DECKS = [
    "tests/unit/test_chirps_bronze_all_null_gate.py",
    "tests/unit/test_chirps_bronze_completeness_skip.py",
    "tests/unit/test_chirps_month_window_completeness.py",
    "tests/unit/test_nasa_bronze_freshness.py",
    "tests/unit/test_weather_z_metric_tip.py",
    "tests/unit/test_weather_z_tripwire_emit.py",
    "tests/unit/test_gate_data_freshness_stage.py",
    # the existing decks this wave touches the behaviour of
    "tests/unit/test_chirps_ingest_gates.py",
    "tests/unit/test_chirps_ingestion.py",
    "tests/unit/test_chirps_bronze_to_silver.py",
    "tests/unit/test_gold_weather_z.py",
    "tests/unit/test_silver_rebuild_gate.py",
    "tests/unit/test_gate_exit_vocabulary.py",
    "tests/unit/test_nasa_power_ingestion.py",
    # the CHIRPS PRELIM lane (2026-09-15) -- including the byte-identity case, which drives an
    # all-final month fetch -> bronze -> silver -> compute_weather_z and compares the gold frame
    # element-wise against the pre-lane module loaded out of ``git show HEAD:``.
    "tests/unit/test_chirps_prelim_fallback.py",
    "tests/unit/test_chirps_prelim_supersession.py",
    "tests/unit/test_chirps_prelim_schema_widening.py",
    "tests/unit/test_weather_z_preliminary_stamp.py",
    "tests/unit/test_weather_schema_pinned.py",
    "tests/unit/test_weather_compaction_f047.py",
    "tests/unit/test_state_registry_ym_lag.py",
    "tests/unit/silver/test_silver_registry_gen.py",
]

STEPS = [
    ("W1", "MOVE THE NASA HALF TODAY -- no code, no image, under $1", [
        "The NASA freeze needs no deploy to clear ONCE: --force_overwrite reprocesses every raw",
        "file regardless of the existence skip. This advances four of the five metrics from",
        "202607 to 202608 and is INDEPENDENT of the code fix (which stops it recurring).",
        "",
        "MSYS_NO_PATHCONV=1 aws glue start-job-run --job-name leviathan-dev-raw-to-bronze-nasa-power \\",
        "  --arguments '{\"--force_overwrite\":\"true\"}' --region us-east-1",
        "",
        "then, once it succeeds (the b2s leg is ALREADY SILVER-V002 freshness-aware, so it needs no",
        "force -- it refreshes any silver partition whose bronze is newer):",
        "",
        "MSYS_NO_PATHCONV=1 aws glue start-job-run --job-name leviathan-dev-bronze-to-silver-nasa-power \\",
        "  --region us-east-1",
        "",
        "then let the 08:00Z weather_daily DAG compact + recompute gold, or submit gold by hand --",
        "BUT READ W4 FIRST: the gold submit wrapper hardcodes the SPOT queue.",
        "",
        "VERIFY, do not assume: re-run --step CENSUS and read the per-metric tips.",
    ]),
    ("W2", "DEPLOY THE CHIRPS FIX -- new WORKER image + a jobdef repin", [
        "The two CHIRPS Batch jobdefs are DIGEST-PINNED, so a git push alone is a NO-OP",
        "(feedback_digest_pinned_jobdefs_make_push_a_noop). The sequence is:",
        "",
        "  1. build + push a WORKER image from the MAIN tree (never a worktree -- gitignored",
        "     configs must be baked: feedback_worktree_builds_miss_gitignored_configs)",
        "  2. python jobs/utils/register_evidence_jobdef.py  (or the repin script) for BOTH:",
        "       leviathan-dev-chirps-to-bronze-backfill      (rev 19 today)",
        "       leviathan-dev-chirps-bronze-to-silver        (rev 21 today)",
        "     both currently worker@sha256:91104375a5af...",
        "  3. verify the NEW revision number and the image digest before any submit",
        "",
        "TRAPS MEASURED ON THE LIVE JOBDEFS (describe-job-definitions, 2026-09-11):",
        "  - chirps-to-bronze-backfill has NO --force_overwrite Ref at all, and its defaults are",
        "    commodity=corn_cbot year=1981. A forced run needs a FULL containerOverrides command.",
        "  - chirps-bronze-to-silver defaults commodity=corn_cbot: a submit that omits",
        "    commodity=all silently runs ONE commodity. commodity=all also flips the year window",
        "    to 2026-only, while a NAMED commodity means ALL years.",
        "  - gold-weather-z (rev 8) is on the EMBEDDER repository (embedder@sha256:78264c51bc2a).",
        "    A worker digest repinned there dies at STARTING with CannotPullContainerError",
        "    (feedback_jobdef_repository_family_on_repin).",
        "",
        "AFTER THE REPIN, YOU USUALLY NEED NO FORCED RUN AT ALL: the shipped daily task now re-enters",
        "an incomplete elapsed month on its own (the observation-count yardstick), so the August block",
        "is picked up by the ordinary 08:00Z DAG within a day of the source publishing it. The two",
        "commands below are the 'I want it NOW' levers, not the repair.",
        "",
        "(a) CHIRPS fetch->bronze, forced, 2026 only. containerOverrides REPLACES the jobdef command",
        "    outright, so no Ref:: is left unresolved -- this is the same shape the weather_daily DAG",
        "    itself submits (configs/silver/dags/_rendered/weather_daily.schedule.json), plus the two",
        "    args the jobdef cannot pass. ONDEMAND QUEUE, per feedback_scheduled_jobs_ondemand_only:",
        "",
        "  MSYS_NO_PATHCONV=1 aws batch submit-job --region us-east-1 \\",
        "    --job-name chirps-to-bronze-force-2026 \\",
        "    --job-queue leviathan-dev-queue-ondemand \\",
        "    --job-definition leviathan-dev-chirps-to-bronze-backfill:<NEW REV> \\",
        "    --container-overrides file://chirps_force.json",
        "",
        "    chirps_force.json (a FILE, not an inline string: PowerShell 5.1 mangles embedded double",
        "    quotes on their way to a native exe -- in Git Bash the same JSON may be passed inline):",
        "",
        '      {"command":["jobs/batch/chirps_to_bronze_task.py",',
        '                  "--commodity","all","--year","2026",',
        '                  "--bucket","leviathan-dev-shahem-001","--aws_region","us-east-1",',
        '                  "--force_overwrite","true"]}',
        "",
        "    COST SHAPE, CORRECTED 2026-09-15 BY MEASUREMENT (an earlier rewrite of this note said a",
        "    forced 2026 run 'costs at most TWO months of real rasters' because the months outside the",
        "    prelim reach '404 exactly as before'. THAT WAS WRONG AND IT UNDERSTATED THE SPEND ~4x: the",
        "    months outside the reach are the months whose FINAL BLOCK HAS LONG SINCE LANDED, so they",
        "    are the most expensive reads on the list, not 404s. HTTP HEAD on the mid-month FINAL of",
        "    every elapsed 2026 month, measured 2026-09-15: 01-15 200 (Last-Modified Feb 13) / 02-15 200",
        "    (Mar 16) / 03-15 200 (Apr 13) / 04-15 200 (May 15) / 05-15 200 (Jun 15) / 06-15 200 (Jul 14)",
        "    / 07-15 200 (Aug 14) / 08-15 200 (Sep 11); only 09-15 404s. The pre-prelim text this",
        "    replaced -- '--force_overwrite re-downloads EVERY elapsed month of 2026 for EVERY region of",
        "    EVERY commodity' -- was CORRECT, and still is.)",
        "",
        "    SO: a forced 2026 run today reads 243 real FINAL day-opens (Jan 1 - Aug 31, every one",
        "    published) plus the September days inside the prelim reach, ~258 in all. At the measured",
        "    per-open cost in W6 (2.1-11 MB, 60-69 s serial from a laptop) that is the run to think",
        "    twice about. What the PRELIM changed is ONLY the tail:",
        "      (-) a day the FINAL has not published USED to cost an instant 404. Inside the reach it is",
        "          now a REAL 2-3 MB read of the PRELIM raster, which /vsigzip/ must inflate from byte 0",
        "          to the deepest requested row. That is ~15-45 day-opens (the current month to date,",
        "          plus the previous month while its block is still absent), ADDED to the 243.",
        "      (=) outside the reach (chirps.PRELIM_MONTH_REACH = 1) nothing changed at all: those",
        "          months read their FINAL exactly as they always did, and a day with no final and no",
        "          prelim costs the same single 404 it used to.",
        "      (+) the daily task now opens each (year, month, day) raster ONCE PER RUN across ALL",
        "          commodities (the year task's cross-commodity dedup, ported), instead of once per",
        "          (day, commodity) -- a 31x cut that dwarfs everything above (W6 has the arithmetic).",
        "    Drop --force_overwrite and pass --year 2026 alone to let the completeness test decide which",
        "    months are actually short -- and note that with the prelim live it usually decides NONE,",
        "    because the current and previous month are already unconditional.",
        "",
        "(b) CHIRPS bronze->silver, all commodities (the jobdef's Refs already exist, so --parameters",
        "    is enough and there is no JSON to quote):",
        "",
        "  MSYS_NO_PATHCONV=1 aws batch submit-job --region us-east-1 \\",
        "    --job-name chirps-b2s-all \\",
        "    --job-queue leviathan-dev-queue-ondemand \\",
        "    --job-definition leviathan-dev-chirps-bronze-to-silver:<NEW REV> \\",
        "    --parameters commodity=all,bucket=leviathan-dev-shahem-001,aws_region=us-east-1,"
        "force_overwrite=false",
    ]),
    ("W3", "DEPLOY THE NASA FIX -- terraform, NOT an image", [
        "jobs/glue/raw_to_bronze_nasa_power.py is a GLUE SCRIPT. It reaches AWS through the",
        "glue_job terraform module, which re-uploads it to s3://<bucket>/glue-scripts/",
        "(infra/terraform/modules/glue_job/main.tf:50). NO image build, NO jobdef repin.",
        "",
        "  cd infra/terraform/envs/dev ; terraform plan -target=module.<glue_job module>",
        "  cd infra/terraform/envs/dev ; terraform apply -target=module.<glue_job module>",
        "",
        "An emergency `aws s3 cp` of the script would work and would DRIFT FROM TFSTATE. Do not.",
    ]),
    ("W4", "THE GOLD SUBMIT WRAPPER RIDES SPOT -- read before any hand backfill", [
        "jobs/submit/submit_batch_gold_weather_z.py:32 hardcodes",
        "  _JOB_QUEUE = 'leviathan-dev-queue'   # the SPOT queue",
        "with no --queue override, while the weather_daily DAG routes gold to",
        "  leviathan-dev-queue-ondemand",
        "A hand backfill through that wrapper can be reclaimed mid-write. Prefer letting the DAG",
        "run it, or submit by hand onto the ondemand queue.",
        "(feedback_scheduled_jobs_ondemand_only: scheduled jobs = on-demand queue ONLY.)",
        "",
        "THE HAND SUBMIT, ON THE ONDEMAND QUEUE. This is byte for byte the command the weather_daily",
        "DAG runs for gold (configs/silver/dags/_rendered/weather_daily.schedule.json), with only the",
        "queue named explicitly -- the wrapper is bypassed entirely, so its hardcoded SPOT queue and",
        "its digest-pin check are both out of the picture:",
        "",
        "  MSYS_NO_PATHCONV=1 aws batch submit-job --region us-east-1 \\",
        "    --job-name gold-weather-z-all \\",
        "    --job-queue leviathan-dev-queue-ondemand \\",
        "    --job-definition leviathan-dev-gold-weather-z:8 \\",
        "    --container-overrides file://gold_force.json",
        "",
        "  gold_force.json:",
        '    {"command":["jobs/batch/gold_weather_z_task.py","--commodity","all",',
        '                "--force-overwrite","true"]}',
        "",
        "MEASURED, AND THE REASON THE OVERRIDE IS THE SAFER FORM: rev 8's own `parameters` map is",
        "EMPTY ({}), while its command carries four Ref:: placeholders (bucket, aws_region, commodity,",
        "force_overwrite). A --parameters submit that omits any one of them leaves the LITERAL STRING",
        "'Ref::bucket' on the argv and the job dies on a bucket that does not exist. A containerOverrides",
        "command replaces the array outright, so no placeholder survives to be forgotten; bucket and",
        "region come from the jobdef's own LEVIATHAN_BUCKET / AWS_REGION environment.",
        "",
        "Note --force-overwrite here spells its flag with HYPHENS (gold_weather_z_task.py:259), while",
        "the two chirps tasks spell theirs with UNDERSCORES (--force_overwrite). Copy, do not retype.",
    ]),
    ("W5", "WHAT TO WATCH AFTER, AND WHERE", [
        "The producer now logs one line per commodity and publishes two CloudWatch metrics into",
        "namespace Leviathan/Silver:",
        "  WeatherZTipYm        {Commodity, Metric}  = the data month actually present",
        "  WeatherZMonthsBehind {Commodity, Metric}  = the card's promise minus that month",
        "The gate publishes, on the put_metric_data call it already makes:",
        "  DataFreshnessMonthsBehind {Table, Family}",
        "  DataDateAgeDays           {Table, Family}",
        "",
        "PER-METRIC IS THE POINT: after W1 and before CHIRPS publishes August, four metrics read",
        "202608 and drought_z reads 202607 inside ONE object. A table-grain counter would take the",
        "max, print '0 behind', and hide the drought hole exactly when it opens.",
        "",
        "NO ALARM IS BUILT. Set its threshold from a week of these datums, not from a guess.",
    ]),
    ("W6", "THE CHIRPS PRELIM LANE -- deploy, backfill, RELOAD THE MIRROR, THEN (only then) the lag", [
        "WHAT SHIPPED (2026-09-15). The fetcher reads CHIRPS v2.0 PRELIM for any day of the CURRENT or",
        "PREVIOUS month whose FINAL block has not landed; bronze carries is_preliminary per day and the",
        "final/prelim/absent counts in _meta.json; the rewrite rule gained a FINAL-DAYS axis so a landed",
        "block can supersede a complete prelim month (the old scalar rule refused it as EQUAL); silver",
        "carries a '0'/'1' is_preliminary string; gold emits drought_z_is_preliminary beside every",
        "drought_z cell row, and drought_z_preliminary_share + _cells at basin/country grain.",
        "",
        "WHAT IT COSTS, MEASURED 2026-09-15 against the real UCSB host (one commodity, corn_cbot,",
        "24 in-band deduped coordinates; the deepest sits at raster row 1733 of 2000, so 87% of every",
        "file must be inflated before the last pixel is reached -- /vsigzip/ cannot seek a gzip stream):",
        "",
        "  PRELIM FALLBACK PATH, 2026-09-01..10 (final 404 every day, prelim 200 every day -- the",
        "  fallback actually firing):  10/10 opens succeeded, 24/24 values per day,",
        "      127.6 s wall at 5 threads | 601.6 s serial | 60.2 s per open | 2.24 MB per open.",
        "  FINAL PATH, the whole of 2026-08 (31 days):",
        "      481.7 s wall at 5 threads | 2,126 s serial | 68.6 s per open | 6.74 MB per day-open",
        "      (208,903,347 gz bytes across the month: 2.1-2.6 MB for days 01-15, 10.3-11.2 MB for",
        "      days 16-31 -- a gzip-ratio artifact, the INFLATED size is 57,612,618 B either way).",
        "",
        "  THE FLEET ARITHMETIC, over that measured per-open cost. One commodity cannot demonstrate a",
        "  CROSS-commodity saving, so this is arithmetic with the measurement as its base: 31 commodities",
        "  x a two-month reach = ~62 day-opens per run either way, but the OPEN COUNT is what differs.",
        "      WITH the shipped dedup   :    62 opens/run | 0.42 GB/run | 12-14 min/run",
        "      WITHOUT it (per-commodity): 1,922 opens/run | 12.9 GB/run | 6.4-7.3 h/run",
        "  That 31x is the difference between a leg that fits inside the 08:00Z DAG and one that cannot,",
        "  and between 0.4 GB and 13 GB a day pulled from a public academic host.",
        "",
        "  AND THE MEASUREMENT FOUND A REAL FAILURE, which is the first thing to smoke after the deploy:",
        "  17 of the 31 August opens FAILED with",
        "      RasterioIOError: TIFFReadDirectory:Failed to read directory at offset 57600008",
        "  -- every one of the 10-11 MB files (days 16-31, plus day 02), while every 2.1-2.6 MB file",
        "  succeeded and returned all 24 values. Offset 57,600,008 is 7200*2000*4 + 8: the TIFF directory",
        "  sits AFTER the whole image, so the reader must inflate all 57.6 MB before it can read the IFD,",
        "  and the GDAL_HTTP_TIMEOUT that chirps.py set -- 30 s at the time of the measurement -- cut it",
        "  off first. THE DEFAULT IS NOW 120 (chirps.py:50), which is the direct remedy and NOT a proven",
        "  one: THIS WAS A LAPTOP READING from a home link, not a Fargate one -- us-east-1 to UCSB is a",
        "  different link and the absolute seconds are an upper bound (the 31x RATIO is",
        "  bandwidth-independent). But it is exactly the shape T-C1 predicted: no data defect, the job",
        "  just loses days into _fetch_day's except. SMOKE ONE MONTH ON THE REAL JOBDEF BEFORE THE",
        "  FLEET, and read the new `fetch_failures` map in _meta.json -- that map is the difference",
        "  between 'the source has not published' and 'the host refused us', and its per-month count",
        "  after the first Fargate run is THE number that revises the 120.",
        "",
        "  AND THE LEVER IS AN ENV VAR, NOT A REBUILD. chirps.py sets GDAL_HTTP_TIMEOUT with",
        "  os.environ.setdefault, so the jobdef environment WINS. If the first smoke still shows",
        "  TIFFReadDirectory failures, raise it in the same sitting by adding to the containerOverrides",
        "  of the submit in step 4 -- no image, no repin:",
        "",
        '      \"environment\": [{\"name\": \"GDAL_HTTP_TIMEOUT\", \"value\": \"300\"}]',
        "",
        "THE ORDER IS NOT STYLISTIC. Getting it wrong re-opens the defect 29de55eb closed.",
        "",
        "  1. DEPLOY. Build + push from the MAIN tree (never a worktree --",
        "     feedback_worktree_builds_miss_gitignored_configs), then repin SIX job definitions -- not",
        "     three. Read the REPOSITORY FAMILY beside each one, because a digest from the wrong family",
        "     dies at STARTING with CannotPullContainerError",
        "     (feedback_jobdef_repository_family_on_repin). Revisions and digests below are LIVE, read",
        "     read-only from AWS Batch on 2026-09-15; re-read them before you repin (the one-liner is at",
        "     the end of this step):",
        "",
        "       jobdef                                     family    rev  digest        carries",
        "       leviathan-dev-chirps-to-bronze-backfill    WORKER    19   sha256:91104375  chirps.py +",
        "                                                                                 the daily task",
        "       leviathan-dev-chirps-bronze-to-silver      WORKER    21   sha256:91104375  _weather_schema",
        "                                                                                 + chirps_weather",
        "       leviathan-dev-weather-compact              WORKER     8   sha256:e11d45fb  weather_compaction",
        "                                                                                 (SHADOW publish)",
        "       leviathan-dev-silver-publisher-runner      WORKER    43   sha256:16068c6b  weather_compaction",
        "                                                                                 (CANONICAL, KMS)",
        "       leviathan-dev-gold-weather-z               EMBEDDER   8   sha256:78264c51  weather_z.py +",
        "                                                                                 the numbers card",
        "       leviathan-dev-evidence-build               EMBEDDER 135   sha256:011438f6  the card the pg",
        "                                                                                 loader filters by",
        "",
        "     THE TWO COMPACTION JOBDEFS ARE THE ONES AN EARLIER CUT OF THIS STEP MISSED, and they are",
        "     the silent half: both bake weather_compaction.py, which carries the additive '0' backfill",
        "     and the explicit prelim-loses-to-final sort. A compaction run on a pre-lane image does not",
        "     fail -- it publishes an object WITHOUT the column, which reads downstream as a producer",
        "     that never wrote it. gold-weather-z and evidence-build ride the EMBEDDER image because",
        "     weather_z.py AND configs/graphrag/numbers/tables.yaml are baked there. NOTE that the four",
        "     worker jobdefs sit on THREE DIFFERENT digests today, so 'repin the worker jobdefs' is six",
        "     decisions and not one. Deploying a subset half-lands the lane, and the missing half shows",
        "     up as a MISSING METRIC, not an error.",
        "",
        "  cd C:\\Users\\User\\Desktop\\Leviathan; foreach ($n in @("
        "'leviathan-dev-chirps-to-bronze-backfill','leviathan-dev-chirps-bronze-to-silver',"
        "'leviathan-dev-weather-compact','leviathan-dev-silver-publisher-runner',"
        "'leviathan-dev-gold-weather-z','leviathan-dev-evidence-build')) { $j = aws batch "
        "describe-job-definitions --region us-east-1 --job-definition-name $n --status ACTIVE "
        "--output json | ConvertFrom-Json; $t = $j.jobDefinitions | Sort-Object revision -Descending "
        "| Select-Object -First 1; Write-Output (\"{0}  rev {1}  {2}\" -f $n, $t.revision, "
        "$t.containerProperties.image) }",
        "",
        "  2. COMPACTION, AND IT IS A BATCH SUBMIT -- NEVER A LOCAL PRODUCER RUN. silver_chirps' writer",
        "     schema gained a 12th column, so the first compaction of each (commodity, year) publishes",
        "     an object whose SD is a trailing-column WIDEN of the partition SD, and ShadowPublisher",
        "     fails THAT closed unless --reconcile-schema-widen is passed. An earlier cut of this step",
        "     printed the bare `python jobs/batch/compact_weather_silver_task.py ...` form: running a",
        "     producer from a laptop against the real bucket is the 09-11 breach class and it is not an",
        "     option here. Neither jobdef has parameter defaults or a Ref for the flag (measured), so a",
        "     FULL containerOverrides is the only form that works. Write the overrides to a FILE --",
        "     PowerShell 5.1 mangles embedded double quotes on their way to a native exe.",
        "",
        "     (a) SHADOW first, on leviathan-dev-weather-compact:",
        "",
        "  cd C:\\Users\\User\\Desktop\\Leviathan; @'",
        '  {\"command\": [\"jobs/batch/compact_weather_silver_task.py\",',
        '               \"--source\", \"chirps\", \"--commodity\", \"all\",',
        '               \"--bucket\", \"leviathan-dev-shahem-001\", \"--aws-region\", \"us-east-1\",',
        '               \"--reconcile-schema-widen\", \"--publish-mode\", \"shadow\"]}',
        "  '@ | Set-Content -Encoding ascii \"$env:TEMP\\chirps_compact_shadow.json\"; "
        "aws batch submit-job --region us-east-1 --job-name chirps-compact-shadow "
        "--job-queue leviathan-dev-queue-ondemand "
        "--job-definition leviathan-dev-weather-compact:<NEW REV> "
        "--container-overrides \"file://$env:TEMP\\chirps_compact_shadow.json\"",
        "",
        "     (b) THEN CANONICAL, through the KMS-signed publisher runner, exactly as the DAG does.",
        "         Both env values are already baked into that jobdef; they are repeated in the override",
        "         so the submit is self-describing:",
        "",
        "  cd C:\\Users\\User\\Desktop\\Leviathan; @'",
        '  {\"command\": [\"jobs/batch/compact_weather_silver_task.py\",',
        '               \"--source\", \"chirps\", \"--commodity\", \"all\",',
        '               \"--bucket\", \"leviathan-dev-shahem-001\", \"--aws-region\", \"us-east-1\",',
        '               \"--reconcile-schema-widen\", \"--publish-mode\", \"canonical\"],',
        '   \"environment\": [{\"name\": \"LEVIATHAN_APPROVAL_MODE\", \"value\": \"kms\"},',
        '                   {\"name\": \"LEVIATHAN_KMS_KEY_ID\",',
        '                    \"value\": \"alias/leviathan-dev-publish-signer\"}]}',
        "  '@ | Set-Content -Encoding ascii \"$env:TEMP\\chirps_compact_canonical.json\"; "
        "aws batch submit-job --region us-east-1 --job-name chirps-compact-canonical "
        "--job-queue leviathan-dev-queue-ondemand "
        "--job-definition leviathan-dev-silver-publisher-runner:<NEW REV> "
        "--container-overrides \"file://$env:TEMP\\chirps_compact_canonical.json\"",
        "",
        "     PASS = silver/weather/source=chirps/commodity=corn_cbot/year=2026/part-000.parquet at 12",
        "     columns with is_preliminary present (today: 5,088 rows, 11 columns, max date 2026-07-31).",
        "     The scheduled weather DAG ALREADY passes --reconcile-schema-widen on all three sources in",
        "     both its shadow and canonical phases (dag_schedules.auto.tfvars.json), so the scheduled",
        "     path needs no change; these two submits exist only to force the order now.",
        "",
        "     The column is HIDDEN in the contract (glue_type null), so NO Glue ALTER is needed and the",
        "     generated DDL is unchanged -- the gold reader reads S3 parquet with pyarrow, never Athena.",
        "",
        "  3. RE-READ THE TIP BEFORE BACKFILLING, AND NOTE WHAT ALREADY CHANGED. MEASURED 2026-09-15",
        "     by HTTP HEAD: the 2026-08 FINAL block HAS LANDED -- all 31 days 200, Last-Modified",
        "     'Fri, 11 Sep 2026 21:10:09 GMT'..'21:10:59 GMT', ONE block write at +11 days past",
        "     month-end and HOURS AFTER the 09-11 probe that recorded it absent. So the prelim BACKFILL",
        "     below is probably UNNECESSARY: the ordinary 08:00Z DAG re-reads the current and previous",
        "     month unconditionally and will pick the finals up. Run --step CENSUS and read the [source]",
        "     block before spending anything -- final PUBLISHED means backfill nothing.",
        "",
        "  4. THE 2026-08 PRELIM BACKFILL, if the final has still not landed. FULL containerOverrides,",
        "     because chirps-to-bronze-backfill has NO --force_overwrite Ref and DEFAULTS",
        "     commodity=corn_cbot year=1981 -- a --parameters submit that omits the overrides runs a",
        "     1981 corn backfill. (That is now SAFE rather than merely wrong: 1981 is outside",
        "     PRELIM_MONTH_REACH, so the fetcher cannot reach the prelim archive for it and history",
        "     cannot move. It is still not the job you meant to run.) ONDEMAND QUEUE:",
        "",
        "  MSYS_NO_PATHCONV=1 aws batch submit-job --region us-east-1 \\",
        "    --job-name chirps-prelim-backfill-2026 \\",
        "    --job-queue leviathan-dev-queue-ondemand \\",
        "    --job-definition leviathan-dev-chirps-to-bronze-backfill:<NEW REV> \\",
        "    --container-overrides file://chirps_prelim.json",
        "",
        "    chirps_prelim.json (a FILE, not an inline string: PowerShell 5.1 mangles embedded double",
        "    quotes on their way to a native exe):",
        "",
        '      {"command":["jobs/batch/chirps_to_bronze_task.py",',
        '                  "--commodity","all","--year","2026",',
        '                  "--bucket","leviathan-dev-shahem-001","--aws_region","us-east-1"]}',
        "",
        "    NOTE: no --force_overwrite. The current and previous month are unconditional in the shipped",
        "    window, so the plain form already re-reads August; forcing would only add the ten elapsed",
        "    months of 2026 that are outside the prelim reach and cost 404s.",
        "",
        "  5. THEN b2s (W2(b)), then the compaction of step 2, then gold (W4's hand submit), then",
        "     --step CENSUS again.",
        "",
        "     WHAT GOLD GROWS BY, so the next reader does not meet it as a surprise on a hand-loaded",
        "     mirror. _drought_z emits ONE preliminary stamp per EMITTED drought_z row -- including a",
        "     0.0 for every all-final month back to 1981, which is the frost_event_flag precedent and",
        "     is what keeps the two sets from ever diverging. MEASURED 2026-09-15 by reading the live",
        "     objects (read-only), one commodity of each shape:",
        "       gold/weather_z/corn_cbot.parquet                 45,096 rows, drought_z 7,368",
        "         -> +7,368 stamp rows = ~52,464, +16.3% (no aggregate grain on this commodity)",
        "       gold/weather_z/malaysian_crude_palm_oil_cme.pq   33,103 rows, drought_z 3,991,",
        "         drought_z_cells 921 -> +3,991 flag + 921 _preliminary_share + 921",
        "         _is_preliminary_cells = ~38,936, +17.6%",
        "     Call it ~+16-18% on every weather_z object. Every one of those rows is then COPYed into",
        "     pg by step 6, on a mirror with autoscaling OFF -- which is why it is stated here as a",
        "     number and not left to be discovered at COPY time.",
        "",
        "  6. RELOAD THE PG MIRROR -- NOT OPTIONAL, AND IT IS WHAT CLOSES A RED WINDOW THIS LANE",
        "     DELIBERATELY OPENED. gold_weather_z is served from the pg mirror",
        "     (GRAPHRAG_NUMBERS_BACKEND=pg) and the mirror is HAND-LOADED -- there is no load schedule",
        "     (owner docket). numbers/contract_check.check_metric_vocabulary asserts, for every TALL",
        "     table, that each metric the card declares appears in DISTINCT(metric_col) ON THE MIRROR",
        "     -- 'declared-but-zero-row -- the drought_z class' -- and jobs/audit/feature_readiness.py",
        "     runs it live in-VPC with gold_weather_z inside its probed set. So from the moment the",
        "     card edit lands until this step completes, that check prints EXACTLY THREE errors:",
        "",
        "       gold_weather_z: metric 'drought_z_is_preliminary' not in DISTINCT metric of",
        "         gold_weather_z (declared-but-zero-row -- the drought_z class)        [+ the other two]",
        "",
        "     THAT IS THE EXPECTED STATE, not a defect, and it is the reason the card's edit is",
        "     sequenced with this step rather than left to a later sitting: a declared metric with no",
        "     rows is precisely the class that checker is named after, and the only honest way to carry",
        "     it is to NAME the window and close it here. The reload:",
        "",
        "       cd C:\\Users\\User\\Desktop\\Leviathan; python jobs/submit/submit_batch_load_numbers_pg.py --tables gold_weather_z",
        "",
        "     (ondemand queue + the evidence-build jobdef are hardcoded in the submitter; it runs",
        "     IN-VPC because the RDS SG admits the Batch SGs.) TWO THINGS MUST BE TRUE BEFORE IT RUNS,",
        "     and both are silent failures if they are not:",
        "       (a) GOLD MUST ALREADY CARRY THE ROWS (step 5). The loader reads S3 parquet, not Athena;",
        "           a reload before the gold recompute mirrors the old roster and the three errors",
        "           stay red with no hint that the reload was premature.",
        "       (b) THE LOADER'S OWN IMAGE MUST CARRY THE NEW CARD. load_pg_numbers filters every TALL",
        "           table to `field(metric_col).isin(ts.metrics)` (load_pg_numbers.py:608-629), and",
        "           ts.metrics comes from configs/graphrag/numbers/tables.yaml BAKED INTO THE IMAGE THE",
        "           LOADER RUNS IN -- the leviathan-dev-evidence-build jobdef, a FOURTH jobdef beyond",
        "           the three in step 1. On a pre-card image the filter DROPS all three new metrics and",
        "           the mirror comes back without them, which looks exactly like a producer that did",
        "           not write them.",
        "     Then re-run the contract check (or the feature-readiness probe) and confirm the three",
        "     errors are GONE. If they are not, read (a) and (b) before touching the producer.",
        "",
        "  7. ONLY NOW THE LAG. configs/graphrag/numbers/tables.yaml keeps drought_z at 25 as this lane",
        "     ships. The flip to 7 has a HARD PRECONDITION and it is a census read, not a date:",
        "",
        "       --step CENSUS must print   drought_z   tip=202608   BEFORE the card moves.",
        "",
        "     _ym_lagged_asof_ym admits month M when asof >= month_end(M) + lag, so 25 -> 7 admits",
        "     2026-08 from 2026-09-07 instead of 09-25. Flipping first makes the guard promise a month",
        "     the bytes do not hold -- byte for byte the defect 29de55eb was written to close.",
        "     When it moves, ALL SIX drought_z* entries move in ONE edit (check_metric_lags clause 4",
        "     forces the siblings, clause 5 forbids silent inheritance):",
        "       drought_z, drought_z_tail_share, drought_z_cells,",
        "       drought_z_is_preliminary, drought_z_preliminary_share, drought_z_is_preliminary_cells",
        "     and 25 survives in the card's prose as the FINAL product's REVISION HORIZON.",
        "     Then RUN THE LINT BY HAND -- it is still not wired into config_check.main:",
        "",
        "       cd C:\\Users\\User\\Desktop\\Leviathan; python -c \"from leviathan.graphrag.numbers.registry import check_metric_lags;"
        " print(check_metric_lags())\"",
        "",
        "  8. WHAT STAYS OPEN, so it is not read as covered: a month that leaves the prelim reach still",
        "     carrying preliminary days is never re-checked again, and _drought_runs' trailing baseline",
        "     is product-blind -- so such a month would feed prelim values into every future year's",
        "     baseline for that (region, month). The bronze _meta.json now COUNTS prelim_days per",
        "     partition, which is the raw material for that alarm. OWNER: the orchestrator, triggered by",
        "     the first Fargate run's prelim_days / fetch_failures reading after the deploy (docketed",
        "     2026-09-15); until it is built, the per-partition count IS the instrument.",
        "",
        "     AND TWO MORE, each named rather than left for a reader to discover:",
        "",
        "     (i) THE STAMP HAS NO SERVING CONSUMER YET, and 'produced' must not be read as",
        "         'surfaced'. MEASURED 2026-09-15 by grep over src/ and configs/: the name",
        "         drought_z_is_preliminary appears in EXACTLY THREE places -- the producer",
        "         (transforms/gold/weather_z.py), the numbers card and source_contracts.yaml. Nothing",
        "         under src/leviathan/graphrag reads it, so a preliminary drought reading is served in",
        "         the same voice as a final one and its provenance lives only in the table. The two",
        "         places a consumer would have to learn it are both FIXED weather-metric rosters on the",
        "         serving side -- numbers/cascade.py:1082 _BASIN_TAIL_METRICS and the metric list in",
        "         state/__main__.py:359-360 -- and both belong to the state-engine lane, which is why",
        "         this lane wrote the producer and not the narration.",
        "",
        "     (ii) ONE FAILED OPEN IS NOW A WHOLE-RUN LOSS OF THAT DAY. The daily task's",
        "          _DayRasterCache keyed the fetch by COORDINATE so each raster is opened once per run",
        "          across all 31 commodities -- and it caches the FAILURE too, deliberately, because a",
        "          retry-per-commodity would re-pay a 57.6 MB inflation 31 times for a host that has",
        "          already refused us. The consequence is the trade: pre-lane, a transport failure cost",
        "          ONE commodity that day and the other 30 still had their own chances; now it costs",
        "          the day for ALL of them. That is exactly the failure the measurement above found (17",
        "          of 31 August opens dying on TIFFReadDirectory), so read fetch_failures in _meta.json",
        "          after the first fleet run and treat a non-empty map as a RE-RUN signal, not a note.",
        "          (absent_days will NOT tell you: as of this lane it counts SOURCE absence only -- a",
        "          404 on both products -- and a raising day is booked in fetch_failures and nowhere",
        "          else, so the three product counts need not sum to the calendar month.)",
        "",
        "     (iii) DO NOT SMOKE bronze_to_silver_chirps_task.py WITH --help. MEASURED 2026-09-15: that",
        "           entrypoint has no argparse at all -- BaseBronzeToSilverJob.run_thin_contract scans",
        "           raw argv, so `--help` is an UNRECOGNISED TOKEN, not a request. commodity falls back",
        "           to 'all', bucket/aws_region fall back to $LEVIATHAN_BUCKET/$AWS_REGION from .env,",
        "           and the process goes straight into _discover_commodities and RUNS THE REAL",
        "           BRONZE->SILVER JOB against the real bucket. Driven with _discover_commodities",
        "           stubbed: it was reached in 0.02 s with ('leviathan-dev-shahem-001', 'us-east-1');",
        "           the module IMPORT is only 1.6 s, so a `--help` that appears to hang is not a slow",
        "           import, it is a producer running. jobs/batch/cpc_bronze_to_silver_task.py is the",
        "           same shape. The fix belongs in src/leviathan/storage/base_jobs.py (one help guard in",
        "           run_thin_contract covers every thin-contract entrypoint) and is OUTSIDE this lane's",
        "           file set; until it lands, submit that job to Batch (step 5 / --parameters) and never",
        "           probe it locally. This is the 09-11 breach class arriving through a SMOKE.",
    ]),
]


# ---------------------------------------------------------------------------
# --step CENSUS -- the $0 read-only measurement
# ---------------------------------------------------------------------------
def _census(commodity: str = "corn_cbot") -> int:
    """Per-layer data tips for one commodity + the CHIRPS source HEAD probe. READ-ONLY."""
    import io

    import boto3
    import pandas as pd

    s3 = boto3.client("s3", region_name=REGION)
    print(f"CENSUS  bucket={BUCKET}  commodity={commodity}   (LIST/HEAD/GET only)")
    print()

    # --- GOLD: the served card ------------------------------------------------------------------
    gold_key = f"gold/weather_z/{commodity}.parquet"
    print(f"[gold]   {gold_key}")
    try:
        head = s3.head_object(Bucket=BUCKET, Key=gold_key)
        body = s3.get_object(Bucket=BUCKET, Key=gold_key)["Body"].read()
        gold = pd.read_parquet(io.BytesIO(body))
        sys.path.insert(0, str(REPO))
        from leviathan.transforms.gold.weather_z import metric_tip_ym, months_behind
        tips = metric_tip_ym(gold)
        # THE PROMISE IS PER METRIC (fixed 2026-09-15). This read used to take
        # ``getattr(ts, "ym_publication_lag_days")`` -- the CARD DEFAULT, which is the NASA POWER value
        # of 5 -- and print it for every metric including drought_z, whose own declared lag is 25. So
        # the instrument the operator verifies the lane WITH disagreed with the producer's own tripwire,
        # which has read ``lag_days_for`` since 29de55eb. One function, one precedence, both seats.
        claimed: dict = {}
        try:
            from datetime import datetime, timezone

            from leviathan.graphrag.numbers.query import _ym_lagged_asof_ym
            from leviathan.graphrag.numbers.registry import lag_days_for, load_registry
            ts = load_registry().get("gold_weather_z")
            # UTC, matching the producer's counter and the gate's stage -- a census that read the
            # operator's LOCAL date would print a different promise than the job it is checking.
            asof = datetime.now(timezone.utc).date().isoformat()
            for metric in tips:
                lag = lag_days_for(ts, metric)
                claimed[metric] = _ym_lagged_asof_ym(asof, lag) if lag else None
        except Exception as exc:  # noqa: BLE001
            print(f"         (card promise unreadable: {type(exc).__name__}: {exc})")
        print(f"         object mtime {head['LastModified']}  {head['ContentLength']:,} B  "
              f"{len(gold):,} rows")
        for metric in sorted(tips):
            promise = claimed.get(metric)
            behind = months_behind(promise, tips[metric])
            flag = "" if behind in (0, None) else f"   <-- {behind} month(s) BEHIND"
            print(f"         {metric:32s} tip={tips[metric]}  "
                  f"card promises {promise if promise else 'undeclared'}{flag}")
        prelim = tips.get("drought_z_is_preliminary")
        if prelim is not None:
            share = gold[gold["metric"] == "drought_z_is_preliminary"]["value"]
            print(f"         PROVENANCE: {float(share.mean()) * 100:.1f}% of drought_z cell-months "
                  f"across the whole object were built from PRELIM bytes and will be RECOMPUTED "
                  f"when their FINAL block lands")
        else:
            print("         PROVENANCE: no drought_z_is_preliminary rows -- this object predates the "
                  "prelim lane's producer (or its silver has not been recompacted yet)")
    except Exception as exc:  # noqa: BLE001
        print(f"         UNREADABLE: {type(exc).__name__}: {exc}")
    print()

    # --- SILVER: both feeders -------------------------------------------------------------------
    for source, col in (("nasa_power", None), ("chirps", None)):
        prefix = f"silver/weather/source={source}/commodity={commodity}/"
        print(f"[silver] {prefix}")
        try:
            objs = _list(s3, prefix, ".parquet")
            if not objs:
                print("         NO OBJECTS")
                continue
            newest = max(objs, key=lambda kv: kv[1])
            body = s3.get_object(Bucket=BUCKET, Key=newest[0])["Body"].read()
            df = pd.read_parquet(io.BytesIO(body))
            tip = None
            if "date" in df.columns:
                tip = str(pd.to_datetime(df["date"], errors="coerce").max())[:10]
            print(f"         {len(objs)} object(s); newest {newest[0].rsplit('/', 2)[-2]}/"
                  f"{newest[0].rsplit('/', 1)[-1]} mtime {newest[1]}")
            print(f"         newest object: {len(df):,} rows, max(date)={tip}")
        except Exception as exc:  # noqa: BLE001
            print(f"         UNREADABLE: {type(exc).__name__}: {exc}")
        print()

    # --- BRONZE: the freeze itself --------------------------------------------------------------
    for source in ("nasa_power", "chirps"):
        prefix = f"bronze/weather/source={source}/commodity={commodity}/"
        print(f"[bronze] {prefix}")
        try:
            objs = _list(s3, prefix, ".parquet")
            by_month: dict[str, tuple] = {}
            for key, mtime in objs:
                seg = [p for p in key.split("/") if p.startswith(("year=", "month="))]
                ym = "/".join(seg)
                if ym not in by_month or mtime > by_month[ym][1]:
                    by_month[ym] = (key, mtime)
            recent = sorted(k for k in by_month if "year=2026" in k)[-4:]
            for ym in recent:
                key, mtime = by_month[ym]
                body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
                df = pd.read_parquet(io.BytesIO(body))
                value_col = "precipitation_mm" if source == "chirps" else None
                if value_col and value_col in df.columns:
                    obs = int(df[value_col].notna().sum())
                    print(f"         {ym:20s} mtime {mtime}  {len(df):3d} rows, "
                          f"{obs:3d} OBSERVED days")
                else:
                    print(f"         {ym:20s} mtime {mtime}  {len(df):3d} rows")
        except Exception as exc:  # noqa: BLE001
            print(f"         UNREADABLE: {type(exc).__name__}: {exc}")
        print()

    # --- the CHIRPS source itself ---------------------------------------------------------------
    # BOTH PRODUCTS (2026-09-15). Probing only the FINAL made a month the estate CAN now serve look
    # exactly like a month it cannot: the final 404s either way, and the prelim is what decides.
    print("[source] CHIRPS v2.0 daily tifs -- FINAL block, and the PRELIM behind it")
    try:
        import urllib.request
        from datetime import date
        today = date.today()
        base = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/tifs/p05"
        prelim_base = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/prelim/global_daily/tifs/p05"

        def _head(url: str) -> str:
            req = urllib.request.Request(url, method="HEAD")
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    stamp = resp.headers.get("Last-Modified", "")
                    return f"HTTP {resp.status}  PUBLISHED  {stamp}"
            except Exception as exc:  # noqa: BLE001
                return f"HTTP {getattr(exc, 'code', type(exc).__name__)}  not published"

        probes = []
        for back in (1, 2):
            y, m = (today.year, today.month - back) if today.month > back else \
                   (today.year - 1, today.month - back + 12)
            for day in (1, calendar.monthrange(y, m)[1]):
                probes.append((y, m, day))
        for y, m, d in probes:
            name = f"chirps-v2.0.{y}.{m:02d}.{d:02d}.tif.gz"
            print(f"         {y}-{m:02d}-{d:02d}  final   {_head(f'{base}/{y}/{name}')}")
            print(f"                     prelim  {_head(f'{prelim_base}/{y}/{name}')}")
    except Exception as exc:  # noqa: BLE001
        print(f"         source probe failed: {type(exc).__name__}: {exc}")
    print()
    print("READ IT THIS WAY: a bronze month whose OBSERVED day count is short of its calendar")
    print("length, beside a source probe that says PUBLISHED, is a bronze the daily run must")
    print("refresh -- and before this wave it never would have.")
    print("AND READ THE TWO PRODUCTS TOGETHER: final PUBLISHED means the month is authoritative and")
    print("any preliminary rows for it are due to be SUPERSEDED on the next fetch; final absent +")
    print("prelim PUBLISHED means drought_z can be served now, stamped preliminary; both absent means")
    print("the source has published nothing and the honest serve is the previous month.")
    return 0


def _list(s3, prefix: str, suffix: str) -> list:
    out = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(suffix):
                out.append((obj["Key"], obj["LastModified"]))
    return out


# ---------------------------------------------------------------------------
# --step CHECK -- the offline preflight
# ---------------------------------------------------------------------------
def _json_blocks(lines: list[str]) -> list[str]:
    """Every brace-balanced JSON body embedded in a step's printed lines.

    A step that hands the operator a ``--container-overrides file://x.json`` body is handing them
    something that must PARSE. Collecting the blocks mechanically -- open at a line whose first
    non-space character is ``{``, close when the braces balance -- means the preflight checks the exact
    bytes the operator will copy, not a restatement of them."""
    blocks, buf, depth = [], [], 0
    for line in lines:
        if not buf and not line.lstrip().startswith("{"):
            continue
        buf.append(line)
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            blocks.append("\n".join(buf))
            buf, depth = [], 0
    return blocks


def _is_local_producer_line(stripped: str) -> bool:
    """True when a printed line would run a jobs/batch producer LOCALLY: a bare `python jobs/batch/...`,
    the house form `cd C:\\...\\Leviathan; python jobs/batch/...`, `py jobs/batch/...`, or any of those
    after `;`, `&`, `|`. Backticked prose and `python -m` module spellings are not caught here."""
    return re.search(r"(^|[;&|]\s*)(python|py)\s+jobs/batch/", stripped) is not None



def _run_check() -> int:
    failures: list[str] = []

    print("[1/5] every touched file is present")
    for rel in TOUCHED:
        ok = (REPO / rel).exists()
        print(f"      {'OK ' if ok else 'MISSING'} {rel}")
        if not ok:
            failures.append(f"missing {rel}")

    print("[2/5] ruff on the touched files")
    # STANDING CONDITION, MEASURED, NOT WAIVED BLIND: these files carried I001 (isort) findings at
    # HEAD before this wave -- the whole repo does, including files this lane never opened
    # (tests/unit/test_gold_weather_z.py:8 is one). A preflight that reds on them reds on the tree it
    # inherited, not on this change, and would teach an operator to ignore it. So I001 is COUNTED and
    # PRINTED, and only a finding of any OTHER rule is a failure.
    # `--output-format text` is pinned because this repo runs ruff 0.1.6, whose enum has no
    # `concise` member -- passing one exits 2 with an EMPTY stdout, which parses as "no findings" and
    # would have turned a broken lint command into a GREEN preflight. READ EVERY EXIT CODE: 0 and 1
    # are ruff's verdicts (clean / findings); anything else is ruff itself refusing to run, and that
    # is a failure of the check, never a pass.
    proc = subprocess.run([sys.executable, "-m", "ruff", "check", "--output-format", "text", *TOUCHED],
                          cwd=REPO, capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        print(f"      ruff DID NOT RUN (exit={proc.returncode}): "
              f"{(proc.stderr or proc.stdout).strip().splitlines()[:2]}")
        failures.append(f"ruff did not run (exit={proc.returncode})")
    else:
        findings = [ln for ln in proc.stdout.splitlines() if ln.strip() and ln[0] not in " [F"]
        isort = [ln for ln in findings if " I001 " in ln]
        other = [ln for ln in findings if " I001 " not in ln]
        print(f"      ruff exit={proc.returncode}; {len(isort)} standing I001 (pre-existing repo "
              f"style), {len(other)} other")
        for ln in other:
            print(f"      {ln}")
        if other:
            failures.append(f"ruff: {len(other)} non-I001 finding(s)")

    print("[3/5] every touched Batch entrypoint imports and parses args")
    for entry in ("jobs/batch/chirps_to_bronze_task.py",
                  "jobs/batch/chirps_year_to_bronze_task.py",
                  "jobs/batch/gold_weather_z_task.py",
                  "jobs/batch/compact_weather_silver_task.py"):
        # A thin-contract entrypoint has NO argparse: its --help falls through to the producer and
        # runs against the real bucket (W6 step 8 (iii); bronze_to_silver_chirps_task.py measured
        # 2026-09-15). Refuse to smoke such a file, and bound every smoke so PREFLIGHT can never
        # become an unbounded producer run.
        src = (REPO / entry).read_text(encoding="utf-8", errors="replace")
        if "argparse" not in src:
            print(f"      {entry} has no argparse -- NOT smoked (--help would run the producer)")
            failures.append(f"{entry}: no argparse; --help is a producer run, not a smoke")
            continue
        try:
            rc = subprocess.run([sys.executable, str(REPO / entry), "--help"], cwd=REPO,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=60).returncode
        except subprocess.TimeoutExpired:
            rc = "TIMEOUT(60s)"
        print(f"      {entry} --help exit={rc}")
        if rc != 0:
            failures.append(f"{entry} --help exit={rc}")

    print("[4/5] the decks")
    rc = subprocess.run([sys.executable, "-m", "pytest", *DECKS, "-q"], cwd=REPO).returncode
    print(f"      pytest exit={rc}")
    if rc != 0:
        failures.append(f"pytest exit={rc}")

    # RUNNABILITY LINT on the paste-ready bodies (the ALARM RCA class: a printed command that cannot
    # run is worse than no command, because it is copied at 2am and its failure is read as the estate's).
    # Every --container-overrides body printed by a step must PARSE and must name a command array whose
    # first element is a task file that exists in this tree.
    print("[5/5] every printed JSON override parses and names a real entrypoint")
    checked = 0
    for name, _title, lines in STEPS:
        for block in _json_blocks(lines):
            checked += 1
            try:
                obj = json.loads(block)
            except Exception as exc:  # noqa: BLE001 -- an unparseable body is the failure being caught
                print(f"      {name} INVALID JSON: {type(exc).__name__}: {exc}")
                failures.append(f"{name}: unparseable JSON override")
                continue
            cmd = obj.get("command")
            if not isinstance(cmd, list) or not cmd:
                print(f"      {name} override has no command array")
                failures.append(f"{name}: override without a command array")
                continue
            entry = cmd[0]
            ok = (REPO / entry).exists()
            print(f"      {'OK ' if ok else 'MISSING'} {name} -> {entry}")
            if not ok:
                failures.append(f"{name}: override names a missing entrypoint {entry}")
    print(f"      {checked} JSON override(s) checked")

    # ...AND NO STEP MAY HAND THE OPERATOR A LOCAL PRODUCER RUN. A `python jobs/batch/<x>_task.py`
    # line pasted at 2am executes against the REAL bucket from a laptop -- the 09-11 breach class, and
    # the exact thing an earlier cut of W6 step 2 printed. Producers are submitted to Batch; the only
    # jobs/ paths a printed line may name are the ones INSIDE a containerOverrides command array,
    # which the loop above already checks.
    # The predicate must see the HOUSE FORM -- every handed command starts with
    # `cd C:\\Users\\User\\Desktop\\Leviathan;` (owner word 09-11) -- so a bare startswith("python ")
    # is blind to exactly the line an operator would paste. Close-out 2026-09-15: the fence's own
    # blind spot is driven below, so a regression here reddens PREFLIGHT rather than printing GREEN.
    _blind_spot = [
        ("cd C:\\Users\\User\\Desktop\\Leviathan; python jobs/batch/compact_weather_silver_task.py --x", True),
        ("python jobs/batch/chirps_to_bronze_task.py --month 2026-08", True),
        ("py jobs/batch/gold_weather_z_task.py", True),
        ("echo ok; python -m jobs.batch.gold_weather_z_task", False),   # module form is not a file path
        ("`python jobs/batch/x_task.py` is what the jobdef runs", False),  # backticked prose
    ]
    for probe, want in _blind_spot:
        got = _is_local_producer_line(probe)
        if got != want:
            failures.append(f"producer-ban fence blind: {probe[:60]!r} -> {got}, expected {want}")
    banned = []
    for name, _title, lines in STEPS:
        for line in lines:
            stripped = line.strip()
            if _is_local_producer_line(stripped):
                banned.append(f"{name}: local producer run printed -- {stripped[:70]}")
    print(f"      {len(banned)} local producer command(s) printed (must be 0)")
    for b in banned:
        print(f"      {b}")
    failures.extend(banned)

    print()
    if failures:
        print("PREFLIGHT RED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PREFLIGHT GREEN -- W1 may proceed.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="gold_weather_z freshness runbook (dry run)")
    ap.add_argument("--step", default=None,
                    help="print one step; CHECK runs the offline preflight; CENSUS runs the $0 census")
    ap.add_argument("--commodity", default="corn_cbot", help="commodity for --step CENSUS")
    ap.add_argument("--list", action="store_true", help="just the step names")
    args = ap.parse_args()

    if args.list:
        for name, title, _ in STEPS:
            print(f"{name:8s} {title}")
        print(f"{'CHECK':8s} RUN the offline preflight (ruff + --help + the decks)")
        print(f"{'CENSUS':8s} RUN the $0 read-only per-layer census + the CHIRPS source probe")
        return 0

    if args.step and args.step.upper() == "CHECK":
        return _run_check()
    if args.step and args.step.upper() == "CENSUS":
        return _census(args.commodity)

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
