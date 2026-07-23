"""T2a pace-leg SOAK aggregator -- read-only CloudWatch Logs scan (companion to
docs/private/PACE_SOAK_TELEMETRY.md; run Monday over the weekend window).

Two surfaces, per the spec:
  SERVING /ecs/leviathan-dev-serving : per-turn EMF JSON lines (TurnLatencyMs, CascadeFired,
      CascadeNodes, MsQuantify, intent). NO pace field exists here (gap G1) -- these numbers only
      bound the cascade context the pace leg rode.
  BATCH   /aws/batch/leviathan-dev   : P1-idiom respond()-probe / eval stdout that dumped
      trace.quantify_pace -- the ONLY CloudWatch surface carrying per-leg entries
      {node_key, table, metric, grain, n_points, streak, streak_direction, window_change, collapse}.

Read-only (logs:FilterLogEvents only); stdlib + boto3; ASCII stdout (cp1252-safe). ZERO pace
records is an HONEST outcome (flag off / no probe ran) and prints as such, never as an error.
--dry-run prints the filters + Logs Insights equivalents and never touches AWS.

Usage (PowerShell -- MSYS mangles /aws/... args under Git-Bash):
    python scripts/graphrag/pace_soak_report.py --hours 72
    python scripts/graphrag/pace_soak_report.py --hours 24 --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter

SERVING_LG = "/ecs/leviathan-dev-serving"
BATCH_LG = "/aws/batch/leviathan-dev"
EMF_FILTER = '"TurnLatencyMs"'          # every orchestrator.respond turn prints one EMF JSON line
PACE_FILTER = '"quantify_pace"'         # probe/eval stdout dumps: the only per-leg surface (G2)
INSIGHTS_EMF = ("filter ispresent(CascadeFired) | stats count() as turns, sum(CascadeFired) as "
                "cascade_turns, sum(CascadeNodes) as nodes, avg(MsQuantify) as avg_ms_q by bin(1d)")
INSIGHTS_PACE = "filter @message like /quantify_pace/ | sort @timestamp asc | limit 1000"


def _events(logs, group: str, pattern: str, start_ms: int, end_ms: int, cap: int) -> list:
    out, token = [], None
    while True:
        kw = {"logGroupName": group, "startTime": start_ms, "endTime": end_ms,
              "filterPattern": pattern}
        if token:
            kw["nextToken"] = token
        try:
            resp = logs.filter_log_events(**kw)
        except Exception as e:  # noqa: BLE001 -- a missing group reports honestly, never crashes
            print(f"  WARN {group}: {type(e).__name__}: {str(e)[:120]}")
            return out
        out += resp.get("events") or []
        token = resp.get("nextToken")
        if not token or len(out) >= cap:
            return out[:cap]


def _json_doc(msg: str):
    i = msg.find("{")
    if i < 0:
        return None
    try:
        return json.loads(msg[i:])
    except ValueError:
        return None


def _pace_entries(doc) -> list:
    """Every quantify_pace entry dict anywhere in a parsed JSON doc (probes nest it under trace)."""
    out: list = []
    if isinstance(doc, dict):
        v = doc.get("quantify_pace")
        if isinstance(v, list):
            out += [e for e in v if isinstance(e, dict)]
        for vv in doc.values():
            if isinstance(vv, (dict, list)) and vv is not v:
                out += _pace_entries(vv)
    elif isinstance(doc, list):
        for vv in doc:
            out += _pace_entries(vv)
    return out


def _mma(vals: list) -> str:
    if not vals:
        return "-"
    return f"n={len(vals)} min={min(vals):g} avg={sum(vals) / len(vals):.2f} max={max(vals):g}"


def main() -> int:
    ap = argparse.ArgumentParser(description="T2a pace soak aggregator (read-only)")
    ap.add_argument("--hours", type=int, default=72)
    ap.add_argument("--end", default=None, help="window end, ISO UTC (default: now)")
    ap.add_argument("--region", default=None)
    ap.add_argument("--serving-log-group", default=SERVING_LG)
    ap.add_argument("--batch-log-group", default=BATCH_LG)
    ap.add_argument("--limit", type=int, default=5000, help="event cap per group")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    end = (dt.datetime.fromisoformat(args.end).replace(tzinfo=dt.timezone.utc) if args.end
           else dt.datetime.now(dt.timezone.utc))
    start = end - dt.timedelta(hours=args.hours)
    print(f"PACE SOAK REPORT  window={start:%Y-%m-%d %H:%M}Z .. {end:%Y-%m-%d %H:%M}Z ({args.hours}h)")
    if args.dry_run:
        print("DRY RUN -- queries only, no AWS calls")
        print(f"  FilterLogEvents {args.serving_log_group}  pattern: {EMF_FILTER}")
        print(f"  FilterLogEvents {args.batch_log_group}  pattern: {PACE_FILTER}")
        print(f"  Insights [{args.serving_log_group}]: {INSIGHTS_EMF}")
        print(f"  Insights [{args.batch_log_group}]: {INSIGHTS_PACE}")
        return 0
    import boto3  # deferred: --help/--dry-run must work without AWS deps resolved
    logs = boto3.client("logs", **({"region_name": args.region} if args.region else {}))
    s_ms, e_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)

    print(f"SERVING {args.serving_log_group} -- cascade context (NO pace surface here: gap G1)")
    docs = [d for d in (_json_doc(e["message"]) for e in
                        _events(logs, args.serving_log_group, EMF_FILTER, s_ms, e_ms, args.limit))
            if isinstance(d, dict) and "TurnLatencyMs" in d]
    by_intent = Counter(str(d.get("intent")) for d in docs)
    msq = [d["MsQuantify"] for d in docs if isinstance(d.get("MsQuantify"), (int, float))]
    print(f"  turns (EMF lines)      : {len(docs)}"
          + (f"   by intent: {dict(sorted(by_intent.items()))}" if docs else ""))
    print(f"  cascade-fired turns    : {sum(1 for d in docs if d.get('CascadeFired'))}")
    print(f"  cascade nodes (sum)    : {sum(int(d.get('CascadeNodes') or 0) for d in docs)}")
    print(f"  MsQuantify             : {_mma(msq)}")

    print(f"BATCH {args.batch_log_group} -- per-leg pace records (probe/eval stdout)")
    events = _events(logs, args.batch_log_group, PACE_FILTER, s_ms, e_ms, args.limit)
    entries, unparsed = [], 0
    for ev in events:
        got = _pace_entries(_json_doc(ev["message"]))
        if got:
            day = dt.datetime.fromtimestamp(ev["timestamp"] / 1000, dt.timezone.utc).date().isoformat()
            entries += [(day, e) for e in got]
        else:
            unparsed += 1
    print(f"  lines mentioning quantify_pace : {len(events)} (unparsed mentions: {unparsed})")
    if not entries:
        print("  pace leg entries       : 0 -- HONEST ZERO: flag off, no probe/eval dumped a trace,")
        print("    or the window predates the flip. The serving path has no per-leg surface (G2);")
        print("    run the daily P1-idiom probe so Monday has records (PACE_SOAK_TELEMETRY.md).")
        return 0
    print(f"  pace leg entries       : {len(entries)}")
    tg = Counter(f"{e.get('table')}/{e.get('grain')}" for _, e in entries)
    print(f"  by table/grain         : {dict(sorted(tg.items()))}")
    streaks = [e["streak"] for _, e in entries if isinstance(e.get("streak"), (int, float))]
    dirs = Counter(e.get("streak_direction") for _, e in entries if e.get("streak_direction"))
    print(f"  streak lengths         : {_mma(streaks)} directions={dict(dirs) if dirs else '-'}")
    wcs = [e["window_change"] for _, e in entries if isinstance(e.get("window_change"), (int, float))]
    print(f"  window_change          : {_mma(wcs)}")
    col = Counter(e.get("collapse") for _, e in entries if e.get("collapse"))
    print(f"  collapse applied       : {dict(col) if col else '(none)'}")
    npts = [e["n_points"] for _, e in entries if isinstance(e.get("n_points"), (int, float))]
    print(f"  n_points (collapsed)   : {_mma(npts)}")
    days: dict = {}
    for day, e in entries:
        k = e.get("node_key")
        days.setdefault(day, set()).add("/".join(str(x) for x in k) if isinstance(k, list) else str(k))
    print("  distinct (commodity/driver) pairs by day:")
    for day in sorted(days):
        print(f"    {day}: {len(days[day])} -- {', '.join(sorted(days[day]))}")
    seen = Counter(p for s in days.values() for p in s)
    rep = sorted(p for p, c in seen.items() if c > 1)
    print(f"  repeat-fire pairs (>1 day): {', '.join(rep) if rep else '(none)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
