"""SILVER-F082 freshness poller: emit ``FreshnessLagDays`` so the freshness alarms can fire.

THE BUG THIS CLOSES (audit finding, 2026-07-23)
-----------------------------------------------
The 21 per-family ``FreshnessLagDays`` alarms were HOLLOW -- nothing emitted the metric and the
alarms were ``treat_missing_data = "missing"``, so a stalled producer never breached. Four
producers ran stale-green for 6-10 weeks. This poller is the missing emitter: for every table in
the SILVER-F010 registry with an ``s3_prefix`` it computes the canonical data AGE from S3 (newest
``LastModified`` under the canonical prefix, EXCLUDING the ``_shadow/`` / ``_staging/`` soak areas
and the tasks manifest -- a shadow write must not reset the clock) and ``put_metric_data`` two
datapoints per table: one dimensioned ``[Table]`` (the precise per-table alarm) and one ``[Family]``
(the coarse per-family alarm; statistic=Maximum picks the family's stalest member).

D-PR-14 (2026-08-04): it ALSO emits ``FreshnessLagRatio = lag_days / <that table's own declared
ceiling>`` on the same two dimensions, so **> 1.0 is the universal breach threshold** for annual,
biweekly and daily tables alike. Five family alarms sat permanently in ALARM because the family
threshold is ``min()`` over the members' ceilings while the statistic is ``Maximum`` over the
members' lags -- a mixed-cadence family compares its fastest member's ceiling against its slowest
member's lag and is arithmetically guaranteed to breach. The ratio normalizes PER MEMBER, before
that ``Maximum`` collapses them. It is emitted **ALONGSIDE** ``FreshnessLagDays``, never instead of
it (a rename would orphan all 26 live freshness alarms at once); the alarm cutover is a separate
terraform batch item that runs with both metrics live. This script creates/edits no alarm.

Cheap by design: a single ``list_objects_v2`` per prefix, no Athena, no GET. The age computation +
shadow exclusion + empty-prefix behaviour + the ratio and its denominator live in the pure core
``leviathan.silver.freshness`` and are unit-tested there.

Usage (Git-Bash needs ``MSYS_NO_PATHCONV=1`` only if you pass ``/aws`` paths -- this tool passes none):
    python scripts/silver/freshness_poller.py                 # emit for every registered table
    python scripts/silver/freshness_poller.py --dry-run       # compute + print, NO put_metric_data
    python scripts/silver/freshness_poller.py --tables silver_fgis,silver_nass_citrus
    python scripts/silver/freshness_poller.py --no-ratio      # D-PR-14 rollback: days only

EMPTY-PREFIX BEHAVIOUR: a table whose canonical prefix has zero objects emits NO datapoint (it is
logged as an EMPTY warning). With the freshness alarms now ``treat_missing_data = "breaching"``, a
table that never emits (or stops emitting) transitions to ALARM after one evaluation period -- which
is the intended "the canonical surface has no data" signal. ASCII-only stdout (Windows console cp1252).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from leviathan.silver.freshness import (  # noqa: E402
    METRIC_NAMESPACE,
    all_poll_targets,
    lag_days,
    lag_ratio,
    metric_data_for,
    newest_last_modified,
)

# CloudWatch caps PutMetricData at 1000 MetricDatum/request; 20 is the classic conservative batch
# size and keeps each request tiny. MEASURED 2026-08-04 with D-PR-14's ratio live: 46 targets x 4
# datums = 184 -> 10 requests (was ~92 -> 5). Still two orders of magnitude under the cap.
_PUT_CHUNK = 20


def _iter_objects(s3, bucket: str, prefix: str):
    """Yield ``(key, LastModified)`` for every object under ``prefix`` (paginated list, no GET)."""
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            yield obj["Key"], obj["LastModified"]


def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="SILVER-F082 freshness poller (emits FreshnessLagDays + FreshnessLagRatio)")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute + print the lags but do NOT put_metric_data (read-only)")
    ap.add_argument("--aws-region", default="us-east-1")
    ap.add_argument("--namespace", default=METRIC_NAMESPACE)
    ap.add_argument("--tables", default=None,
                    help="comma-separated table_name filter (default: every registered table)")
    ap.add_argument("--no-ratio", action="store_true",
                    help="D-PR-14 rollback switch: emit FreshnessLagDays ONLY. The ratio is "
                         "additive, so this restores the exact pre-D-PR-14 payload without a "
                         "redeploy; the day-based alarms never moved either way.")
    args = ap.parse_args(argv)

    now = datetime.now(timezone.utc)
    targets = all_poll_targets()   # registry tables + the non-registry artifacts (FENCE 2 leg 3)
    if args.tables:
        want = {t.strip() for t in args.tables.split(",") if t.strip()}
        targets = [t for t in targets if t.table in want]

    s3 = boto3.client("s3", region_name=args.aws_region)
    cw = None if args.dry_run else boto3.client("cloudwatch", region_name=args.aws_region)

    print(f"=== freshness_poller: {len(targets)} tables, asof {now.isoformat()} "
          f"(dry_run={args.dry_run} ratio={not args.no_ratio}) ===")

    metric_data: list[dict] = []
    empty: list[str] = []
    breaching: list[str] = []      # ratio > 1.0 -- what the cut-over alarm would fire on
    no_ceiling: list[str] = []     # emitted days but no ratio (no declared ceiling)
    for t in sorted(targets, key=lambda x: x.table):
        newest = newest_last_modified(_iter_objects(s3, t.bucket, t.prefix))
        lag = lag_days(newest, now)
        if lag is None:
            empty.append(t.table)
            print(f"  {t.table:42s} EMPTY canonical prefix {t.prefix} "
                  f"-> NO datapoint (breaching alarm will catch)")
            continue
        expected = None if args.no_ratio else t.expected_lag_days
        ratio = lag_ratio(lag, expected)
        if ratio is None:
            if not args.no_ratio:
                no_ceiling.append(t.table)
            ratio_txt = "ratio=n/a"
        else:
            ratio_txt = (f"expected={expected:.0f}d ratio={ratio:.3f}"
                         f"{' BREACH' if ratio > 1.0 else ''}")
            if ratio > 1.0:
                breaching.append(t.table)
        print(f"  {t.table:42s} family={t.family:14s} "
              f"newest={newest.isoformat()} lag_days={lag:.2f} {ratio_txt}")
        metric_data.extend(
            metric_data_for(t.table, t.family, lag, timestamp=now, expected=expected))

    print(f"[ratio] {len(breaching)} table(s) over 1.0: {sorted(breaching)}")
    if no_ceiling:
        print(f"[ratio] {len(no_ceiling)} table(s) emitted days but NO ratio "
              f"(no declared ceiling): {sorted(no_ceiling)}")

    if args.dry_run:
        print(f"[dry-run] would put {len(metric_data)} datapoints to {args.namespace}; "
              f"{len(empty)} empty prefixes: {empty}")
        return 0

    put = 0
    for chunk in _chunks(metric_data, _PUT_CHUNK):
        cw.put_metric_data(Namespace=args.namespace, MetricData=chunk)
        put += len(chunk)
    print(f"[emit] put {put} datapoints to {args.namespace}; "
          f"{len(empty)} empty prefixes: {empty}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
