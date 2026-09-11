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
        "    COST SHAPE, so this is a decision and not a reflex: --force_overwrite re-downloads EVERY",
        "    elapsed month of 2026 for EVERY region of EVERY commodity from the UCSB server (5 threads,",
        "    jobdef rev 19 = 0.5 vCPU / 1024 MB). Drop --force_overwrite and pass --year 2026 alone to",
        "    let the completeness test decide which months are actually short.",
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
        claimed = None
        try:
            from datetime import datetime, timezone

            from leviathan.graphrag.numbers.query import _ym_lagged_asof_ym
            from leviathan.graphrag.numbers.registry import load_registry
            lag = getattr(load_registry().get("gold_weather_z"), "ym_publication_lag_days", None)
            # UTC, matching the producer's counter and the gate's stage -- a census that read the
            # operator's LOCAL date would print a different promise than the job it is checking.
            asof = datetime.now(timezone.utc).date().isoformat()
            claimed = _ym_lagged_asof_ym(asof, lag) if lag else None
        except Exception as exc:  # noqa: BLE001
            print(f"         (card promise unreadable: {type(exc).__name__}: {exc})")
        print(f"         object mtime {head['LastModified']}  {head['ContentLength']:,} B  "
              f"{len(gold):,} rows")
        print(f"         card promises data month: {claimed if claimed else 'undeclared'}")
        for metric in sorted(tips):
            behind = months_behind(claimed, tips[metric])
            flag = "" if behind in (0, None) else f"   <-- {behind} month(s) BEHIND"
            print(f"         {metric:28s} tip={tips[metric]}{flag}")
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
    print("[source] CHIRPS v2.0 daily tifs -- is the block published yet?")
    try:
        import urllib.request
        from datetime import date
        today = date.today()
        base = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/tifs/p05"
        probes = []
        for back in (1, 2):
            y, m = (today.year, today.month - back) if today.month > back else \
                   (today.year - 1, today.month - back + 12)
            for day in (1, calendar.monthrange(y, m)[1]):
                probes.append((y, m, day))
        for y, m, d in probes:
            url = f"{base}/{y}/chirps-v2.0.{y}.{m:02d}.{d:02d}.tif.gz"
            req = urllib.request.Request(url, method="HEAD")
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    print(f"         {y}-{m:02d}-{d:02d}  HTTP {resp.status}  PUBLISHED")
            except Exception as exc:  # noqa: BLE001
                code = getattr(exc, "code", type(exc).__name__)
                print(f"         {y}-{m:02d}-{d:02d}  HTTP {code}  not published")
    except Exception as exc:  # noqa: BLE001
        print(f"         source probe failed: {type(exc).__name__}: {exc}")
    print()
    print("READ IT THIS WAY: a bronze month whose OBSERVED day count is short of its calendar")
    print("length, beside a source probe that says PUBLISHED, is a bronze the daily run must")
    print("refresh -- and before this wave it never would have.")
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
                  "jobs/batch/gold_weather_z_task.py"):
        rc = subprocess.run([sys.executable, str(REPO / entry), "--help"], cwd=REPO,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
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
