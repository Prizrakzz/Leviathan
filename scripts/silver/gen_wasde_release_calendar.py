"""Bank the WASDE release calendar as a TEST FIXTURE -- never as the runtime source.

WHAT THIS IS AND WHAT IT IS EMPHATICALLY NOT
--------------------------------------------
The PSD clock (``leviathan.transforms.bronze_to_silver.psd_clock``) needs the day
of each month's WASDE release.  There are two ways to give it one and only one of
them is allowed:

  RUNTIME (the only supported path).  ``jobs/batch/psd_silver_task.
  wasde_release_calendar`` reads the REGISTERED ``silver_wasde`` partitions from
  Glue on every fire (get-partitions, never MSCK -- the table's own
  recovery_strategy) and passes the resulting ``{'YYYY-MM': day}`` dict into the
  pure transform.  silver_wasde's newest partition and the newest PSD stamp
  advance in LOCKSTEP monthly and ``psd_monthly`` fires ``cron(0 18 8-13 * ? *)``,
  so any calendar frozen at image-build time would make the clock's fail-closed
  raise RED-STOP the DAG every single month until a new image, a terraform digest
  bump and a jobdef re-register had landed.  A one-time build step cannot be a
  monthly mechanism.

  BANKED (this script).  A snapshot of the same partition list, written to
  ``tests/fixtures/wasde/release_calendar.json`` so the unit suite can pin the
  clock FUNCTION's shape hermetically -- no Glue, no S3, no live catalog.  The
  transform never imports it.  Nothing in ``src/`` or ``jobs/`` reads it.  The
  LIVE reconcile is the shadow gate's job, not this file's.

If a future edit makes any runtime module import the banked fixture, that is the
F5 defect returning, and it is a kill condition for the lane.

WHAT THE FIXTURE CARRIES, MEASURED
----------------------------------
472 registered partitions, 1985-01-11 .. 2026-08-12, one release per calendar
month, every day over 2006+ inside 8..14.  FIVE months are absent from
2006-01..2026-08 and the fixture is honest about all five:

  * 2013-10, 2019-01, 2025-10 -- the government-shutdown CANCELLED WASDEs.  USDA
    published nothing, so nothing can be backfilled.  The unit suite asserts they
    appear in neither the calendar nor any PSD stamp.
  * 2006-07, 2008-10 -- gaps in OUR silver_wasde, not in USDA's calendar.  USDA
    published both and configs/sources/usda_wasde_manifest.yaml already holds
    them (2006-07-12 and 2008-10-28).  They are what the month-end fallback
    covers today: 51,454 of 247,294 wide rows, 20.81%, 99.63% of it 2006-07.

Keeping the two gap classes DISTINCT in the fixture is the point.  A test that
cannot tell "USDA cancelled it" from "we have not ingested it" cannot pin the
month-end fallback's meaning either.

Usage
-----
    python scripts/silver/gen_wasde_release_calendar.py --check
    python scripts/silver/gen_wasde_release_calendar.py                    # live Glue
    python scripts/silver/gen_wasde_release_calendar.py \
        --from-partition-list <file>       # one YYYY-MM-DD per line, offline
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "wasde" / "release_calendar.json"

# The three government-shutdown cancellations. USDA published NO WASDE in these
# months, so they are absences in the SOURCE and can never be backfilled.
SHUTDOWN_MONTHS: tuple[str, ...] = ("2013-10", "2019-01", "2025-10")

# The two months USDA published and silver_wasde has not ingested. These are OUR
# gaps and they are what the PSD clock's month-end fallback covers today.
UNINGESTED_MONTHS: tuple[str, ...] = ("2006-07", "2008-10")


def _from_partition_list(path: str) -> list[str]:
    out = []
    with open(path, encoding="ascii") as fh:
        for line in fh:
            value = line.strip()
            if value:
                out.append(value)
    return out


def _from_glue(aws_region: str) -> list[str]:
    from leviathan.silver.registry import load_registry

    from jobs.batch.psd_silver_task import _glue_client

    contract = load_registry().table("silver_wasde")
    glue = _glue_client(aws_region)
    values: list[str] = []
    paginator = glue.get_paginator("get_partitions")
    for page in paginator.paginate(DatabaseName=contract["glue_database"],
                                   TableName="silver_wasde",
                                   PaginationConfig={"PageSize": 1000}):
        for part in page.get("Partitions", []):
            vals = part.get("Values") or []
            if vals:
                values.append(str(vals[0]))
    return values


def build(partitions: list[str]) -> dict:
    """Turn a registered-partition list into the banked fixture payload."""
    partitions = sorted({p for p in partitions if len(p) == 10})
    if not partitions:
        raise SystemExit("no registered silver_wasde partitions to bank")
    calendar: dict[str, int] = {}
    for value in partitions:
        month, day = value[:7], int(value[8:10])
        calendar[month] = max(day, calendar.get(month, 0))
    days_2006_plus = sorted({d for m, d in calendar.items() if m >= "2006"})
    missing = []
    year, month = 2006, 1
    ceiling = max(calendar)
    while "%04d-%02d" % (year, month) <= ceiling:
        key = "%04d-%02d" % (year, month)
        if key not in calendar:
            missing.append(key)
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return {
        "_what": ("A BANKED SNAPSHOT of the registered silver_wasde partitions, for the unit "
                  "suite ONLY. The runtime calendar is read live from Glue by "
                  "jobs/batch/psd_silver_task.wasde_release_calendar; nothing in src/ or jobs/ "
                  "reads this file, and an import of it from a runtime module is a kill "
                  "condition (a baked calendar red-stops psd_monthly every month)."),
        "_generated_by": "scripts/silver/gen_wasde_release_calendar.py",
        "n_partitions": len(partitions),
        "n_months": len(calendar),
        "span": [min(partitions), max(partitions)],
        "registered_days_2006_plus": days_2006_plus,
        "missing_months_2006_plus": missing,
        "shutdown_months": list(SHUTDOWN_MONTHS),
        "uningested_months": list(UNINGESTED_MONTHS),
        "calendar": calendar,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Bank the WASDE release calendar test fixture")
    parser.add_argument("--from-partition-list", default="", dest="partition_list",
                        help="Offline source: one YYYY-MM-DD registered partition per line.")
    parser.add_argument("--aws-region", default=os.environ.get("AWS_REGION", "us-east-1"),
                        dest="aws_region")
    parser.add_argument("--out", default=str(FIXTURE_PATH))
    parser.add_argument("--check", action="store_true",
                        help="Do not write; report whether the banked fixture is self-consistent.")
    args = parser.parse_args()

    if args.check:
        payload = json.loads(Path(args.out).read_text(encoding="ascii"))
        calendar = payload["calendar"]
        problems = []
        if len(calendar) != payload["n_months"]:
            problems.append("n_months disagrees with the calendar it describes")
        for month in payload["shutdown_months"] + payload["uningested_months"]:
            if month in calendar:
                problems.append("%s is declared absent but the calendar carries it" % month)
        declared = set(payload["missing_months_2006_plus"])
        expected = set(payload["shutdown_months"]) | set(payload["uningested_months"])
        if declared != expected:
            problems.append("missing_months_2006_plus %s != shutdown + uningested %s"
                            % (sorted(declared), sorted(expected)))
        if problems:
            print("WASDE calendar fixture PROBLEMS:")
            for p in problems:
                print("  - " + p)
            return 3
        print("WASDE calendar fixture OK: %d months, %d partitions, span %s..%s, days 2006+ %s"
              % (payload["n_months"], payload["n_partitions"], payload["span"][0],
                 payload["span"][1], payload["registered_days_2006_plus"]))
        return 0

    partitions = (_from_partition_list(args.partition_list) if args.partition_list
                  else _from_glue(args.aws_region))
    payload = build(partitions)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, sort_keys=False) + "\n", encoding="ascii")
    print("wrote %s: %d months, %d partitions, span %s..%s, missing 2006+ %s"
          % (out, payload["n_months"], payload["n_partitions"], payload["span"][0],
             payload["span"][1], payload["missing_months_2006_plus"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
