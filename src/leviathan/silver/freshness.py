"""SILVER-F082: the data-age (freshness) pure core for the freshness poller.

WHY THIS EXISTS (audit finding, 2026-07-23)
-------------------------------------------
The 21 per-family ``FreshnessLagDays`` alarms (``jobs/observability/silver_alarms.py`` +
``modules/silver_observability``) were HOLLOW: nothing ever emitted the metric, and the alarms
were ``treat_missing_data = "missing"`` -- so a stalled producer never breached. Four producers
(``silver_nass_crop_progress``, ``silver_unica_biweekly_season_history``, ``silver_fgis``,
``silver_nass_citrus``) ran stale-green for 6-10 weeks undetected. This module is the emitter's
pure core: given the canonical S3 listing for a registry table it computes the data AGE in days
(newest ``LastModified`` under the CANONICAL prefix, excluding the shadow/staging soak areas), and
builds the CloudWatch ``PutMetricData`` items dimensioned by both ``Table`` and ``Family``.

Design mirrors ``scripts/silver/day0_heartbeat.py``'s ``freshness_delta`` canonical-only exclusion
rule exactly (a shadow publish never advances canonical, so shadow keys must not masquerade as
fresh data). Pure + AWS-free + deterministic so the age computation, the shadow exclusion, and the
empty-prefix behaviour are all unit-testable against a fake S3 listing. The thin boto3 wrapper that
actually lists S3 and calls ``put_metric_data`` lives in ``scripts/silver/freshness_poller.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable, Optional

from leviathan.silver.dag_catalog import family_of
from leviathan.silver.registry import SilverRegistry, load_registry

__all__ = [
    "METRIC_NAMESPACE",
    "METRIC_NAME",
    "is_excluded_key",
    "newest_last_modified",
    "lag_days",
    "PollTarget",
    "poll_targets",
    "metric_data_for",
]

METRIC_NAMESPACE = "Leviathan/Silver"
METRIC_NAME = "FreshnessLagDays"

# Canonical-only: the shadow/staging soak areas and the tasks manifest are NOT canonical data, so
# a shadow-published table (which by SFN doctrine never advances canonical) can never look fresh.
# Mirrors day0_heartbeat.freshness_delta's exclusion set exactly.
_EXCLUDE_SEGMENTS = ("/_shadow/", "/_staging/")
_EXCLUDE_SUFFIXES = ("_tasks.json",)


def is_excluded_key(key: str) -> bool:
    """True for a key that is NOT canonical data (shadow / staging soak area or the tasks manifest)."""
    if any(seg in key for seg in _EXCLUDE_SEGMENTS):
        return True
    return any(key.endswith(sfx) for sfx in _EXCLUDE_SUFFIXES)


def newest_last_modified(
    objects: Iterable[tuple[str, datetime]],
    exclude: Callable[[str], bool] = is_excluded_key,
) -> Optional[datetime]:
    """Newest ``LastModified`` across the canonical objects, or ``None`` for an empty/all-excluded prefix.

    ``objects`` is an iterable of ``(key, last_modified)`` pairs (exactly what an S3 ``list_objects_v2``
    page yields). Excluded keys never count toward the age -- a shadow write must not reset the clock."""
    newest: Optional[datetime] = None
    for key, last_modified in objects:
        if exclude(key):
            continue
        if newest is None or last_modified > newest:
            newest = last_modified
    return newest


def lag_days(newest: Optional[datetime], now: datetime) -> Optional[float]:
    """Age in days of the newest canonical object, or ``None`` when the prefix has no canonical data.

    Clamped at 0 so clock skew / an object stamped slightly in the future can never emit a negative
    lag (which would read as impossibly-fresh and suppress a real stall)."""
    if newest is None:
        return None
    days = (now - newest).total_seconds() / 86400.0
    return days if days > 0 else 0.0


@dataclass(frozen=True)
class PollTarget:
    """One table to poll: its canonical S3 location + the DAG family it aggregates into."""

    table: str
    family: str
    bucket: str
    prefix: str  # normalized with a single trailing slash


def poll_targets(registry: Optional[SilverRegistry] = None) -> list[PollTarget]:
    """Every registry table that has an ``s3_prefix`` (+ ``s3_bucket``), with its DAG family resolved.

    A table without an ``s3_prefix`` is skipped (nothing to list). Family is the existing
    ``dag_catalog.family_of`` derivation, so the ``Family`` dimension the poller emits lines up
    one-to-one with the per-family ``freshness_sla_breach`` alarms."""
    reg = registry or load_registry()
    targets: list[PollTarget] = []
    for name in reg.names():
        contract = reg.table(name)
        prefix = contract.get("s3_prefix")
        bucket = contract.get("s3_bucket")
        if not prefix or not bucket:
            continue
        targets.append(
            PollTarget(
                table=name,
                family=family_of(name),
                bucket=bucket,
                prefix=prefix.rstrip("/") + "/",
            )
        )
    return targets


def metric_data_for(
    table: str, family: str, lag: float, *, timestamp: datetime
) -> list[dict]:
    """Two CloudWatch ``MetricDatum`` dicts for one table's lag: one dimensioned ``[Table]``, one ``[Family]``.

    The ``[Table]`` datapoint feeds the precise per-table alarm; the ``[Family]`` datapoint feeds the
    coarse per-family alarm (statistic=Maximum, so the family reads its stalest member). ``Unit`` is
    ``None`` -- CloudWatch has no "days" unit and the alarm thresholds are bare day counts."""
    base = {
        "MetricName": METRIC_NAME,
        "Timestamp": timestamp,
        "Value": float(lag),
        "Unit": "None",
    }
    return [
        {**base, "Dimensions": [{"Name": "Table", "Value": table}]},
        {**base, "Dimensions": [{"Name": "Family", "Value": family}]},
    ]
