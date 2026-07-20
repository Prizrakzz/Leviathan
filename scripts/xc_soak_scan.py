"""RV2 D20 counted dark-soak scan -- the queryable gate that replaced the 2-day timer.

While the LLM cross-commodity tier ships DARK (W4: planner emits xc_explicit/xc_target, flag
GRAPHRAG_XC_LLM_DETECT absent, gate consumes nothing), the flip gate is a COUNT, not a clock:
>= 50 dispatch-successful reasoning/hybrid turns observed, 0 unjustified would-fires, and EVERY
xc_explicit=true dark turn individually dispositioned by the user against the fence definition
text. This script enumerates that gate from the two server-side channels W2 added:

  1. CloudWatch EMF (namespace Leviathan/Serving, emitted by orchestrator.respond):
     - MsDispatch SampleCount per (intent, model)  -> turns where dispatch actually RAN
     - PlannerFallback Sum                          -> dispatch ran but fell back (excluded from N)
     - XcLlmWouldFire Sum                           -> planner would-fire turns (flag-independent)
  2. Logs Insights over the serving log group: the per-turn `XC_DETECT_DARK turn=<id> target=<span>`
     ASCII lines -- the disposition list the flip request must carry, one row per would-fire.

EMF dimension note: emf.emit writes every metric twice, once under [intent, model] and once
dimensionless. The per-intent numbers here therefore come from list_metrics over the [intent, model]
combos (reasoning/hybrid only); the dimensionless rollup is reported as a cross-check.

Read-only (GetMetricStatistics + StartQuery/GetQueryResults); ASCII stdout (cp1252-safe); optional
--json report file is UTF-8. No LLM calls, ~zero cost.

Usage (PowerShell, AWS creds in env):
    python scripts/xc_soak_scan.py --hours 168
    python scripts/xc_soak_scan.py --hours 72 --log-group /ecs/leviathan-dev-serving --json out\\soak.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time

NAMESPACE = "Leviathan/Serving"
LOG_GROUP = "/ecs/leviathan-dev-serving"
SOAK_INTENTS = ("reasoning", "hybrid")          # D20: only these branches consult the gate
DARK_QUERY = ("fields @timestamp, @message | filter @message like /XC_DETECT_DARK/ "
              "| sort @timestamp desc | limit {limit}")


def _ascii(s: str) -> str:
    return str(s).encode("ascii", "replace").decode()


def _metric_dim_sets(cw, name: str) -> list[list[dict]]:
    """Every dimension combo this metric was emitted under (paginated ListMetrics)."""
    combos, token = [], None
    while True:
        kw = {"Namespace": NAMESPACE, "MetricName": name}
        if token:
            kw["NextToken"] = token
        resp = cw.list_metrics(**kw)
        combos += [m.get("Dimensions") or [] for m in resp.get("Metrics") or []]
        token = resp.get("NextToken")
        if not token:
            return combos


def _stat_sum(cw, name: str, dims: list[dict], start, end, stat: str) -> float:
    """One windowed GetMetricStatistics sum for a metric under an exact dimension combo. CloudWatch
    matching is exact-set, so [] returns the dimensionless rollup and [intent, model] the per-pair line."""
    resp = cw.get_metric_statistics(Namespace=NAMESPACE, MetricName=name, Dimensions=dims,
                                    StartTime=start, EndTime=end, Period=3600, Statistics=[stat])
    return float(sum(p.get(stat) or 0.0 for p in resp.get("Datapoints") or []))


def _sum_over_intents(cw, name: str, start, end, stat: str) -> tuple[float, dict]:
    """Sum a metric across every [intent, model] combo whose intent is reasoning/hybrid."""
    total, per = 0.0, {}
    for dims in _metric_dim_sets(cw, name):
        d = {x["Name"]: x["Value"] for x in dims}
        if set(d) != {"intent", "model"} or d["intent"] not in SOAK_INTENTS:
            continue
        v = _stat_sum(cw, name, dims, start, end, stat)
        total += v
        per[f"{d['intent']}/{d['model']}"] = per.get(f"{d['intent']}/{d['model']}", 0.0) + v
    return total, per


def _dark_lines(logs, start, end, limit: int) -> list[dict]:
    """The XC_DETECT_DARK disposition rows via Logs Insights (poll until Complete, ~60s ceiling)."""
    q = logs.start_query(logGroupName=LOG_GROUP, startTime=int(start.timestamp()),
                         endTime=int(end.timestamp()), queryString=DARK_QUERY.format(limit=limit))
    qid = q["queryId"]
    for _ in range(30):
        res = logs.get_query_results(queryId=qid)
        if res.get("status") in ("Complete", "Failed", "Cancelled", "Timeout"):
            break
        time.sleep(2)
    rows = []
    for row in res.get("results") or []:
        d = {c["field"]: c.get("value") for c in row}
        rows.append({"ts": d.get("@timestamp"), "message": _ascii(d.get("@message") or "").strip()})
    return rows


def main() -> int:
    global LOG_GROUP
    ap = argparse.ArgumentParser(description="RV2 D20 dark-soak scan (EMF sums + XC_DETECT_DARK lines)")
    ap.add_argument("--hours", type=int, default=168, help="lookback window (default 168 = 7d)")
    ap.add_argument("--region", default=None, help="AWS region (default: env/config chain)")
    ap.add_argument("--log-group", default=LOG_GROUP, help=f"serving log group (default {LOG_GROUP})")
    ap.add_argument("--soak-n", type=int, default=50, help="D20 count gate (default 50; user-ratifiable)")
    ap.add_argument("--limit", type=int, default=200, help="max dark lines to pull (default 200)")
    ap.add_argument("--json", default=None, help="optional UTF-8 JSON report path")
    args = ap.parse_args()
    LOG_GROUP = args.log_group

    import boto3  # deferred: --help must work without AWS deps resolved
    kw = {"region_name": args.region} if args.region else {}
    cw = boto3.client("cloudwatch", **kw)
    logs = boto3.client("logs", **kw)
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(hours=args.hours)

    dispatched, disp_per = _sum_over_intents(cw, "MsDispatch", start, end, "SampleCount")
    fallbacks, _ = _sum_over_intents(cw, "PlannerFallback", start, end, "Sum")
    would_rh, _ = _sum_over_intents(cw, "XcLlmWouldFire", start, end, "Sum")
    would_all = _stat_sum(cw, "XcLlmWouldFire", [], start, end, "Sum")   # dimensionless cross-check
    successful = int(dispatched - fallbacks)
    dark = _dark_lines(logs, start, end, args.limit)

    print(f"XC SOAK REPORT (D20)  window={args.hours}h  ns={NAMESPACE}  log_group={LOG_GROUP}")
    print(f"  dispatched reasoning/hybrid turns   : {int(dispatched)}")
    for k in sorted(disp_per):
        print(f"    - {k}: {int(disp_per[k])}")
    print(f"  planner fallbacks (reasoning/hybrid): {int(fallbacks)}")
    print(f"  dispatch-successful r/h turns  (N)  : {successful}   gate: N >= {args.soak_n}")
    print(f"  XcLlmWouldFire (reasoning/hybrid)   : {int(would_rh)}")
    print(f"  XcLlmWouldFire (all turns, no-dim)  : {int(would_all)}")
    count_ok = successful >= args.soak_n
    print(f"  COUNT GATE: {'MET' if count_ok else f'SHORT ({successful}/{args.soak_n})'}"
          + ("" if count_ok else " -- fill via dark deck replay (D20)"))
    print(f"DARK WOULD-FIRE LINES ({len(dark)} pulled; EVERY one needs a USER disposition against the")
    print("fence definition text before the W5 flip -- the script only enumerates, it never adjudicates):")
    if not dark:
        print("  (none in window)")
    for row in dark:
        print(f"  {row['ts']}  {row['message']}")
    if args.json:
        doc = {"window_hours": args.hours, "namespace": NAMESPACE, "log_group": LOG_GROUP,
               "dispatched_rh": int(dispatched), "planner_fallbacks_rh": int(fallbacks),
               "dispatch_successful_rh": successful, "soak_n": args.soak_n, "count_gate_met": count_ok,
               "would_fire_rh": int(would_rh), "would_fire_all": int(would_all), "dark_lines": dark}
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
        print(f"report written: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
