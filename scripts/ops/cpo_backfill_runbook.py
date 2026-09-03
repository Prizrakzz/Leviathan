#!/usr/bin/env python
"""V2-4 CPO backfill RUNBOOK -- prints the exact command for each step and, for the two steps a
human cannot eyeball (D7's partition count and the partial-registration rollback), RUNS the check.

    python scripts/ops/cpo_backfill_runbook.py                     # print every step's commands
    python scripts/ops/cpo_backfill_runbook.py --step D7-CHECK     # glue partition count == units
    python scripts/ops/cpo_backfill_runbook.py --step ROLLBACK     # enumerate the registered
                                                                   # subset; print delete commands
    python scripts/ops/cpo_backfill_runbook.py --step ROLLBACK --run   # ... and execute them

Nothing here submits a Batch job, buys data or writes canonical: every mutating command is printed
for the operator to paste (the estate's runbook idiom -- dmw_p2_deploy.py's dry-run-by-default,
``--run`` to mutate, refuse anything else). The ONLY mutation this script can perform itself is the
ROLLBACK under ``--run``: ``glue batch-delete-partition`` over the EXACT registered subset for the
palm slug + ``s3 rm`` of those partition objects -- which is M6's finding: a canonical backfill can
register N < unit-count partitions and still exit 1, so 'delete a fixed list of 11' is wrong and
the subset must be ENUMERATED from Glue at rollback time.

D7 (V2-4 M6): the canonical backfill is GREEN only when the job's rc is 0 AND
``glue get-partitions`` for leviathan_slug='malaysian_crude_palm_oil_cme' counts exactly
len(root_years('CPO', <this year>)) partitions (11 for 2016..2026). rc 1 with ANY partition
registered = enumerate the subset, roll it back, re-run.

D6b / D8 (STEP-12 F7): gate 9 (month continuity) judges EVERY Databento root, and the 15 shipped
roots' continuity has never been measured -- so the harness runs ONCE on the canonical prefix
BEFORE promote (D6b, beside D6) to record the ESTATE's pre-state, and D8's gate 9 is SCOPED to the
slug this sitting touched (``--continuity-slug malaysian_crude_palm_oil_cme``). A hole D6b recorded
is the estate's and is never a K9 rollback of CPO.

ASCII-only output.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from leviathan.transforms.raw_to_bronze.databento_eod import root_years  # noqa: E402

REGION = "us-east-1"
BUCKET = "leviathan-dev-shahem-001"
ACCOUNT = "668891723125"
DB = "leviathan_dev"
TABLE = "silver_futures_eod"
SLUG = "malaysian_crude_palm_oil_cme"
ROOT = "CPO"
QUEUE = "leviathan-dev-queue-ondemand"
JD_FETCH = "leviathan-dev-databento-fetch"
JD_SILVER = "leviathan-dev-futures-eod-silver"
JD_GATE = "leviathan-dev-silver-gate"
RAW_PREFIX = f"raw/production/source=databento/dataset=glbx_mdp3/root={ROOT}/"
BASELINE = f"s3://{BUCKET}/cascade_census/rolling/futures_eod_databento/census.json"
SFN = f"arn:aws:states:{REGION}:{ACCOUNT}:stateMachine:leviathan-dev-silver-thin-contract"


def _units(year: int) -> list[int]:
    return root_years(ROOT, year)


def _submit(name: str, jobdef: str, command: list[str], extra: str = "") -> str:
    ov = json.dumps({"command": command})
    return (f"aws batch submit-job --job-name {name} --job-queue {QUEUE} --job-definition {jobdef} "
            f"--container-overrides '{ov}'{extra} --query jobId --output text")


def steps(year: int, run_id: str) -> list[tuple[str, list[str]]]:
    years = _units(year)
    n = len(years)
    half = years[: (n + 1) // 2]
    rest = years[(n + 1) // 2:]

    def _years(ys):
        out = []
        for y in ys:
            out += ["--year", str(y)]
        return out

    return [
        ("D0  record-count probe ($0; metadata endpoints are free) -- OPTIONAL instrument, on the "
         "OLD or NEW fetch jobdef via the S3-download idiom (overrides via file:// -- the python "
         "one-liner's own quotes cannot ride inside a shell-quoted JSON literal)", [
            f"aws s3 cp jobs/utils/cpo_databento_probe.py s3://{BUCKET}/probes/cpo_databento_probe.py",
            "cat > cpo_records_overrides.json <<'JSON'\n  " + json.dumps({"command": ["-c", (
                "import boto3,subprocess,sys; boto3.client('s3').download_file("
                f"'{BUCKET}','probes/cpo_databento_probe.py','/tmp/p.py'); "
                "sys.exit(subprocess.run([sys.executable,'/tmp/p.py','--asof','<today>',"
                "'--record-counts','--density-years','2016,2026','--suffix','_records'])"
                ".returncode)")]}) + "\n  JSON",
            f"MSYS_NO_PATHCONV=1 aws batch submit-job --job-name cpo-records --job-queue {QUEUE} "
            f"--job-definition {JD_FETCH} --container-overrides file://cpo_records_overrides.json "
            f"--query jobId --output text",
            f"aws s3 cp s3://{BUCKET}/probes/cpo_databento_probe_<YYYYMMDD>_records.json "
            f"data/batch_runs/cpo_databento_probe_<YYYYMMDD>_records.json",
        ]),
        ("D1  KP0 COST GATE = the F-A dry run, in-VPC on the NEW fetch revision; NOTHING submitted", [
            _submit("cpo-cost-only", JD_FETCH, ["jobs/ingest/fetch_databento_eod.py", "--mode",
                                                "backfill", "--root", ROOT, "--cost-only",
                                                "--max-usd", "0.50"]),
            "MSYS_NO_PATHCONV=1 aws logs filter-log-events --log-group-name /aws/batch/leviathan-dev "
            "--log-stream-name-prefix databento-fetch --filter-pattern 'GRAND TOTAL'",
            "# expect: ohlcv$ 0.0000 on every CPO row, statistics ~0.09, 11 rows (2016..2026),"
            " dropped > 0 on every row, exit 0; 'F-A VIOLATION' / 'STEP-2 FAILURE' / "
            "'GATE-2 PRECONDITION BREACH' ABSENT",
        ]),
        ("D2  THE BUY (~$0.09; idempotent per unit; statistics ONLY for the settlement-tape root) "
         "-- two parallel jobs so the 14400 s jobdef ceiling cannot bite", [
            _submit("cpo-backfill-a", JD_FETCH, ["jobs/ingest/fetch_databento_eod.py", "--mode",
                                                 "backfill", "--root", ROOT, *_years(half)]),
            _submit("cpo-backfill-b", JD_FETCH, ["jobs/ingest/fetch_databento_eod.py", "--mode",
                                                 "backfill", "--root", ROOT, *_years(rest)]),
            f"aws s3 ls s3://{BUCKET}/{RAW_PREFIX} --recursive",
            f"# expect exactly {n} symbology_CPO_YYYY.json + {n} statistics_CPO_YYYY.dbn.zst "
            f"(+ metadata companions), NO ohlcv-1d object; each log ends "
            f"'done -- units=N failures=0 thin_settlement_tape_payloads=0 "
            f"settlement_tape_skipped=0'",
            "# K6: in BACKFILL a thin/empty statistics payload is a FAILED unit (rc 1), never a "
            "skip -- any 'FAILED GLBX.MDP3 CPO/YYYY' line = STOP (the nightly's non-blocking "
            "fence is incremental-only)",
        ]),
        ("D3  SILVER DRY-RUN ($0; writes nothing) = the record-density + OI-coverage measurement "
         "AND the EXPECTED_BARS source", [
            _submit("cpo-silver-dryrun", JD_SILVER, ["jobs/batch/futures_eod_task.py", "--mode",
                                                     "backfill", "--root", ROOT,
                                                     "--publish-mode", "dry-run"]),
            f"# read the {n} 'unit GLBX.MDP3 CPO/YYYY: {{...}}' lines: rows_out, settlement_base "
            f"true, glbx_settle_coverage.settle_nonnull_frac >= 0.95, oi_keys_without_settle/rows "
            f"<= 0.01, rows_beyond_horizon 0, anchor_fallbacks 0 (every outright decoded on "
            f"its own resolved d0), no 'truncated download', no MONTH_CONTINUITY line",
            "# BANK rows_out per (CPO, year) into scripts/silver/futures_eod_gate.py EXPECTED_BARS "
            "on the 'silver' basis (2026 is in PARTIAL_YEARS) and EMPTY EXPECTED_BARS_PENDING; "
            "run tests/unit/silver/test_futures_eod_gate.py; commit",
        ]),
        ("D4  SHADOW (stages every (slug, trade_year) partition under the shadow prefix, no Glue)", [
            _submit("cpo-silver-shadow", JD_SILVER, ["jobs/batch/futures_eod_task.py", "--mode",
                                                     "backfill", "--root", ROOT,
                                                     "--publish-mode", "shadow", "--run-id",
                                                     run_id]),
            "# read 'publish shadow: source=databento state=... rows=N' and the shadow prefix;"
            f" COUNT(DISTINCT trade_year) == {n}; MIN(trade_date) WHERE settle IS NOT NULL >= "
            "2016-08-01",
        ]),
        ("D5  HARNESS on the SHADOW bytes with WAIVERS (M3: the shadow prefix carries only the CPO "
         "partitions, so gates 3/5/7 are structurally red there) + an explicit CPO row-count check", [
            f"python scripts/silver/futures_eod_gate.py --eod-uri <shadow prefix of {TABLE}> "
            f"--manifest-uri s3://{BUCKET}/raw/production/source=databento/ "
            f"--futures-prices-uri s3://{BUCKET}/silver/futures_prices/part-000.parquet "
            f"--aws-region {REGION} --skip 3 --skip 5 --skip 7",
            "# gates 1/2/4/6/8/9 must PASS (9 = month continuity); the report records waived [3,5,7]",
            "# CPO row count on the shadow == the sum of the D3 rows_out (pyarrow over the shadow "
            "objects or an Athena COUNT(*) on an external table)",
        ]),
        ("D6  GATE #1 (pre-state; the scheduled gate reads CANONICAL via the pg reload) -- must be "
         "GREEN before canonical is touched", [
            _submit("cpo-gate-pre", JD_GATE, ["-m", "jobs.audit.silver_rebuild_gate", "--tables",
                                              TABLE, "--asof", "<UTC ISO now>", "--baseline-uri",
                                              BASELINE]),
        ]),
        ("D6b PRE-STATE HARNESS on the CANONICAL prefix, BEFORE any palm byte lands (STEP-12 F7): "
         "gate 9 judges every Databento root and the 15 shipped roots' month continuity has NEVER "
         "been measured (KE from 2014, ICE from 2018-12-24, ZR's thin years) -- a hole here is the "
         "ESTATE's, recorded now so D8 can never mistake it for the sitting's", [
            f"python scripts/silver/futures_eod_gate.py --eod-uri s3://{BUCKET}/silver/futures_eod/ "
            f"--manifest-uri s3://{BUCKET}/raw/production/source=databento/ "
            f"--futures-prices-uri s3://{BUCKET}/silver/futures_prices/part-000.parquet "
            f"--aws-region {REGION} --skip 3 | tee data/batch_runs/cpo_gate_pre_state_<YYYYMMDD>.txt",
            "# read GATE 9 (gate 3 is waived here by design: CPO's D3-banked rows are not yet "
            "canonical). PASS = the estate is continuous and D8 may run gate 9 UNSCOPED; FAIL "
            "naming <root>/<slug> months = pre-existing estate holes: bank the artifact, docket "
            "the holes, and run D8 SCOPED to the palm slug (as printed). Never roll CPO back for "
            "a hole this step recorded before D7",
        ]),
        ("D7  PROMOTE = CANONICAL from Batch, KMS-signed (the DAG's own promote leg on the digest-"
         "pinned silver jobdef; env pair baked). OWNER GO applies only if D5 and D6 PASSED", [
            _submit("cpo-silver-canonical", JD_SILVER, ["jobs/batch/futures_eod_task.py", "--mode",
                                                        "backfill", "--root", ROOT,
                                                        "--publish-mode", "canonical",
                                                        "--run-id", run_id]),
            "aws batch describe-jobs --jobs <jobId> --query 'jobs[0].{status:status,rc:container."
            "exitCode}'",
            f"python scripts/ops/cpo_backfill_runbook.py --step D7-CHECK   "
            f"# rc 0 AND get-partitions count == {n}; rc 1 with ANY partition registered -> ROLLBACK",
        ]),
        ("D7r ROLLBACK of a partial/failed canonical (M6): enumerate the REGISTERED subset, delete "
         "exactly that set, re-run D6 to reload the pg mirror", [
            "python scripts/ops/cpo_backfill_runbook.py --step ROLLBACK        # print",
            "python scripts/ops/cpo_backfill_runbook.py --step ROLLBACK --run  # execute (owner)",
        ]),
        ("D8  FULL HARNESS on the CANONICAL prefix (no waivers; rollback above = the stop) + GATE #2 "
         "= KP4. Gate 9 is SCOPED to the slug this sitting touched (STEP-12 F7); drop the "
         "--continuity-slug ONLY if D6b's gate 9 PASSED unscoped", [
            f"python scripts/silver/futures_eod_gate.py --eod-uri s3://{BUCKET}/silver/futures_eod/ "
            f"--manifest-uri s3://{BUCKET}/raw/production/source=databento/ "
            f"--futures-prices-uri s3://{BUCKET}/silver/futures_prices/part-000.parquet "
            f"--aws-region {REGION} --continuity-slug {SLUG}",
            "# a gate-9 hole named on the PALM slug = K9 (ROLLBACK, prove green, STOP); a hole on "
            "any other root cannot appear under the scope -- it lives in the D6b record, never "
            "behind a --skip 9 without that record",
            _submit("cpo-gate-post", JD_GATE, ["-m", "jobs.audit.silver_rebuild_gate", "--tables",
                                               TABLE, "--asof", "<UTC ISO now>", "--baseline-uri",
                                               BASELINE]),
        ]),
        ("D9  FLOOR MEASUREMENT (walk-side commit input): MIN(trade_date) WHERE settle IS NOT NULL", [
            f"SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM {DB}.{TABLE} "
            f"WHERE leviathan_slug='{SLUG}' AND settle IS NOT NULL   -- Athena, or the pg mirror",
            "# expected >= 2016-08-01 (ROOT_FIRST_DATE); the literal goes to PRICE_COVERAGE_START "
            "in the walk-side commit, never earlier",
        ]),
        ("D10 NIGHTLY = automatic after the terraform repin (the 08:00Z TUE-SAT fire buys CPO/"
         f"{year} statistics incrementally); verify the first fire", [
            f"aws stepfunctions list-executions --state-machine-arn {SFN} --max-results 3",
            "# fetch log: 'done -- ... thin_settlement_tape_payloads=0 settlement_tape_skipped=0' "
            "(a non-zero count = the nightly skipped CPO BY NAME -- SETTLEMENT_TAPE_THIN / "
            "SETTLEMENT_TAPE_SKIPPED <ExceptionClass> -- and the 15 roots still promoted; two in "
            "a row = K10); silver log: no SETTLEMENT_TAPE_THIN line and no SETTLEMENT_TAPE_SKIPS "
            "{json} record (a thin unit KEEPS its partial rows and stamps settlement_tape_thin=1 "
            "in its unit line), 'incremental merge' naming the palm partition; promote + "
            "Reconcile green",
        ]),
    ]


def print_steps(year: int, run_id: str) -> None:
    print(f"=== V2-4 CPO backfill runbook (units {_units(year)[0]}..{_units(year)[-1]} = "
          f"{len(_units(year))} partitions; run_id {run_id}) ===")
    for title, cmds in steps(year, run_id):
        print()
        print(title)
        for c in cmds:
            print(f"  {c}")


def registered_partitions(glue) -> list[list[str]]:
    """Every registered (leviathan_slug, trade_year) value tuple for the palm slug."""
    out: list[list[str]] = []
    token = None
    while True:
        kw = {"DatabaseName": DB, "TableName": TABLE,
              "Expression": f"leviathan_slug='{SLUG}'"}
        if token:
            kw["NextToken"] = token
        page = glue.get_partitions(**kw)
        out.extend([list(p["Values"]) for p in page.get("Partitions", [])])
        token = page.get("NextToken")
        if not token:
            break
    return sorted(out)


def d7_check(year: int) -> int:
    import boto3

    glue = boto3.client("glue", region_name=REGION)
    parts = registered_partitions(glue)
    want = [[SLUG, str(y)] for y in _units(year)]
    print(f"registered partitions for {SLUG}: {len(parts)} (expected {len(want)})")
    for p in parts:
        print(f"  {p}")
    missing = [w for w in want if w not in parts]
    extra = [p for p in parts if p not in want]
    if missing:
        print(f"MISSING {len(missing)}: {missing}")
    if extra:
        print(f"UNEXPECTED {len(extra)}: {extra}")
    ok = not missing and not extra
    print("D7 partition check:", "PASS" if ok else "FAIL -- roll back the registered subset")
    return 0 if ok else 1


def rollback(run: bool) -> int:
    """Enumerate the registered subset and delete EXACTLY that set (Glue + S3), or print it."""
    import boto3

    glue = boto3.client("glue", region_name=REGION)
    parts = registered_partitions(glue)
    if not parts:
        print(f"no partitions registered for {SLUG} -- nothing to roll back")
        return 0
    locs = []
    for p in parts:
        rec = glue.get_partition(DatabaseName=DB, TableName=TABLE, PartitionValues=p)
        locs.append(rec["Partition"]["StorageDescriptor"]["Location"].rstrip("/") + "/")
    print(f"registered subset for {SLUG}: {len(parts)} partition(s)")
    for p, loc in zip(parts, locs):
        print(f"  {p} -> {loc}")
    to_delete = json.dumps([{"Values": p} for p in parts])
    print("\ncommands:")
    print(f"  aws glue batch-delete-partition --database-name {DB} --table-name {TABLE} "
          f"--partitions-to-delete '{to_delete}'")
    for loc in locs:
        print(f"  aws s3 rm {loc} --recursive")
    print(f"  {_submit('cpo-gate-rollback', JD_GATE, ['-m', 'jobs.audit.silver_rebuild_gate', '--tables', TABLE, '--asof', '<UTC ISO now>', '--baseline-uri', BASELINE])}")
    if not run:
        print("\n(dry run -- nothing deleted; --run executes the Glue + S3 deletes above)")
        return 0
    s3 = boto3.resource("s3", region_name=REGION)
    resp = glue.batch_delete_partition(DatabaseName=DB, TableName=TABLE,
                                       PartitionsToDelete=[{"Values": p} for p in parts])
    errs = resp.get("Errors") or []
    if errs:
        print(f"Glue reported {len(errs)} error(s): {errs}")
    for loc in locs:
        assert loc.startswith("s3://")
        bucket, key = loc[5:].split("/", 1)
        n = 0
        for obj in s3.Bucket(bucket).objects.filter(Prefix=key):
            obj.delete()
            n += 1
        print(f"deleted {n} object(s) under {loc}")
    print("rolled back; re-run the gate (D6 command) to reload the pg mirror")
    return 1 if errs else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="V2-4 CPO backfill runbook")
    ap.add_argument("--step", choices=["PRINT", "D7-CHECK", "ROLLBACK"], default="PRINT")
    ap.add_argument("--year", type=int, default=datetime.now(tz=timezone.utc).year,
                    help="the through-year of the backfill (default: this UTC year)")
    ap.add_argument("--run-id", default=f"cpo-backfill-{datetime.now(tz=timezone.utc):%Y%m%d}")
    ap.add_argument("--run", action="store_true", help="ROLLBACK only: execute the deletes")
    args = ap.parse_args(argv)
    if args.step == "PRINT":
        print_steps(args.year, args.run_id)
        return 0
    if args.step == "D7-CHECK":
        return d7_check(args.year)
    return rollback(args.run)


if __name__ == "__main__":
    sys.exit(main())
