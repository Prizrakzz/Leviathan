"""Day-0 heartbeat: the two read-only probes (C1 fired_check + C6 freshness_delta).

The minimal carve-out of docs/private/DAY0_SCHEDULED_OPS_REVIEW_PLAN.md WAVE 2 (DECISION D1
tier i, ratified 2026-07-17): a stateless, describe/list/get-only heartbeat run after a
family's scheduled firing. Its reason to exist is the HOLLOW-GREEN assertion -- an execution
can be Succeeded with a green gate while a family-owned canonical table never advanced
(observed live: the 2026-07-17 modis chain), and that state SELF-CONCEALS across days
(a frozen source keeps passing every later census diff). Neither the gate nor any alarm
catches it; this tool does.

Usage (Git-Bash needs MSYS_NO_PATHCONV=1):
    python scripts/silver/day0_heartbeat.py --schedule weather_daily --window 2026-07-18T08:00Z
    python scripts/silver/day0_heartbeat.py --schedule sagis_weekly  --window 2026-07-17T12:00Z

Exit code 0 iff verdict GREEN; nonzero otherwise (gate-able by an operator or agent).

Hard guarantees (fail-closed, mirrors rehearse_recovery.py):
  * READ-ONLY -- every boto3 call goes through an allowlist proxy; any non-allowlisted
    method name raises before touching the network. No Athena (INV-3), no StartExecution,
    no writes of any kind.
  * ASCII-only stdout (Windows console is cp1252).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3

_REPO = Path(__file__).resolve().parents[2]
_MACHINE = "leviathan-dev-silver-thin-contract"
_BUCKET = "leviathan-dev-shahem-001"

# The ONLY boto3 client methods this tool may call. Fail-closed: anything else raises.
_ALLOWLIST = frozenset({
    # stepfunctions
    "list_state_machines", "list_executions", "describe_execution",
    # scheduler
    "get_schedule",
    # cloudwatch
    "get_metric_statistics",
    # s3
    "list_objects_v2", "head_object", "get_paginator", "get_object",
})

# Execution-name prefixes are FAMILY tokens and COLLIDE across schedules (plan finding C-F1):
# weather-sched-* covers weather_daily AND modis_biweekly; usda_nass-sched-* covers
# nass_crop_progress AND nass_citrus; world_bank-sched-* covers pink_sheet_monthly AND
# food_cpi -- the last pair also fires at the SAME instant, so gate --tables is the only
# discriminator. fired_check therefore matches (prefix AND window AND, on collision,
# the input's gate tables), never the prefix alone.
_SAME_INSTANT_COLLIDERS = {"pink_sheet_monthly", "food_cpi"}

# Tables gated by a family but REFRESHED by a different one (cross-family gate coupling):
# not expected to advance on this family's run -- INFO, never ATTENTION.
_NOT_OWNED = {
    "weather_daily": {"silver_modis_ndvi"},
}

# gold_weather_z is RE-RUN every weather cycle with --force-overwrite (object mtime advances
# every run) but its CONTENT lags one cycle by design -- mtime advance == PASS here; content
# lag is the full tool's C7 concern, not the heartbeat's.


class _AllowlistClient:
    def __init__(self, service: str, region: str):
        self._c = boto3.client(service, region_name=region)

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in _ALLOWLIST:
            raise RuntimeError(f"day0_heartbeat is READ-ONLY: boto3 method '{name}' is not allowlisted")
        return getattr(self._c, name)


def _load_descriptor(schedule: str) -> dict:
    p = _REPO / "configs" / "silver" / "dags" / f"{schedule}.json"
    if not p.exists():
        raise SystemExit(f"unknown schedule '{schedule}' (no descriptor at {p})")
    return json.loads(p.read_text(encoding="utf-8"))


def _table_prefix(table: str) -> str:
    import yaml  # local import: keep boto3-only startup cheap

    p = _REPO / "configs" / "silver" / "tables" / f"{table}.yaml"
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    return d["s3_prefix"].rstrip("/") + "/"


def _parse_window(s: str) -> datetime:
    s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fired_check(sfn, cw, schedule: str, family: str, desc: dict,
                window_start: datetime, grace_min: int, region: str) -> tuple[str, str, dict | None]:
    """C1: did the schedule fire and start an execution in [window, window+grace]?"""
    window_end = window_start + timedelta(minutes=grace_min)
    prefix = f"{family}-sched-"
    machine_arn = None
    for m in sfn.list_state_machines()["stateMachines"]:
        if m["name"] == _MACHINE:
            machine_arn = m["stateMachineArn"]
    if machine_arn is None:
        return ("ATTENTION", f"state machine {_MACHINE} not found", None)

    # list_executions is NOT strictly newest-first (observed live: an ABORTED run from
    # 11:23Z listed before 12:58Z runs), so no early-break on "old" items -- scan a bounded
    # number of pages and filter purely by the window.
    matches = []
    token = None
    for _page_no in range(5):  # 500 most-recent executions; ample for a day-0 window
        kw = {"stateMachineArn": machine_arn, "maxResults": 100}
        if token:
            kw["nextToken"] = token
        page = sfn.list_executions(**kw)
        for e in page["executions"]:
            if e["name"].startswith(prefix) and window_start <= e["startDate"] <= window_end:
                matches.append(e)
        token = page.get("nextToken")
        if not token:
            break

    # Same-instant collision (world_bank pair): discriminate by the input's gate --tables.
    if schedule in _SAME_INSTANT_COLLIDERS and len(matches) > 1:
        want = set(desc.get("gate_tables", []))
        kept = []
        for e in matches:
            inp = json.loads(sfn.describe_execution(executionArn=e["executionArn"])["input"])
            got = set((inp.get("gate", {}).get("command", []) or [""])[
                inp.get("gate", {}).get("command", []).index("--tables") + 1
            ].split(",")) if "--tables" in inp.get("gate", {}).get("command", []) else set()
            if want & got:
                kept.append(e)
        matches = kept or matches

    # Scheduler-level target errors in the window (the fx-placeholder failure class).
    # ACCOUNT-AGGREGATE metric (no per-schedule dimension) -- attribute by timestamp only.
    err_pts = cw.get_metric_statistics(
        Namespace="AWS/Scheduler", MetricName="TargetErrorCount",
        StartTime=window_start - timedelta(minutes=2), EndTime=window_end,
        Period=300, Statistics=["Sum"],
    )["Datapoints"]
    err_stamps = sorted(p["Timestamp"].isoformat() for p in err_pts if p["Sum"] > 0)
    target_errors = int(sum(p["Sum"] for p in err_pts))

    if not matches:
        detail = f"no {prefix}* execution in window"
        if target_errors:
            detail += (f"; AWS/Scheduler TargetErrorCount={target_errors} at {err_stamps}"
                       " (StartExecution REJECTED, retries may follow)")
        return ("DID-NOT-FIRE", detail, None)

    e = sorted(matches, key=lambda x: x["startDate"])[0]
    status = e["status"]
    detail = f"{e['name']} started {e['startDate'].isoformat()} status={status}"
    if target_errors and status in ("SUCCEEDED", "RUNNING"):
        # At-least-once delivery: first attempt errored, scheduler retry landed the run
        # (observed live 2026-07-17: sagis TargetErrorCount=1 at 12:00, execution started
        # 12:00:20 and succeeded). Working as designed -> INFO, not ATTENTION.
        detail += (f" [INFO: account TargetErrorCount={target_errors} at {err_stamps} in window;"
                   " execution present+healthy => scheduler retry recovered (at-least-once)]")
        return ("PASS", detail, e)
    if target_errors:
        detail += f" [TargetErrorCount={target_errors} at {err_stamps} -- investigate]"
        return ("ATTENTION", detail, e)
    return ("PASS" if status in ("SUCCEEDED", "RUNNING") else "ATTENTION", detail, e)


def freshness_delta(s3, schedule: str, desc: dict, window_start: datetime) -> tuple[str, list[str]]:
    """C6: did every family-OWNED canonical gate table actually advance? (the hollow-green probe)"""
    lines = []
    not_owned = _NOT_OWNED.get(schedule, set())
    class_b = desc.get("promote_mode") == "stop_and_notify"
    owned_stale = []
    for table in desc.get("gate_tables", []):
        prefix = _table_prefix(table)
        newest = None
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=_BUCKET, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if "/_shadow/" in key or "/_staging/" in key or key.endswith("_tasks.json"):
                    continue
                if newest is None or obj["LastModified"] > newest:
                    newest = obj["LastModified"]
        if newest is None:
            lines.append(f"  {table:24s} EMPTY prefix {prefix} -> ATTENTION")
            owned_stale.append(table)
            continue
        advanced = newest >= window_start
        if table in not_owned:
            tag = "INFO (not owned by this family; refreshed by its own schedule)"
        elif class_b:
            tag = "INFO (CLASS-B: canonical move not expected pre-W4)" if not advanced else "PASS"
        elif advanced:
            tag = "PASS"
        else:
            tag = "STALE"
            owned_stale.append(table)
        lines.append(f"  {table:24s} newest={newest.isoformat()} advanced={advanced} -> {tag}")
    verdict = "PASS" if not owned_stale else "HOLLOW-GREEN-RISK"
    return (verdict, lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Day-0 heartbeat: fired_check + freshness_delta (read-only)")
    ap.add_argument("--schedule", required=True)
    ap.add_argument("--window", required=True, help="expected fire instant, e.g. 2026-07-18T08:00Z")
    ap.add_argument("--grace-min", type=int, default=30, help="fire-window grace (default 30)")
    ap.add_argument("--aws-region", default="us-east-1")
    args = ap.parse_args()

    desc = _load_descriptor(args.schedule)
    family = desc["family"]
    window_start = _parse_window(args.window)

    sfn = _AllowlistClient("stepfunctions", args.aws_region)
    cw = _AllowlistClient("cloudwatch", args.aws_region)
    s3 = _AllowlistClient("s3", args.aws_region)

    print(f"=== day0 heartbeat: {args.schedule} (family={family}, class={desc.get('promote_mode')}) ===")
    print(f"window: {window_start.isoformat()} +{args.grace_min}min")

    c1, c1_detail, execution = fired_check(
        sfn, cw, args.schedule, family, desc, window_start, args.grace_min, args.aws_region)
    print(f"C1 fired_check      : {c1}")
    print(f"  {c1_detail}")

    c6, c6_lines = freshness_delta(s3, args.schedule, desc, window_start)
    print(f"C6 freshness_delta  : {c6}")
    for ln in c6_lines:
        print(ln)

    if c1 == "DID-NOT-FIRE":
        verdict = "DID-NOT-FIRE"
    elif c1 == "ATTENTION":
        verdict = "ATTENTION:fired_check"
    elif execution is not None and execution["status"] == "RUNNING":
        verdict = "RUNNING (re-run after terminal)"
    elif c6 == "HOLLOW-GREEN-RISK":
        # Succeeded execution + owned canonical did not move == the self-concealing state.
        verdict = "HOLLOW-GREEN"
    else:
        verdict = "GREEN"
    print(f"VERDICT: {verdict}")
    return 0 if verdict == "GREEN" else 1


if __name__ == "__main__":
    sys.exit(main())
