"""SILVER-F082: the data-age (freshness) pure core for the freshness poller.

WHY THIS EXISTS (audit finding, 2026-07-23)
-------------------------------------------
The 21 per-family ``FreshnessLagDays`` alarms (``jobs/observability/silver_alarms.py`` +
``modules/silver_observability``) were HOLLOW: nothing ever emitted the metric, and the alarms
were ``treat_missing_data = "missing"`` -- so a stalled producer never breached. Four producers
(``silver_nass_crop_progress``, ``silver_unica_biweekly_season_history``, ``silver_fgis``,
``silver_nass_citrus``) ran stale-green for 6-10 weeks undetected. This module is the emitter's
pure core: given the canonical S3 listing for a registry table it computes the data AGE in days
(newest ``LastModified`` under the CANONICAL prefix, excluding the shadow/staging soak areas and
the backup areas), and builds the CloudWatch ``PutMetricData`` items dimensioned by both ``Table``
and ``Family``.

Design follows ``scripts/silver/day0_heartbeat.py``'s ``freshness_delta`` canonical-only exclusion
rule (a shadow publish never advances canonical, so shadow keys must not masquerade as fresh data),
extended with ``/_backup/`` per R7.2 below. Pure + AWS-free + deterministic so the age computation,
the non-canonical exclusions, and the empty-prefix behaviour are all unit-testable against a fake
S3 listing. The thin boto3 wrapper that
actually lists S3 and calls ``put_metric_data`` lives in ``scripts/silver/freshness_poller.py``.

D-PR-14 -- THE SECOND METRIC (``FreshnessLagRatio``), 2026-08-04
---------------------------------------------------------------
Five family alarms had been in ALARM since 2026-07-23/07-30 and, because CloudWatch notifies on
TRANSITION, were silent AND could never signal a NEW stall. The mechanism is arithmetic, not
mis-tuning: ``jobs/observability/silver_alarms.py`` thresholds a family at
``dag_catalog.build_catalog``'s ``max_sla_lag_days``, which is ``min()`` over the family's members
("the tightest interim ceiling"), and then evaluates it with ``statistic=Maximum`` over those same
members. A mixed-cadence family compares its FASTEST member's ceiling against its SLOWEST member's
lag, so it is GUARANTEED to breach (``usda_nass``: 14d ceiling vs ``silver_nass_annual`` at 64.83d;
``weather``: a 3d ceiling vs ``silver_modis_ndvi``, an 8-day composite -- arithmetically
unsatisfiable).

The fix is to NORMALIZE PER MEMBER BEFORE the family ``Maximum`` collapses them:
``FreshnessLagRatio = lag_days / <that table's own declared ceiling>``, so **1.0 is the universal
threshold** for annual, biweekly and daily tables alike.

TWO RULES THIS MODULE ENFORCES, both from the ratified decision:
  1. **ALONGSIDE, NEVER INSTEAD.** A metric RENAME would orphan all 26 existing ``FreshnessLagDays``
     alarms at once. :func:`metric_data_for` therefore still emits the two day-based datums
     unchanged and APPENDS the ratio ones; the alarm cutover is a separate terraform batch item that
     runs with both metrics live.
  2. **EMITTER-SIDE ONLY.** Nothing here creates, renames or reads an alarm, and the timeline alarm
     tfvars (D-EI-12) are untouched. Per-leg ``FreshnessLagDays`` granularity remains owned by
     D-EI-12/R7 -- referenced, not forked.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable, Optional

from leviathan.silver.dag_catalog import (
    FRESHNESS_LAG_OVERRIDES,
    effective_sla_lag_days,
    family_of,
)
from leviathan.silver.registry import SilverRegistry, load_registry

__all__ = [
    "METRIC_NAMESPACE",
    "METRIC_NAME",
    "RATIO_METRIC_NAME",
    "BREACH_METRIC_NAME",
    "TABLE_CEILING_OVERRIDES",
    "is_excluded_key",
    "newest_last_modified",
    "lag_days",
    "declared_ceiling_days",
    "lag_ratio",
    "is_breaching",
    "breach_counts",
    "breach_metric_data",
    "PollTarget",
    "poll_targets",
    "EXTRA_TARGETS",
    "all_poll_targets",
    "metric_data_for",
]

METRIC_NAMESPACE = "Leviathan/Silver"
METRIC_NAME = "FreshnessLagDays"

# D-PR-14. The normalized companion metric. NEVER a rename of METRIC_NAME -- see rule 1 above.
RATIO_METRIC_NAME = "FreshnessLagRatio"

# D-SG G3-1, 2026-08-16. THE THIRD METRIC, and the one the family alarm should have been reading
# all along.
#
# FreshnessLagDays{Family} is evaluated with statistic=Maximum against a threshold that
# jobs/observability/silver_alarms.py takes as min() over the family's member ceilings -- the
# family's SLOWEST member measured against its FASTEST member's ceiling. For a mixed-cadence
# family that is not a mis-tuning, it is arithmetically unsatisfiable: ``weather`` carries a 3d
# ceiling while silver_modis_ndvi is an 8-day composite sitting at 80.7d (measured 2026-08-16),
# so leviathan-dev-freshness-sla-breach-weather has been latched ALARM since 2026-07-30 while
# all four daily weather tables sat at 0.12-0.14d.
#
# FreshnessLagRatio (D-PR-14) normalizes per member but is STILL collapsed by Maximum, so it
# answers "how bad is the worst member" -- a real improvement, and still not the question the
# alarm asks. FreshnessBreachCount answers the question directly: how MANY member tables are
# past THEIR OWN declared ceiling. Alarm on >= 1 and the weather artifact dies without losing
# modis coverage (its own 45d table ceiling still counts it the day it is truly dead).
BREACH_METRIC_NAME = "FreshnessBreachCount"

# Canonical-only: the shadow/staging soak areas, the BACKUP areas and the tasks manifest are NOT
# canonical data, so a shadow-published table (which by SFN doctrine never advances canonical) can
# never look fresh.
#
# ``/_backup/`` added 2026-08-01 (EVIDENCE_INTEGRITY_WAVE_PLAN R7.2, ratified D-EI-12). MEASURED:
# the EXTRA_TARGETS prefix ``graphrag_evidence/timeline/`` already held
# ``_backup/episodes_20260704_prerebuild.json``, so a pre-rebuild BACKUP copy -- written by the
# copy-prefix discipline, not by a rebuild -- was resetting the artifact's measured age and would
# have made the FreshnessLagDays fence fail OPEN in exactly the direction it was built to close
# (and kept a datapoint flowing after a DELETED artifact, contra silver_alarms.py's
# treat_missing_data='breaching' design note). Excluded as a SEGMENT rather than by narrowing any
# one poll prefix so it generalises to every future backup convention, anywhere in the tree.
#
# ``/_manifests/`` added 2026-08-07 (D-PQ recon V2): ShadowPublisher writes its RUN MANIFEST under
# the canonical root even on SHADOW publishes, so a shadow-only run was resetting the canonical
# freshness clock -- the SILVER-F082 fail-open through a second door. MEASURED false-greens at
# discovery: nass_crop_progress reported 3.0d vs 66.9d true, unica_annual_state 1.9 vs 67.7,
# modis 11.0 vs 72.6, fnc x3 21.5 vs 66.0, fgis 0.9 vs 14.9 -- six tables under their ceilings
# on manifest mtimes alone. A manifest is bookkeeping, never canonical data.
_EXCLUDE_SEGMENTS = ("/_shadow/", "/_staging/", "/_backup/", "/_manifests/")
_EXCLUDE_SUFFIXES = ("_tasks.json",)


def is_excluded_key(key: str) -> bool:
    """True for a key that is NOT canonical data (shadow / staging / backup area or the tasks manifest)."""
    if any(seg in key for seg in _EXCLUDE_SEGMENTS):
        return True
    return any(key.endswith(sfx) for sfx in _EXCLUDE_SUFFIXES)


def newest_last_modified(
    objects: Iterable[tuple[str, datetime]],
    exclude: Callable[[str], bool] = is_excluded_key,
) -> Optional[datetime]:
    """Newest ``LastModified`` across the canonical objects, or ``None`` for an empty/all-excluded prefix.

    ``objects`` is an iterable of ``(key, last_modified)`` pairs (exactly what an S3 ``list_objects_v2``
    page yields). Excluded keys never count toward the age -- neither a shadow write nor a BACKUP copy
    may reset the clock, however new it is and even when it is the only recent object under the prefix."""
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


# ---------------------------------------------------------------------------
# D-PR-14: the DENOMINATOR. Per-table declared freshness ceilings that DIVERGE from the registry
# derivation, mirroring the per-table alarms' own declared ceilings in
# ``jobs/observability/silver_alarms.py`` (BURNED_TABLE_FRESHNESS + ARTIFACT_FRESHNESS).
#
# WHY A MIRROR RATHER THAN AN IMPORT: ``src/leviathan/`` has ZERO imports from ``jobs/`` (measured),
# ``jobs`` is not even a package (no ``__init__.py``), and inverting that layering to read an alarm
# module from the pure core would be worse than the duplication. The mirror is TEST-PINNED instead:
# tests/unit/silver/test_freshness_poller.py loads silver_alarms.py by importlib and asserts that
# :func:`declared_ceiling_days` reproduces EVERY declared per-table ceiling exactly, so a drift on
# either side is a red test, not a silently wrong denominator. silver_alarms is the direction of
# truth; this dict follows it.
#
# MEASURED 2026-08-04: exactly ONE registry table diverges. The other three burned tables
# (silver_nass_crop_progress 14 via FRESHNESS_LAG_OVERRIDES, silver_fgis 14, silver_nass_citrus 400)
# already fall out of the registry derivation unchanged, so they are deliberately NOT listed here --
# an entry that merely restates the derivation is a second source of truth for nothing.
#
#   silver_unica_biweekly_season_history 21  A FORTNIGHTLY release series. The registry carries
#       cadence=weekly, so the derivation yields 14 -- and 14 is exactly the miscalibration D-PR-14
#       exists to kill: a NORMAL 16-day-old fortnightly drop would score ratio 1.14 and fire the
#       > 1.0 threshold. 21 = ~1 cycle (14d) + a half-cycle grace, so a single delayed drop is
#       tolerated and a MISSED cycle still breaches.
TABLE_CEILING_OVERRIDES: dict[str, int] = {
    "silver_unica_biweekly_season_history": 21,
}


def declared_ceiling_days(contract: dict) -> float:
    """The table's own declared freshness ceiling in days -- the DENOMINATOR of ``FreshnessLagRatio``.

    Precedence: an explicit :data:`TABLE_CEILING_OVERRIDES` entry (the per-table alarm's declared
    ceiling, which LOOSENS a cadence the registry records too tightly) > the registry derivation
    ``dag_catalog.effective_sla_lag_days``, TIGHTENED by ``dag_catalog.FRESHNESS_LAG_OVERRIDES``.

    That second clause is deliberately the SAME per-member quantity ``build_catalog`` computes
    immediately before collapsing it with ``min()`` -- the ratio is that collapse undone, applied
    per member, which is the whole of D-PR-14."""
    name = contract["table_name"]
    override = TABLE_CEILING_OVERRIDES.get(name)
    if override is not None:
        return float(override)
    lag, _basis = effective_sla_lag_days(contract)
    tighten = FRESHNESS_LAG_OVERRIDES.get(name)
    if tighten is not None and tighten < lag:
        lag = tighten
    return float(lag)


def lag_ratio(lag: Optional[float], expected: Optional[float]) -> Optional[float]:
    """``lag / expected`` -- the normalized age, so **> 1.0 is the universal breach threshold**.

    ``None`` (no ratio datapoint) when the prefix has no canonical data, when no ceiling is
    declared, or when the ceiling is non-positive. A non-positive ceiling is refused rather than
    divided by: ZeroDivisionError would kill the whole poll cycle, and all 26 day-based alarms are
    ``treat_missing_data='breaching'``, so one bad denominator would page 21 owners at once."""
    if lag is None or expected is None:
        return None
    expected = float(expected)
    if expected <= 0:
        return None
    return float(lag) / expected


@dataclass(frozen=True)
class PollTarget:
    """One table to poll: its canonical S3 location, the DAG family it aggregates into, and the
    table's own declared freshness ceiling in days (the ``FreshnessLagRatio`` denominator).

    ``expected_lag_days`` defaults to ``None`` so a hand-built target still emits the day metric;
    it simply gets no ratio datapoint (the alarm posture on the day metric is unchanged)."""

    table: str
    family: str
    bucket: str
    prefix: str  # normalized with a single trailing slash
    expected_lag_days: Optional[float] = None


def poll_targets(registry: Optional[SilverRegistry] = None) -> list[PollTarget]:
    """Every registry table that has an ``s3_prefix`` (+ ``s3_bucket``), with its DAG family resolved.

    A table without an ``s3_prefix`` is skipped (nothing to list). Family is the existing
    ``dag_catalog.family_of`` derivation, so the ``Family`` dimension the poller emits lines up
    one-to-one with the per-family ``freshness_sla_breach`` alarms. ``expected_lag_days`` is the
    table's OWN ceiling (:func:`declared_ceiling_days`) -- never the family's tightest one, which is
    what makes the family ``Maximum`` stop being poisoned by its slowest member (D-PR-14)."""
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
                expected_lag_days=declared_ceiling_days(contract),
            )
        )
    return targets


# ---------------------------------------------------------------------------
# FENCE 2 leg 3 (incident I-2, 2026-07-31): NON-REGISTRY artifacts that still deserve a freshness
# clock. graphrag_evidence/timeline/episodes.json was built 2026-07-04 and nothing measured its age
# while the store it describes grew ~74%; the feature stayed on and shipped zero episodes silently.
#
# WHY NOT JUST REGISTER IT IN THE SILVER-F010 REGISTRY (the obvious "reuse the machinery" move):
# that is a CATEGORY ERROR. ``load_registry()`` also feeds ``build_catalog`` (which would mint a
# phantom DAG family and a phantom ``batch_job_failed`` alarm for a family with no Batch DAG), DDL
# generation, the value census, projection validation and readiness certification -- a GraphRAG
# serving artifact would start appearing in silver readiness certificates. It would also break
# tests/unit/silver/test_freshness_poller.py:123-127 (`len(targets) == len(reg.names())`).
#
# So ``poll_targets`` stays REGISTRY-PURE and the extras ride alongside. What IS reused is
# everything that matters: the metric contract (Leviathan/Silver :: FreshnessLagDays{Table}), the
# per-table alarm resource (modules/silver_observability/main.tf:253-270), the SNS topic, and the
# existing daily schedule -- no parallel freshness system is invented.
#
# bucket/prefix mirror jobs/utils/register_evidence_jobdef.py:22-24
# (EVIDENCE_S3 = s3://leviathan-dev-shahem-001/graphrag_evidence).
#
# ``expected_lag_days`` is declared LITERALLY here because the artifact is not in the registry, so
# there is no contract to derive from. 10 = the weekly timeline rebuild (cron 0 3 ? * SUN *) + a 3d
# grace, mirroring silver_alarms.ARTIFACT_FRESHNESS -- and pinned to it by the same test that pins
# TABLE_CEILING_OVERRIDES. D-PR-14 emitter-side only: no alarm, and the timeline alarm tfvars stay
# held by D-EI-12.
EXTRA_TARGETS: tuple[PollTarget, ...] = (
    PollTarget(
        table="graphrag_timeline_episodes",
        family="graphrag_evidence",
        bucket="leviathan-dev-shahem-001",
        # D-SG D12 / D-EI-12 CALIBRATION, 2026-08-16 -- POINTED AT THE HEARTBEAT, NOT THE
        # DIRECTORY. This is an S3 list PREFIX that happens to name one full key, so
        # list_objects_v2 returns exactly last_run.json and nothing else.
        #
        # WHY: the weekly rebuild runs ``--run-if-changed``, so on an UNCHANGED week it writes NO
        # episodes.json -- correctly, R7.1 -- and touches only the heartbeat. What is being
        # measured is SCHEDULE LIVENESS, never content churn, and the applied alarm's own basis
        # string in silver_observability.auto.tfvars.json has said exactly that since 2026-08-05
        # while the emitter still pointed at the directory.
        #
        # WHAT THE DIRECTORY PREFIX GOT WRONG, precisely: ``newest_last_modified`` takes the MAX
        # over the prefix, so today it happens to return last_run.json (2026-08-09T03:01Z,
        # measured lag 6.40d) because the heartbeat is newer than episodes.json
        # (2026-08-04T07:17Z). The reading is right by ACCIDENT. A run that writes the artifact
        # and then fails before stamping the heartbeat would reset the clock off the artifact and
        # read fresh -- the fail-open direction R7.2 closed for /_backup/, through a third door.
        # Naming the object makes the measurement a declaration instead of a coincidence.
        #
        # THE FAILURE MODE THIS TAKES ON, stated: if the heartbeat object is ever renamed or
        # moved, this prefix lists EMPTY, the poller emits no datapoint, and the
        # treat_missing_data="breaching" alarm fires within one day. That is the correct
        # direction (fail closed) and it is pinned by
        # tests/unit/silver/test_freshness_poller.py, which asserts this prefix against
        # leviathan.graphrag.timeline's own ``_HEARTBEAT`` constant rather than a hand-copied
        # literal.
        prefix="graphrag_evidence/timeline/last_run.json",
        expected_lag_days=10.0,
    ),
)


def all_poll_targets(registry: Optional[SilverRegistry] = None) -> list[PollTarget]:
    """Every registry poll target PLUS the non-registry artifacts of :data:`EXTRA_TARGETS`.

    This is what the poller runs. ``poll_targets`` is left untouched and registry-pure so the
    registry-coverage pin (test_freshness_poller.py:123) keeps meaning what it says."""
    return poll_targets(registry) + list(EXTRA_TARGETS)


def metric_data_for(
    table: str,
    family: str,
    lag: float,
    *,
    timestamp: datetime,
    expected: Optional[float] = None,
) -> list[dict]:
    """CloudWatch ``MetricDatum`` dicts for one table's lag, dimensioned ``[Table]`` and ``[Family]``.

    The ``[Table]`` datapoint feeds the precise per-table alarm; the ``[Family]`` datapoint feeds the
    coarse per-family alarm (statistic=Maximum, so the family reads its stalest member). ``Unit`` is
    ``None`` -- CloudWatch has no "days" unit and the alarm thresholds are bare day counts.

    Returns TWO datums (``FreshnessLagDays`` x {Table, Family}) always, and FOUR when ``expected``
    yields a ratio -- the two extra being ``FreshnessLagRatio`` on the SAME two dimensions
    (D-PR-14). The day-based datums are byte-identical either way: the ratio is emitted ALONGSIDE,
    never instead of, because a rename would orphan all 26 live ``FreshnessLagDays`` alarms in one
    poll cycle. ``expected=None`` (or a non-positive ceiling) is a normal, non-fatal state -- the
    table simply keeps only its day metric."""
    base = {
        "MetricName": METRIC_NAME,
        "Timestamp": timestamp,
        "Value": float(lag),
        "Unit": "None",
    }
    data = [
        {**base, "Dimensions": [{"Name": "Table", "Value": table}]},
        {**base, "Dimensions": [{"Name": "Family", "Value": family}]},
    ]
    ratio = lag_ratio(lag, expected)
    if ratio is None:
        return data
    ratio_base = {
        "MetricName": RATIO_METRIC_NAME,
        "Timestamp": timestamp,
        "Value": float(ratio),
        "Unit": "None",
    }
    data.extend([
        {**ratio_base, "Dimensions": [{"Name": "Table", "Value": table}]},
        {**ratio_base, "Dimensions": [{"Name": "Family", "Value": family}]},
    ])
    return data


def is_breaching(lag: Optional[float], expected: Optional[float]) -> bool:
    """True when this table is past its OWN declared ceiling -- the per-member breach predicate.

    THE EMPTY PREFIX COUNTS AS A BREACH (``lag is None``), and that is load-bearing rather than
    convenient. The poller emits NO ``FreshnessLagDays`` datapoint for a table whose canonical
    prefix has zero objects; today that absence is caught only by ``treat_missing_data =
    'breaching'`` on the per-TABLE alarm, which exactly five tables have. The family breach-count
    datapoint is written on EVERY poll cycle, so scoring an empty prefix 0 here would make the
    replacement metric strictly WEAKER than the metric it replaces -- the failure mode this
    estate keeps re-learning.

    A table with no declared ceiling (``expected`` None or non-positive) CANNOT breach and scores
    0; :func:`breach_counts` still counts it as a member so the family keeps emitting."""
    if lag is None:
        return True
    ratio = lag_ratio(lag, expected)
    if ratio is None:
        return False
    return ratio > 1.0


def breach_counts(
    rows: Iterable[tuple[str, Optional[float], Optional[float]]],
) -> dict[str, int]:
    """``{family: number of member tables past their own ceiling}``, for EVERY family seen.

    ``rows`` is ``(family, lag_days_or_None, expected_or_None)`` -- one row per polled table.

    A family with zero breaches is present with value 0, DELIBERATELY. An alarm that only
    receives a datapoint while it is breaching can never CLEAR, and the breach-count alarms are
    ``treat_missing_data = 'breaching'`` (a poller that dies must page), so a healthy family that
    stopped emitting would page within one evaluation period."""
    counts: dict[str, int] = {}
    for family, lag, expected in rows:
        counts.setdefault(family, 0)
        if is_breaching(lag, expected):
            counts[family] += 1
    return counts


def breach_metric_data(counts: dict[str, int], *, timestamp: datetime) -> list[dict]:
    """One ``FreshnessBreachCount{Family}`` MetricDatum per family, ordered by family name.

    ``Unit`` is ``"Count"`` -- unlike the two lag metrics (which are bare day numbers CloudWatch
    has no unit for), this one really is a count of things."""
    return [
        {
            "MetricName": BREACH_METRIC_NAME,
            "Timestamp": timestamp,
            "Value": float(counts[family]),
            "Unit": "Count",
            "Dimensions": [{"Name": "Family", "Value": family}],
        }
        for family in sorted(counts)
    ]
