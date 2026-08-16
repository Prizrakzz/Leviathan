"""SILVER-F082 freshness poller -- THE IN-IMAGE TASK.

Emits, per poll cycle: FreshnessLagDays{Table,Family}, FreshnessLagRatio{Table,Family} (D-PR-14)
and FreshnessBreachCount{Family} (D-SG G3-1).

WHY THIS FILE EXISTS, AND WHY scripts/silver/freshness_poller.py IS NOW A SHIM OVER IT.
The worker image COPYs src/ jobs/ configs/ sql/ and NOT scripts/, so the scheduled poller could
never invoke the script. infra/terraform/envs/dev/main.tf therefore carried a hand-transcribed
``python -c`` COPY of the script's emit loop inside the schedule's ContainerOverrides. That copy
has now drifted from the script TWICE, and both times silently:

  * R7a (found 2026-08-04): the inline loop called ``poll_targets()`` -- registry-pure by design --
    where the script had moved to ``all_poll_targets()``. The ONE artifact ``EXTRA_TARGETS`` exists
    for, ``graphrag_timeline_episodes``, was never polled: 0 datapoints over a 7-day window while
    the control family emitted daily.
  * D-SG (found 2026-08-16): the inline loop called
    ``metric_data_for(t.table, t.family, lag, timestamp=now)`` with NO ``expected=``, so
    ``metric_data_for`` took its ``ratio is None`` early return and D-PR-14's ``FreshnessLagRatio``
    was NEVER emitted in production. Measured: ``list-metrics --namespace Leviathan/Silver``
    returned FreshnessLagDays, BatchJobFailedScheduled, BatchJobFailedBackstop and nothing else,
    three months after the ratio was built, unit-tested and documented as live.

Two drifts in one quarter on one block is a CLASS, not two bugs. The class dies here: the
schedule now names a module that ships in the image, and terraform holds no python at all.

The age computation, the canonical-only exclusions, the ratio, its denominator and the breach
predicate all live in the pure core ``leviathan.silver.freshness`` and are unit-tested there. This
file is the thin boto3 wrapper: one ``list_objects_v2`` per prefix, no GET, no Athena.

EMPTY-PREFIX BEHAVIOUR: a table whose canonical prefix has zero objects emits NO lag/ratio
datapoint (logged EMPTY) and counts as a BREACH in its family's FreshnessBreachCount -- see
``freshness.is_breaching`` for why that asymmetry is deliberate.

ASCII-only stdout (Windows console cp1252).

    python -m jobs.observability.freshness_poller_task
    python -m jobs.observability.freshness_poller_task --dry-run
    python -m jobs.observability.freshness_poller_task --tables silver_fgis,silver_nass_citrus
    python -m jobs.observability.freshness_poller_task --no-ratio    # D-PR-14 rollback
    python -m jobs.observability.freshness_poller_task --no-breach-count   # G3-1 rollback
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

# Local runs (repo checkout, no editable install) need src/ on the path. Inside the image the
# package is pip-installed, so this is a no-op there.
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from leviathan.silver.freshness import (  # noqa: E402
    BREACH_METRIC_NAME,
    METRIC_NAMESPACE,
    all_poll_targets,
    breach_counts,
    breach_metric_data,
    lag_days,
    lag_ratio,
    metric_data_for,
    newest_last_modified,
)

# CloudWatch caps PutMetricData at 1000 MetricDatum/request; 20 is the classic conservative batch
# size. MEASURED 2026-08-16: 46 targets x 4 datums + ~25 family breach datums = ~209 -> 11
# requests. Two orders of magnitude under the cap.
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
        description="SILVER-F082 freshness poller (FreshnessLagDays + FreshnessLagRatio + "
                    "FreshnessBreachCount)")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute + print the lags but do NOT put_metric_data (read-only)")
    ap.add_argument("--aws-region", default="us-east-1")
    ap.add_argument("--namespace", default=METRIC_NAMESPACE)
    ap.add_argument("--tables", default=None,
                    help="comma-separated table_name filter (default: every registered table). "
                         "NB a filtered run emits PARTIAL breach counts -- use --no-breach-count "
                         "with it unless you mean to overwrite a family's datapoint.")
    ap.add_argument("--no-ratio", action="store_true",
                    help="D-PR-14 rollback switch: suppress FreshnessLagRatio. Additive metric, "
                         "so this restores the exact pre-D-PR-14 payload without a redeploy.")
    ap.add_argument("--no-breach-count", action="store_true",
                    help="D-SG G3-1 rollback switch: suppress FreshnessBreachCount. Additive "
                         "metric; the day-based alarms never moved either way.")
    args = ap.parse_args(argv)

    now = datetime.now(timezone.utc)
    targets = all_poll_targets()   # registry tables + the non-registry artifacts (FENCE 2 leg 3)
    filtered = False
    if args.tables:
        want = {t.strip() for t in args.tables.split(",") if t.strip()}
        targets = [t for t in targets if t.table in want]
        filtered = True

    s3 = boto3.client("s3", region_name=args.aws_region)
    cw = None if args.dry_run else boto3.client("cloudwatch", region_name=args.aws_region)

    emit_breach = not args.no_breach_count and not filtered
    print(f"=== freshness_poller: {len(targets)} targets, asof {now.isoformat()} "
          f"(dry_run={args.dry_run} ratio={not args.no_ratio} breach={emit_breach}) ===")
    if filtered and not args.no_breach_count:
        print("  [breach] SUPPRESSED: --tables makes the per-family counts partial, and a "
              "partial count would overwrite the real one at this timestamp.")

    metric_data: list[dict] = []
    breach_rows: list[tuple[str, float | None, float | None]] = []
    empty: list[str] = []
    breaching: list[str] = []
    no_ceiling: list[str] = []
    for t in sorted(targets, key=lambda x: x.table):
        newest = newest_last_modified(_iter_objects(s3, t.bucket, t.prefix))
        lag = lag_days(newest, now)
        expected = None if args.no_ratio else t.expected_lag_days
        # The breach row uses the table's OWN ceiling regardless of --no-ratio: --no-ratio is a
        # metric-suppression switch, never a redefinition of what "late" means.
        breach_rows.append((t.family, lag, t.expected_lag_days))
        if lag is None:
            empty.append(t.table)
            print(f"  {t.table:42s} EMPTY canonical prefix {t.prefix} "
                  f"-> NO lag datapoint (counts as a BREACH for family {t.family})")
            continue
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

    counts = breach_counts(breach_rows)
    if emit_breach:
        metric_data.extend(breach_metric_data(counts, timestamp=now))
    hot = {k: v for k, v in sorted(counts.items()) if v}
    print(f"[breach] {len(counts)} families scored; {len(hot)} with >=1 late member: {hot}")
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
    print(f"[emit] put {put} datapoints to {args.namespace} "
          f"(incl. {BREACH_METRIC_NAME} for {len(counts) if emit_breach else 0} families); "
          f"{len(empty)} empty prefixes: {empty}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
